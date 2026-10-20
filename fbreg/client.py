"""HTTP client bound to one identity + one proxy, with coherent browser headers."""
from __future__ import annotations

import logging
import random
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .identity import Identity
from .proxy import Proxy

log = logging.getLogger("fbreg.client")

DESKTOP_NAV = [
    "https://www.facebook.com/",
    "https://www.facebook.com/login/",
    "https://www.facebook.com/reg/",
]
MOBILE_NAV = [
    "https://m.facebook.com/",
    "https://mbasic.facebook.com/",
    "https://m.facebook.com/reg/",
]


def base_headers(ident: Identity) -> dict:
    """A header set that does not contradict itself between UA and client hints."""
    h = {
        "User-Agent": ident.user_agent,
        "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
                   "image/avif,image/webp,*/*;q=0.8"),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "sec-ch-ua": ident.sec_ch_ua,
        "sec-ch-ua-mobile": "?1" if ident.mobile else "?0",
        "sec-ch-ua-platform": f'"{ident.platform}"',
        "sec-ch-ua-platform-version": f'"{ident.platform_version}"',
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "same-origin",
        "sec-fetch-user": "?1",
        "upgrade-insecure-requests": "1",
        "Cache-Control": "max-age=0",
        "DNT": "1",
    }
    return h


class FBSession:
    """One session = one identity = one proxy. Never reuse across attempts."""

    def __init__(self, ident: Identity, proxy: Proxy | None, timeout: int = 30,
                 retries: int = 3):
        self.ident = ident
        self.proxy = proxy
        self.timeout = timeout
        self.s = requests.Session()
        self.s.headers.update(base_headers(ident))
        if proxy:
            self.s.proxies.update(proxy.proxies_dict())

        retry = Retry(total=retries, backoff_factor=0.8,
                      status_forcelist=(429, 500, 502, 503, 504),
                      allowed_methods=frozenset(["GET", "POST"]),
                      raise_on_status=False)
        ad = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
        self.s.mount("https://", ad)
        self.s.mount("http://", ad)

    # ---------- transport ----------

    def _prepare(self, url: str, referer: str | None = None,
                 ajax: bool = False) -> dict:
        h = {}
        if referer:
            h["Referer"] = referer
            h["sec-fetch-site"] = "same-origin"
        if ajax:
            h["X-Requested-With"] = "XMLHttpRequest"
            h["Accept"] = "*/*"
            h["sec-fetch-dest"] = "empty"
            h["sec-fetch-mode"] = "cors"
            h["sec-fetch-site"] = "same-origin"
        return h

    def get(self, url: str, referer: str | None = None, **kw) -> requests.Response:
        h = self._prepare(url, referer)
        h.update(kw.pop("headers", {}))
        r = self.s.get(url, headers=h, timeout=self.timeout, **kw)
        log.debug("GET %s -> %s", url, r.status_code)
        return r

    def post(self, url: str, data: dict, referer: str | None = None,
             ajax: bool = False, **kw) -> requests.Response:
        h = self._prepare(url, referer, ajax)
        h.update(kw.pop("headers", {}))
        r = self.s.post(url, data=data, headers=h, timeout=self.timeout, **kw)
        log.debug("POST %s -> %s (%d bytes)", url, r.status_code, len(r.content or b""))
        return r

    # ---------- facebook-specific plumbing ----------

    def datr(self) -> str:
        return self.s.cookies.get("datr", domain=".facebook.com") or self.s.cookies.get("datr", "")

    def c_user(self) -> str:
        return self.s.cookies.get("c_user", "")

    def cookie_jar(self) -> list[dict]:
        return [{"name": c.name, "value": c.value, "domain": c.domain,
                 "path": c.path} for c in self.s.cookies]

    def warmup(self, spend: bool = True) -> bool:
        """Land on the site, look around, take the datr cookie like a visitor."""
        targets = MOBILE_NAV if self.ident.mobile else DESKTOP_NAV
        try:
            r = self.get(random.choice(targets))
            if r.status_code >= 400:
                return False
            if spend:
                time.sleep(random.uniform(1.2, 3.4))
                self.get("https://www.facebook.com/login/", referer="https://www.facebook.com/")
                time.sleep(random.uniform(0.8, 2.1))
            return True
        except requests.RequestException as exc:
            log.warning("warmup failed: %s", exc)
            return False

    def close(self) -> None:
        try:
            self.s.close()
        except Exception:                     # noqa: BLE001
            pass
