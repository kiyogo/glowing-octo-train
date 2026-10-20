"""Account loading: Playwright cookie dumps, fbreg accounts.jsonl, browser stores.

Every source is normalised into one shape:

    Account(name, uid, cookies: dict[str, str], proxy: str | None)

so the sender never has to care where a session came from.
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

FB_DOMAINS = (".facebook.com", "facebook.com", ".messenger.com")

# cookies that matter for an authenticated session
WANTED = ("c_user", "xs", "datr", "sb", "fr", "presence", "dpr", "wd")


@dataclass
class Account:
    name: str
    uid: str
    cookies: dict[str, str]
    proxy: str | None = None
    dead: bool = False
    note: str = ""
    extra: dict = field(default_factory=dict)

    def alive(self) -> bool:
        return not self.dead and "c_user" in self.cookies and "xs" in self.cookies

    def __str__(self) -> str:
        return f"{self.name}({self.uid})"


# --------------------------------------------------------------------------
# cookie blob -> dict
# --------------------------------------------------------------------------

def _cookies_to_dict(raw) -> dict[str, str]:
    """Accept Playwright list, {name:value} dict, or 'a=b; c=d' string."""
    out: dict[str, str] = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            if isinstance(v, dict):
                out[str(k)] = str(v.get("value", ""))
            else:
                out[str(k)] = str(v)
        return out
    if isinstance(raw, str):
        for part in raw.split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                out[k.strip()] = v.strip()
        return out
    for c in raw or []:
        if not isinstance(c, dict):
            continue
        name = c.get("name")
        dom = c.get("domain") or ""
        if not name:
            continue
        if dom and not any(dom.endswith(d.lstrip(".")) for d in FB_DOMAINS):
            continue
        out[name] = str(c.get("value", ""))
    return out


def account_from_cookie_file(path: Path) -> Account | None:
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

    if isinstance(blob, dict) and "cookies" in blob:
        data = blob
    elif isinstance(blob, list):
        data = {"cookies": blob}
    elif isinstance(blob, dict):
        data = {"cookies": [{"name": k, "value": v} for k, v in blob.items()]}
    else:
        return None

    cookies = _cookies_to_dict(data.get("cookies"))
    uid = cookies.get("c_user", "")
    if not uid:
        return None
    name = path.stem.replace(".mailbox", "")
    return Account(name=name, uid=uid, cookies=cookies,
                   proxy=None if data.get("proxy") in (None, "", "direct") else data.get("proxy"),
                   note=data.get("note", ""))


# --------------------------------------------------------------------------
# fbreg accounts.jsonl
# --------------------------------------------------------------------------

def load_jsonl(path: Path) -> list[Account]:
    out: list[Account] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("status") not in (None, "success"):
            continue
        cookies = _cookies_to_dict(rec.get("cookies"))
        uid = rec.get("user_id") or cookies.get("c_user", "")
        if not uid or "xs" not in cookies:
            continue
        out.append(Account(
            name=rec.get("email") or uid,
            uid=str(uid),
            cookies=cookies,
            proxy=None if rec.get("proxy") in (None, "", "direct") else rec.get("proxy"),
            note=rec.get("note", ""),
        ))
    return out


# --------------------------------------------------------------------------
# local browser stores (Chrome family + Firefox), Windows
# --------------------------------------------------------------------------

CHROME_ROOTS = {
    "chrome": Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/User Data",
    "edge": Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Edge/User Data",
    "brave": Path(os.environ.get("LOCALAPPDATA", "")) / "BraveSoftware/Brave-Browser/User Data",
    "opera": Path(os.environ.get("APPDATA", "")) / "Opera Software/Opera Stable",
    "vivaldi": Path(os.environ.get("LOCALAPPDATA", "")) / "Vivaldi/User Data",
}
FIREFOX_ROOT = Path(os.environ.get("APPDATA", "")) / "Mozilla/Firefox/Profiles"


def _dpapi(blob: bytes) -> bytes:
    import win32crypt  # pywin32
    return win32crypt.CryptUnprotectData(blob, None, None, None, 0)[1]


def _master_key(user_data: Path) -> bytes | None:
    state = user_data / "Local State"
    if not state.exists():
        return None
    try:
        blob = json.loads(state.read_text(encoding="utf-8"))
        enc = base64.b64decode(blob["os_crypt"]["encrypted_key"])
    except Exception:
        return None
    if enc[:5] != b"DPAPI":
        return None
    try:
        return _dpapi(enc[5:])
    except Exception:
        return None


def _decrypt(key: bytes | None, blob: bytes) -> str:
    if blob[:3] in (b"v10", b"v11"):
        if not key:
            return ""
        from Crypto.Cipher import AES
        nonce, ct, tag = blob[3:15], blob[15:-16], blob[-16:]
        try:
            return AES.new(key, AES.MODE_GCM, nonce=nonce).decrypt_and_verify(ct, tag).decode("utf-8", "ignore")
        except Exception:
            return ""
    if blob[:3] == b"v20":
        # Chrome 127+ app-bound encryption: not readable without the browser's own broker.
        return ""
    try:
        return _dpapi(blob).decode("utf-8", "ignore")
    except Exception:
        return ""


def _read_chrome_db(db: Path, key: bytes | None) -> dict[str, str]:
    tmp = Path(tempfile.mkdtemp(prefix="ck_")) / "Cookies"
    shutil.copy2(db, tmp)
    out: dict[str, str] = {}
    con = sqlite3.connect(tmp)
    try:
        rows = con.execute(
            "SELECT name, encrypted_value, value, host_key FROM cookies "
            "WHERE host_key LIKE '%facebook.com' OR host_key LIKE '%messenger.com'"
        ).fetchall()
    finally:
        con.close()
        shutil.rmtree(tmp.parent, ignore_errors=True)
    for name, enc, plain, _host in rows:
        val = plain or _decrypt(key, enc or b"")
        if val:
            out[name] = val
    return out


def extract_browsers(which: list[str] | None = None) -> list[Account]:
    """Pull live FB sessions out of whatever browser is installed here."""
    found: list[Account] = []
    seen: set[str] = set()

    for tag, root in CHROME_ROOTS.items():
        if which and tag not in which:
            continue
        if not root or not root.exists():
            continue
        key = _master_key(root)
        profiles = [root] + [p for p in root.iterdir() if p.is_dir() and (p / "Network").exists()]
        for prof in profiles:
            db = prof / "Network" / "Cookies"
            if not db.exists():
                db = prof / "Cookies"
            if not db.exists():
                continue
            try:
                cookies = _read_chrome_db(db, key)
            except Exception:
                continue
            uid = cookies.get("c_user")
            if not uid or "xs" not in cookies or uid in seen:
                continue
            seen.add(uid)
            found.append(Account(name=f"{tag}:{prof.name}", uid=uid, cookies=cookies))

    if not which or "firefox" in which:
        if FIREFOX_ROOT.exists():
            for prof in FIREFOX_ROOT.iterdir():
                db = prof / "cookies.sqlite"
                if not db.exists():
                    continue
                tmp = Path(tempfile.mkdtemp(prefix="ff_")) / "cookies.sqlite"
                shutil.copy2(db, tmp)
                cookies: dict[str, str] = {}
                try:
                    con = sqlite3.connect(tmp)
                    for name, value in con.execute(
                        "SELECT name, value FROM moz_cookies "
                        "WHERE host LIKE '%facebook.com' OR host LIKE '%messenger.com'"
                    ):
                        if value:
                            cookies[name] = value
                    con.close()
                except Exception:
                    pass
                finally:
                    shutil.rmtree(tmp.parent, ignore_errors=True)
                uid = cookies.get("c_user")
                if uid and "xs" in cookies and uid not in seen:
                    seen.add(uid)
                    found.append(Account(name=f"firefox:{prof.name}", uid=uid, cookies=cookies))
    return found


# --------------------------------------------------------------------------
# one entry point
# --------------------------------------------------------------------------

def load_accounts(paths: list[str], from_browsers: bool = False,
                  browsers: list[str] | None = None) -> list[Account]:
    accounts: list[Account] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            for f in sorted(p.rglob("*.json")):
                a = account_from_cookie_file(f)
                if a:
                    accounts.append(a)
        elif p.suffix == ".jsonl":
            accounts.extend(load_jsonl(p))
        elif p.suffix == ".json":
            a = account_from_cookie_file(p)
            if a:
                accounts.append(a)
        elif p.suffix in (".txt", ".csv"):
            for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                cookies = _cookies_to_dict(line)
                uid = cookies.get("c_user", "")
                if uid and "xs" in cookies:
                    accounts.append(Account(name=uid, uid=uid, cookies=cookies))

    if from_browsers:
        accounts.extend(extract_browsers(browsers))

    # dedupe by uid, keep first
    uniq: dict[str, Account] = {}
    for a in accounts:
        uniq.setdefault(a.uid, a)
    return list(uniq.values())
