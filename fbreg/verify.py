"""Catch-all mailbox polling for the confirmation mail."""
from __future__ import annotations

import email
import imaplib
import logging
import re
import time
from email.header import decode_header

log = logging.getLogger("fbreg.verify")

LINK_RE = re.compile(r"https://(?:www\.|m\.|mbasic\.)?facebook\.com/[^\s\"'<>]*(?:confirm|verify|code)[^\s\"'<>]*",
                     re.I)
CODE_RE = re.compile(r"\b(\d{5,6})\b")


def _decode(raw: str) -> str:
    if not raw:
        return ""
    parts = []
    for chunk, enc in decode_header(raw):
        parts.append(chunk.decode(enc or "utf-8", "ignore") if isinstance(chunk, bytes) else chunk)
    return "".join(parts)


def _body(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                return (part.get_payload(decode=True) or b"").decode("utf-8", "ignore")
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                return (part.get_payload(decode=True) or b"").decode("utf-8", "ignore")
        return ""
    return (msg.get_payload(decode=True) or b"").decode("utf-8", "ignore")


def wait_for_link(host: str, port: int, user: str, password: str, address: str,
                  timeout: int = 180, poll: int = 10) -> tuple[str, str]:
    """Returns (link, code). Either may be empty. Raises on auth problems."""
    deadline = time.time() + timeout
    inbox = imaplib.IMAP4_SSL(host, port)
    try:
        inbox.login(user, password)
        while time.time() < deadline:
            inbox.select("INBOX")
            typ, data = inbox.search(None, f'(TO "{address}" UNSEEN)')
            ids = (data[0].split() if data and data[0] else [])
            for mid in reversed(ids):
                typ, raw = inbox.fetch(mid, "(RFC822)")
                if typ != "OK" or not raw or not raw[0]:
                    continue
                msg = email.message_from_bytes(raw[0][1])
                subject = _decode(msg.get("Subject", ""))
                body = _body(msg)
                text = f"{subject}\n{body}"
                link_m = LINK_RE.search(text)
                code_m = CODE_RE.search(text)
                if link_m or code_m:
                    inbox.store(mid, "+FLAGS", "\\Seen")
                    return (link_m.group(0) if link_m else "",
                            code_m.group(1) if code_m else "")
            time.sleep(poll)
        return "", ""
    finally:
        try:
            inbox.logout()
        except Exception:                          # noqa: BLE001
            pass
