"""Arkose Labs (FunCaptcha) solving. Adapter per vendor + a manual fallback."""
from __future__ import annotations

import json
import logging
import re
import time

import requests

log = logging.getLogger("fbreg.captcha")

GUID = re.compile(r"[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}")


class CaptchaError(RuntimeError):
    pass


def harvest_sitekey(html: str) -> str:
    """Pull the arkose public key out of whatever wrapper FB served."""
    guid = GUID.pattern
    patterns = (
        r'"sitekey"\s*:\s*"([^"]+)"',
        r'data-arkose-sitekey="([^"]+)"',
        r'arkose[^"\']{0,80}?["\'](' + guid + r')["\']',
        r'siteKey["\']?\s*[:=]\s*["\'](' + guid + r')["\']',
    )
    for pat in patterns:
        m = re.search(pat, html, re.I)
        if m:
            return m.group(1)
    m = GUID.search(html)
    return m.group(0) if m else ""


def harvest_blob(html: str) -> str:
    """The `data` blob the arkose iframe is initialised with (encrypted blob)."""
    for pat in (r'data-blob="([^"]+)"', r'"blob"\s*:\s*"([^"]+)"',
                r'enhanced_fp["\']?\s*:\s*["\']([^"\']+)'):
        m = re.search(pat, html)
        if m:
            return m.group(1)
    return ""


# --------------------------------------------------------------------------- #
# vendors
# --------------------------------------------------------------------------- #

def _capsolver(key: str, sitekey: str, url: str, blob: str, timeout: int) -> str:
    base = "https://api.capsolver.com"
    task = {"type": "FunCaptchaTaskProxyLess", "websiteURL": url,
            "websitePublicKey": sitekey}
    if blob:
        task["data"] = json.dumps({"blob": blob})
    r = requests.post(f"{base}/createTask",
                      json={"clientKey": key, "task": task}, timeout=30).json()
    if r.get("errorId"):
        raise CaptchaError(f"capsolver create: {r.get('errorDescription')}")
    tid = r["taskId"]
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(3)
        res = requests.post(f"{base}/getTaskResult",
                            json={"clientKey": key, "taskId": tid}, timeout=30).json()
        if res.get("status") == "ready":
            return res["solution"]["token"]
        if res.get("errorId"):
            raise CaptchaError(f"capsolver poll: {res.get('errorDescription')}")
    raise CaptchaError("capsolver timeout")


def _twocaptcha(key: str, sitekey: str, url: str, blob: str, timeout: int) -> str:
    base = "https://2captcha.com"
    payload = {"key": key, "method": "funcaptcha", "publickey": sitekey,
               "pageurl": url, "json": 1}
    if blob:
        payload["data"] = blob
    r = requests.post(f"{base}/in.php", data=payload, timeout=30).json()
    if r.get("status") != 1:
        raise CaptchaError(f"2captcha submit: {r.get('request')}")
    tid = r["request"]
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(5)
        res = requests.get(f"{base}/res.php", params={
            "key": key, "action": "get", "id": tid, "json": 1}, timeout=30).json()
        if res.get("status") == 1:
            return res["request"]
        if res.get("request") not in ("CAPCHA_NOT_READY",):
            raise CaptchaError(f"2captcha poll: {res.get('request')}")
    raise CaptchaError("2captcha timeout")


def _anticaptcha(key: str, sitekey: str, url: str, blob: str, timeout: int) -> str:
    base = "https://api.anti-captcha.com"
    task = {"type": "FunCaptchaTaskProxyless", "websiteURL": url,
            "websitePublicKey": sitekey}
    if blob:
        task["data"] = json.dumps({"blob": blob})
    r = requests.post(f"{base}/createTask",
                      json={"clientKey": key, "task": task}, timeout=30).json()
    if r.get("errorId"):
        raise CaptchaError(f"anticaptcha create: {r.get('errorDescription')}")
    tid = r["taskId"]
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(3)
        res = requests.post(f"{base}/getTaskResult",
                            json={"clientKey": key, "taskId": tid}, timeout=30).json()
        if res.get("status") == "ready":
            return res["solution"]["token"]
        if res.get("errorId"):
            raise CaptchaError(f"anticaptcha poll: {res.get('errorDescription')}")
    raise CaptchaError("anticaptcha timeout")


def _manual(sitekey: str, url: str, blob: str, timeout: int) -> str:
    print("\n--- manual captcha ---")
    print(f"open: {url}")
    print(f"sitekey: {sitekey}")
    if blob:
        print(f"blob (paste into the arkose loader as data.blob):\n{blob[:400]}")
    print("solve it in a browser that matches the UA, then paste the token.")
    return input("token> ").strip()


VENDORS = {"capsolver": _capsolver, "2captcha": _twocaptcha,
           "anticaptcha": _anticaptcha, "manual": _manual}


def solve(solver: str, key: str, sitekey: str, page_url: str, blob: str,
          timeout: int = 180) -> str:
    if solver not in VENDORS:
        raise CaptchaError(f"no solver configured (got {solver!r})")
    if not sitekey:
        raise CaptchaError("no arkose sitekey (pass --arkose-sitekey)")
    log.info("solving arkose via %s", solver)
    return VENDORS[solver](key, sitekey, page_url, blob, timeout)
