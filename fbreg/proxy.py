"""Proxy pool: parse, health-check, rotate, cool down on failure."""
from __future__ import annotations

import json
import logging
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

import requests

log = logging.getLogger("fbreg.proxy")


@dataclass
class Proxy:
    url: str
    fails: int = 0
    banned_until: float = 0.0
    ok: bool = False
    last_ip: str = ""
    last_latency: float = 0.0

    @property
    def alive(self) -> bool:
        return time.time() >= self.banned_until

    def proxies_dict(self) -> dict:
        return {"http": self.url, "https": self.url}

    def __str__(self) -> str:
        return self.url


def _normalise(line: str) -> str | None:
    """Accept the usual four shapes people keep proxies in."""
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    if "://" in line:
        scheme, rest = line.split("://", 1)
        scheme = scheme.lower()
        if scheme not in ("http", "https", "socks4", "socks5", "socks5h"):
            return None
        return f"{scheme}://{rest}"
    parts = line.split(":")
    if len(parts) == 2:                      # host:port
        return f"http://{parts[0]}:{parts[1]}"
    if len(parts) == 4:                      # host:port:user:pass
        h, p, u, pw = parts
        return f"http://{quote(u, safe='')}:{quote(pw, safe='')}@{h}:{p}"
    if len(parts) == 5:                      # user:pass@host:port split weirdly
        u, pw, h, p = parts[0], parts[1], parts[2], parts[3]
        return f"http://{quote(u, safe='')}:{quote(pw, safe='')}@{h}:{p}"
    return None


def load_proxies(path: str) -> list[str]:
    p = Path(path)
    if not p.exists():
        log.warning("proxy file %s not found", path)
        return []
    out, seen = [], set()
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        u = _normalise(line)
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    log.info("loaded %d proxies from %s", len(out), path)
    return out


class ProxyPool:
    def __init__(self, urls: list[str], timeout: int = 15, check_url: str = "",
                 cooldown: int = 600):
        self.timeout = timeout
        self.check_url = check_url or "https://api.ipify.org?format=json"
        self.cooldown = cooldown
        self._lock = threading.Lock()
        self.items: list[Proxy] = [Proxy(u) for u in urls]

    def __len__(self) -> int:
        return len(self.items)

    def alive(self) -> list[Proxy]:
        with self._lock:
            return [p for p in self.items if p.alive]

    def check(self, p: Proxy) -> bool:
        t0 = time.time()
        try:
            r = requests.get(self.check_url, proxies=p.proxies_dict(),
                             timeout=self.timeout)
            if r.status_code != 200:
                raise RuntimeError(f"status {r.status_code}")
            try:
                p.last_ip = r.json().get("ip") or r.text.strip()[:64]
            except Exception:
                p.last_ip = r.text.strip()[:64]
            p.last_latency = round(time.time() - t0, 2)
            p.ok = True
            p.fails = 0
            return True
        except Exception as exc:                       # noqa: BLE001
            p.ok = False
            p.last_ip = f"err:{type(exc).__name__}"
            return False

    def check_all(self, threads: int = 32) -> int:
        if not self.items:
            return 0
        with ThreadPoolExecutor(max_workers=min(threads, len(self.items))) as ex:
            list(ex.map(self.check, self.items))
        good = sum(1 for p in self.items if p.ok)
        log.info("proxy health: %d/%d alive", good, len(self.items))
        return good

    def get(self, prefer_fresh: bool = True) -> Proxy | None:
        with self._lock:
            live = [p for p in self.items if p.alive]
        if not live:
            return None
        if prefer_fresh:
            fresh = [p for p in live if p.fails == 0]
            if fresh:
                live = fresh
        return random.choice(live)

    def penalise(self, p: Proxy, hard: bool = False) -> None:
        with self._lock:
            p.fails += 1
            if hard or p.fails >= 3:
                p.banned_until = time.time() + self.cooldown
                log.warning("proxy benched %ds (%d fails): %s", self.cooldown, p.fails, p.url)

    def report(self) -> str:
        lines, good = [], 0
        for p in self.items:
            flag = "OK " if p.ok else "BAD"
            if p.ok:
                good += 1
            lines.append(f"{flag} {p.url:<55} ip={p.last_ip:<16} {p.last_latency}s")
        return f"{good}/{len(self.items)} alive\n" + "\n".join(lines)
