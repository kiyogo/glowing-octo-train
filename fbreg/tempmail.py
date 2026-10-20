"""temp-mail.org mailbox driver: create, poll, extract the code or the link.

The public web app talks to `web2.temp-mail.org` with a bearer JWT:

    POST /mailbox              -> {"token": "...", "mailbox": "x@y"}
    GET  /messages             -> {"mailbox": "x@y", "messages": [...]}
    GET  /messages/<id>        -> full body (text + html)

Everything below normalises those payloads so the rest of the tool never has to
care which key this week's build decided to use.
"""
from __future__ import annotations

import html as htmlmod
import logging
import re
import time
from dataclasses import dataclass, field

import requests

log = logging.getLogger("fbreg.tempmail")

BASE = "https://web2.temp-mail.org"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"),
    "Origin": "https://temp-mail.org",
    "Referer": "https://temp-mail.org/vi/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

CODE_RE = re.compile(r"(?<!\d)(\d{5,8})(?!\d)")
SPACED_CODE_RE = re.compile(r"(?<!\d)(\d{3})[ -](\d{3})(?!\d)")
FB_LINK_RE = re.compile(
    r"https?://(?:www\.|m\.|mbasic\.)?facebook\.com/[^\s\"'<>]*"
    r"(?:confirm|verify|code|confirm_email|activate)[^\s\"'<>]*", re.I)


@dataclass
class Mail:
    id: str
    sender: str
    subject: str
    text: str
    html: str = ""
    raw: dict = field(default_factory=dict)

    def code(self) -> str:
        blob = f"{self.subject}\n{self.text}\n{self.html}"
        m = SPACED_CODE_RE.search(blob)
        if m:
            return m.group(1) + m.group(2)
        m = CODE_RE.search(blob)
        return m.group(1) if m else ""

    def link(self) -> str:
        blob = self.text + "\n" + self.html
        m = FB_LINK_RE.search(blob)
        return htmlmod.unescape(m.group(0)) if m else ""


class Mailbox:
    """One disposable inbox, owned by one identity."""

    def __init__(self, email: str, token: str):
        self.email = email
        self.token = token
        self.s = requests.Session()
        self.s.headers.update(HEADERS)
        self.s.headers["Authorization"] = f"Bearer {token}"
        self._seen: set[str] = set()

    @classmethod
    def create(cls, timeout: int = 25) -> "Mailbox":
        r = requests.post(f"{BASE}/mailbox", headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        d = r.json()
        if not d.get("token") or not d.get("mailbox"):
            raise RuntimeError(f"temp-mail create returned {d}")
        log.info("temp-mail: %s", d["mailbox"])
        return cls(d["mailbox"], d["token"])

    # ---------- reading ----------

    def messages(self, timeout: int = 25) -> list[dict]:
        r = self.s.get(f"{BASE}/messages", timeout=timeout)
        if r.status_code != 200:
            log.debug("messages: %s %s", r.status_code, r.text[:120])
            return []
        try:
            d = r.json()
        except ValueError:
            return []
        return d.get("messages") or d.get("data") or []

    def full(self, mid: str, timeout: int = 25) -> dict:
        r = self.s.get(f"{BASE}/messages/{mid}", timeout=timeout)
        if r.status_code != 200:
            return {}
        try:
            return r.json()
        except ValueError:
            return {}

    @staticmethod
    def _normalise(d: dict) -> Mail:
        sender = d.get("from") or d.get("sender") or ""
        if isinstance(sender, dict):
            sender = sender.get("address") or sender.get("name") or ""
        mid = str(d.get("_id") or d.get("id") or "")
        text = (d.get("text") or d.get("body") or d.get("bodyPreview")
                or d.get("intro") or "")
        return Mail(id=mid, sender=str(sender), subject=d.get("subject") or "",
                    text=text or "", html=d.get("html") or "", raw=d)

    def wait_for(self, timeout: int = 180, poll: int = 5,
                 match: str | None = None) -> Mail | None:
        """Poll until a mail lands. Returns the newest match, or None."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            for d in self.messages():
                m = self._normalise(d)
                if not m.id or m.id in self._seen:
                    continue
                if match and match.lower() not in (m.sender + m.subject).lower():
                    continue
                full = self.full(m.id)
                if full:
                    m = self._normalise(full)
                self._seen.add(m.id)
                log.info("mail: from=%s subject=%r", m.sender, m.subject[:60])
                if m.text or m.html or m.code() or m.link():
                    return m
            time.sleep(poll)
        return None

    def wait_for_code(self, timeout: int = 180, poll: int = 5) -> str:
        """Wait for the first mail that actually carries a code or a link."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            for d in self.messages():
                m = self._normalise(d)
                if not m.id or m.id in self._seen:
                    continue
                full = self.full(m.id)
                if full:
                    m = self._normalise(full)
                self._seen.add(m.id)
                code = m.code()
                if code:
                    log.info("code %s from %r", code, m.subject[:50])
                    return code
                link = m.link()
                if link:
                    log.info("confirmation link from %r", m.subject[:50])
                    return link
            time.sleep(poll)
        return ""

    def wait_for_link(self, timeout: int = 90, poll: int = 5) -> str:
        """Specifically wait for a facebook confirmation URL."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            for d in self.messages():
                m = self._normalise(d)
                if not m.id or m.id in self._seen:
                    continue
                full = self.full(m.id)
                if full:
                    m = self._normalise(full)
                link = m.link()
                if link:
                    self._seen.add(m.id)
                    log.info("confirm link from %r", m.subject[:50])
                    return link
                self._seen.add(m.id)
            time.sleep(poll)
        return ""


def is_link(value: str) -> bool:
    return value.startswith("http")
