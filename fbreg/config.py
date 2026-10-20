"""Runtime configuration. Everything overridable by env var."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


@dataclass
class Config:
    # ---- throughput ----
    count: int = 1                 # how many accounts to attempt
    workers: int = 1               # concurrent attempts (= proxies per slot)
    delay_min: float = 20.0        # jitter between attempts, per worker
    delay_max: float = 55.0

    # ---- proxies ----
    proxy_file: str = "proxies.txt"
    proxy_check_url: str = "https://api.ipify.org?format=json"
    proxy_timeout: int = 15
    proxy_cooldown: int = 600      # seconds a dead/blocked proxy sits out
    require_proxy: bool = True     # refuse to run direct

    # ---- identity ----
    email_domain: str = ""         # e.g. "mail.mydomain.tld" (catch-all)
    email_prefix_len: int = 12
    mail_provider: str = "none"    # none | tempmail
    mail_poll_timeout: int = 180
    imap_host: str = ""
    imap_port: int = 993
    imap_user: str = ""
    imap_pass: str = ""
    age_min: int = 18
    age_max: int = 42

    # ---- captcha (Arkose Labs / FunCaptcha) ----
    solver: str = "none"           # none | capsolver | 2captcha | anticaptcha | manual
    solver_key: str = ""
    captcha_timeout: int = 180
    arkose_sitekey: str = ""       # auto-harvested from challenge page if empty

    # ---- behaviour ----
    mode: str = "browser"          # browser | requests
    headed: bool = False           # show the window (needed for manual captcha)
    verify_email: bool = True
    dry_run: bool = False          # build + fingerprint + proxy check, never submit
    out_dir: str = "out"
    log_level: str = "INFO"

    # ---- network shape ----
    request_timeout: int = 30
    max_retries: int = 3
    warmup: bool = True            # hit facebook.com first for a datr cookie

    extra_headers: dict = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "Config":
        c = cls()
        c.count = _env_int("FB_COUNT", c.count)
        c.workers = _env_int("FB_WORKERS", c.workers)
        c.delay_min = _env_float("FB_DELAY_MIN", c.delay_min)
        c.delay_max = _env_float("FB_DELAY_MAX", c.delay_max)
        c.proxy_file = _env("FB_PROXY_FILE", c.proxy_file)
        c.proxy_timeout = _env_int("FB_PROXY_TIMEOUT", c.proxy_timeout)
        c.require_proxy = _env("FB_REQUIRE_PROXY", "1") not in ("0", "false", "no")
        c.email_domain = _env("FB_EMAIL_DOMAIN", c.email_domain)
        c.mail_provider = _env("FB_MAIL_PROVIDER", c.mail_provider)
        c.imap_host = _env("FB_IMAP_HOST", c.imap_host)
        c.imap_port = _env_int("FB_IMAP_PORT", c.imap_port)
        c.imap_user = _env("FB_IMAP_USER", c.imap_user)
        c.imap_pass = _env("FB_IMAP_PASS", c.imap_pass)
        c.solver = _env("FB_SOLVER", c.solver)
        c.solver_key = _env("FB_SOLVER_KEY", c.solver_key)
        c.arkose_sitekey = _env("FB_ARKOSE_SITEKEY", c.arkose_sitekey)
        c.mode = _env("FB_MODE", c.mode)
        c.headed = _env("FB_HEADED", "0") not in ("0", "false", "no")
        c.verify_email = _env("FB_VERIFY_EMAIL", "1") not in ("0", "false", "no")
        c.dry_run = _env("FB_DRY_RUN", "0") not in ("0", "false", "no")
        c.out_dir = _env("FB_OUT_DIR", c.out_dir)
        c.request_timeout = _env_int("FB_TIMEOUT", c.request_timeout)
        c.log_level = _env("FB_LOG_LEVEL", c.log_level)
        return c
