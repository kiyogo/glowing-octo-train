"""Scrape the tokens Facebook actually put on the page, instead of hardcoding them.

Anything the server rendered is fair game: hidden inputs, LSD, jazoest, fb_dtsg,
reg_instance, the arkose wrapper. Values rotate per response, so they are always
re-read from the live body.
"""
from __future__ import annotations

import re

INPUT_RE = re.compile(r"<input\b([^>]*)>", re.I | re.S)
SELECT_RE = re.compile(r"<select\b([^>]*)>(.*?)</select>", re.I | re.S)
OPTION_RE = re.compile(r"<option\b([^>]*)>", re.I | re.S)
ATTR_RE = re.compile(r"""([:\w-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", re.S)


def _attrs(blob: str) -> dict:
    out = {}
    for m in ATTR_RE.finditer(blob):
        key = m.group(1).lower()
        val = m.group(2) if m.group(2) is not None else (
            m.group(3) if m.group(3) is not None else (m.group(4) or ""))
        out[key] = val
    return out


def parse_fields(html: str) -> dict:
    """Every named input/select with a usable value."""
    fields: dict[str, str] = {}
    for m in INPUT_RE.finditer(html):
        a = _attrs(m.group(1))
        name = a.get("name")
        if not name:
            continue
        if a.get("type", "").lower() in ("submit", "button", "image", "file"):
            if a.get("type", "").lower() != "submit":
                continue
        if a.get("disabled") is not None:
            continue
        fields[name] = a.get("value", "")
    for m in SELECT_RE.finditer(html):
        a = _attrs(m.group(1))
        name = a.get("name")
        if not name:
            continue
        opts = [(_attrs(o.group(1)), o.group(1)) for o in OPTION_RE.finditer(m.group(2))]
        chosen = next((a for a, raw in opts if "selected" in a
                       or re.search(r"\bselected\b", raw, re.I)), None)
        if chosen is None and opts:
            chosen = opts[0][0]
        fields[name] = chosen.get("value", "") if chosen else ""
    return fields


def find_lsd(html: str) -> str:
    for pat in (r'name="lsd"\s+value="([^"]+)"',
                r'"LSD",\[\],\{"token":"([^"]+)"\}',
                r'"lsd"\s*:\s*"([^"]+)"'):
        m = re.search(pat, html)
        if m:
            return m.group(1)
    return ""


def jazoest_from(lsd: str) -> str:
    """FB derives this client-side; the derivation is stable."""
    return "2" + str(sum(ord(c) for c in lsd)) if lsd else ""


def find_dtsg(html: str) -> str:
    for pat in (r'name="fb_dtsg"\s+value="([^"]+)"',
                r'"DTSGInitialData",\[\],\{"token":"([^"]+)"\}',
                r'"fb_dtsg"\s*:\s*"([^"]+)"'):
        m = re.search(pat, html)
        if m:
            return m.group(1)
    return ""


def find_reg_instance(html: str) -> str:
    m = re.search(r'reg_instance["\']?\s*[:=]\s*["\']([A-Za-z0-9_-]{10,})', html)
    return m.group(1) if m else ""


def find_ccp(html: str, default: str = "") -> str:
    m = re.search(r'name="ccp"\s+value="(\d+)"', html)
    return m.group(1) if m else default
