"""One Facebook session: bootstrap, resolve a thread, push a message.

Everything goes through mbasic — it still speaks plain HTML forms, it is
cheap on the account, and a fresh thread can be opened from a bare user id.
A desktop fallback exists for accounts where mbasic is unavailable.
"""
from __future__ import annotations

import html
import random
import re
import time
from dataclasses import dataclass
from enum import Enum
from urllib.parse import quote_plus

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .cookies import Account


class Status(str, Enum):
    OK = "ok"
    CHECKPOINT = "checkpoint"
    RATE = "ratelimit"
    DEAD = "dead"
    THREAD = "no_thread"
    FAIL = "fail"


MOBILE_UAS = [
    "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36",
]
DESKTOP_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

RE_DTSG = re.compile(r'name="fb_dtsg"\s+value="([^"]+)"')
RE_JAZO = re.compile(r'name="jazoest"\s+value="([^"]+)"')
RE_TID = [
    re.compile(r'name="tids"\s+value="(\d+)"'),
    re.compile(r'/messages/read/\?tid=(\d+)'),
    re.compile(r'"thread_fbid"\s*:\s*"(\d+)"'),
    re.compile(r'tid=(\d+)'),
]
RE_PROFILE_ID = [
    re.compile(r'"profile_id"\s*:\s*"(\d+)"'),
    re.compile(r'"userID"\s*:\s*"(\d+)"'),
    re.compile(r'/profile\.php\?id=(\d+)'),
]


def expand_spintax(text: str) -> str:
    """{a|b|c} -> one option. Handles nesting by repeating the pass."""
    pat = re.compile(r"\{([^{}]*)\}")
    for _ in range(12):
        m = pat.search(text)
        if not m:
            break
        choices = m.group(1).split("|")
        text = text[:m.start()] + random.choice(choices) + text[m.end():]
    return text


@dataclass
class SendResult:
    status: Status
    detail: str = ""
    tid: str = ""


class FBClient:
    def __init__(self, account: Account, timeout: int = 30, proxy: str | None = None):
        self.account = account
        self.timeout = timeout
        self.mobile = True
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": random.choice(MOBILE_UAS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "DNT": "1",
            "Upgrade-Insecure-Requests": "1",
        })
        for name, value in account.cookies.items():
            self.s.cookies.set(name, value, domain=".facebook.com", path="/")
        p = proxy or account.proxy
        if p and p != "direct":
            self.s.proxies.update({"http": p, "https": p})

        retry = Retry(total=2, backoff_factor=0.6,
                      status_forcelist=(500, 502, 503, 504),
                      allowed_methods=frozenset(["GET", "POST"]),
                      raise_on_status=False)
        ad = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
        self.s.mount("https://", ad)
        self.s.mount("http://", ad)

        self.fb_dtsg = ""
        self.jazoest = ""
        self.detail = ""
        self._tids: dict[str, str] = {}
        self.uid = account.uid

    # ------------------------------------------------------------------ http

    def _get(self, url: str, referer: str | None = None) -> requests.Response:
        h = {"Referer": referer} if referer else {}
        return self.s.get(url, headers=h, timeout=self.timeout, allow_redirects=True)

    def _post(self, url: str, data: dict, referer: str | None = None) -> requests.Response:
        h = {"Referer": referer} if referer else {}
        return self.s.post(url, data=data, headers=h, timeout=self.timeout, allow_redirects=True)

    @staticmethod
    def _looks_logged_out(r: requests.Response) -> bool:
        if "/login" in r.url and "checkpoint" not in r.url:
            return True
        return "login_form" in r.text[:4000] or 'id="login_form"' in r.text[:4000]

    # -------------------------------------------------------------- bootstrap

    def boot(self) -> Status:
        """Open mbasic, harvest fb_dtsg/jazoest. Cheap, one page."""
        try:
            r = self._get("https://mbasic.facebook.com/home.php")
        except requests.RequestException as e:
            self.detail = str(e)[:160]
            return Status.FAIL

        if self._looks_logged_out(r):
            self.account.dead = True
            self.detail = "logged out"
            return Status.DEAD

        text = r.text
        m = RE_DTSG.search(text) or re.search(r'"token":"([^"]+)"', text)
        if m:
            self.fb_dtsg = html.unescape(m.group(1))
        j = RE_JAZO.search(text)
        if j:
            self.jazoest = j.group(1)

        if not self.fb_dtsg:
            # mbasic sometimes omits the token on the home feed; grab it on messages
            r2 = self._get("https://mbasic.facebook.com/messages/")
            m = RE_DTSG.search(r2.text)
            if m:
                self.fb_dtsg = html.unescape(m.group(1))
            j = RE_JAZO.search(r2.text)
            if j:
                self.jazoest = j.group(1)

        if not self.jazoest and self.fb_dtsg:
            # jazoest = '2' + sum of ord() of the dtsg
            self.jazoest = "2" + str(sum(ord(c) for c in self.fb_dtsg))

        return Status.OK if self.fb_dtsg else Status.FAIL

    # --------------------------------------------------------------- resolving

    def resolve_username(self, username: str) -> str:
        """username -> numeric id."""
        try:
            r = self._get(f"https://mbasic.facebook.com/{quote_plus(username)}")
        except requests.RequestException:
            return ""
        for pat in RE_PROFILE_ID:
            m = pat.search(r.text)
            if m:
                return m.group(1)
        return ""

    def thread_for(self, uid: str) -> str:
        """Find (or create) the 1:1 thread id with a user."""
        if uid in self._tids:
            return self._tids[uid]
        url = f"https://mbasic.facebook.com/messages/compose/?id={uid}"
        try:
            r = self._get(url, referer="https://mbasic.facebook.com/messages/")
        except requests.RequestException:
            return ""
        if self._looks_logged_out(r):
            self.account.dead = True
            return ""
        for pat in RE_TID:
            m = pat.search(r.text)
            if m:
                self._tids[uid] = m.group(1)
                return m.group(1)
        # compose page sometimes already redirects into the thread
        m = re.search(r"/messages/read/\?tid=(\d+)", r.url)
        if m:
            self._tids[uid] = m.group(1)
            return m.group(1)
        return ""

    # ------------------------------------------------------------------- send

    def send(self, uid: str, body: str) -> SendResult:
        if self.account.dead:
            return SendResult(Status.DEAD, "marked dead")
        if not self.fb_dtsg:
            st = self.boot()
            if st is not Status.OK:
                return SendResult(st, self.detail or "boot failed")

        tid = self.thread_for(uid)
        if not tid:
            # desktop fallback: fire straight at the user fbid
            return self._send_desktop(uid, body)

        data = {
            "fb_dtsg": self.fb_dtsg,
            "jazoest": self.jazoest,
            "tids": tid,
            "body": body,
            "send": "Send",
            "wwwupp": "1",
        }
        try:
            r = self._post("https://mbasic.facebook.com/messages/send/?icm=1",
                           data, referer=f"https://mbasic.facebook.com/messages/read/?tid={tid}")
        except requests.RequestException as e:
            return SendResult(Status.FAIL, str(e)[:120], tid)

        return self._classify(r, tid)

    def _send_desktop(self, uid: str, body: str) -> SendResult:
        if self.s.headers.get("User-Agent", "").startswith("Mozilla/5.0 (Linux; Android"):
            self.s.headers["User-Agent"] = DESKTOP_UA
        try:
            g = self._get("https://www.facebook.com/messages/t/")
            m = RE_DTSG.search(g.text)
            if m:
                self.fb_dtsg = html.unescape(m.group(1))
        except requests.RequestException:
            pass
        data = {
            "fb_dtsg": self.fb_dtsg,
            "jazoest": self.jazoest,
            "body": body,
            "other_user_fbid": uid,
            "send": "Send",
        }
        try:
            r = self._post("https://www.facebook.com/messages/send/", data,
                           referer="https://www.facebook.com/messages/")
        except requests.RequestException as e:
            return SendResult(Status.FAIL, str(e)[:120])
        return self._classify(r, "")

    @staticmethod
    def _classify(r: requests.Response, tid: str) -> SendResult:
        blob = (r.text or "")[:20000].lower()
        url = r.url.lower()

        if r.status_code == 429 or "too many requests" in blob:
            return SendResult(Status.RATE, "429", tid)
        if "checkpoint" in url or "checkpoint" in blob[:4000]:
            return SendResult(Status.CHECKPOINT, "checkpoint", tid)
        if "temporarily blocked" in blob or "action blocked" in blob or "you're blocked" in blob:
            return SendResult(Status.CHECKPOINT, "action blocked", tid)
        if "login_form" in blob[:4000] or "/login" in url:
            return SendResult(Status.DEAD, "session dead", tid)
        if "message could not be sent" in blob or "error" in blob and "couldn't send" in blob:
            return SendResult(Status.FAIL, "send error", tid)
        return SendResult(Status.OK, "", tid)

    def ping(self) -> bool:
        """Live check without sending anything."""
        try:
            r = self._get("https://mbasic.facebook.com/profile.php")
            return not self._looks_logged_out(r)
        except requests.RequestException:
            return False

    def close(self) -> None:
        try:
            self.s.close()
        except Exception:
            pass
