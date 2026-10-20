"""CLI: build N accounts across a proxy pool, one identity per attempt."""
from __future__ import annotations

import argparse
import json
import logging
import queue
import random
import sys
import threading
import time
from pathlib import Path

from . import browser
from . import proxy as proxymod
from . import register as reg
from . import tempmail
from .client import FBSession
from .config import Config
from .identity import make_identity

log = logging.getLogger("fbreg")


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)-16s %(message)s",
        datefmt="%H:%M:%S",
    )


class Output:
    """Append-only sinks: JSONL for machines, TSV for eyeballs."""

    def __init__(self, out_dir: str):
        d = Path(out_dir)
        d.mkdir(parents=True, exist_ok=True)
        self.jsonl = d / "accounts.jsonl"
        self.txt = d / "accounts.txt"
        self.log = d / "attempts.log"
        self.lock = threading.Lock()

    def good(self, r: reg.RegistrationResult) -> None:
        with self.lock:
            with self.jsonl.open("a", encoding="utf-8") as f:
                f.write(json.dumps(r.as_dict(), ensure_ascii=False) + "\n")
            with self.txt.open("a", encoding="utf-8") as f:
                f.write(f"{r.email}\t{r.password}\t{r.full_name}\t{r.user_id}\t{r.proxy}\n")

    def all(self, r: reg.RegistrationResult) -> None:
        with self.lock:
            with self.log.open("a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\t{r.status.value}\t"
                        f"{r.email}\t{r.proxy}\t{r.note}\n")


def worker(idx: int, jobs: queue.Queue, pool: proxymod.ProxyPool, cfg: Config,
           out: Output) -> None:
    while True:
        try:
            _ = jobs.get_nowait()
        except queue.Empty:
            return
        try:
            p = pool.get()
            if p is None and cfg.require_proxy:
                log.error("[w%d] no live proxy, standing down", idx)
                jobs.task_done()
                return

            ident = make_identity(cfg.email_domain, cfg.age_min, cfg.age_max,
                                 prefix_len=cfg.email_prefix_len)
            mailbox = None
            if cfg.mail_provider == "tempmail":
                try:
                    mailbox = tempmail.Mailbox.create()
                    ident.email = mailbox.email
                    Path(f"{cfg.out_dir}/cookies").mkdir(parents=True, exist_ok=True)
                    Path(f"{cfg.out_dir}/cookies/{mailbox.email}.mailbox.json").write_text(
                        json.dumps({"email": mailbox.email, "token": mailbox.token}),
                        encoding="utf-8")
                except Exception as exc:                       # noqa: BLE001
                    log.error("[w%d] temp-mail unavailable: %s", idx, exc)
                    mailbox = None
            log.info("[w%d] %s %s via %s", idx, ident.email, ident.full_name,
                     p.url if p else "direct")
            try:
                if cfg.mode == "browser":
                    res = browser.register_browser(
                        cfg, ident, p.url if p else None,
                        headed=cfg.headed, cookie_dir=f"{cfg.out_dir}/cookies",
                        mailbox=mailbox)
                else:
                    sess = FBSession(ident, p, cfg.request_timeout, cfg.max_retries)
                    try:
                        res = reg.register(cfg, ident, sess)
                    finally:
                        sess.close()
            except Exception as exc:                       # noqa: BLE001
                res = reg.RegistrationResult(
                    status=reg.Status.ERROR, email=ident.email,
                    password=ident.password, full_name=ident.full_name,
                    proxy=p.url if p else "direct",
                    note=f"{type(exc).__name__}: {exc}")

            out.all(res)
            if res.status == reg.Status.SUCCESS:
                out.good(res)
                log.info("[w%d] GOOD %s uid=%s", idx, res.email, res.user_id)
            else:
                log.warning("[w%d] %s %s (%s)", idx, res.status.value,
                            res.email, res.note)
                if p and res.status in (reg.Status.PROXY_DEAD, reg.Status.BLOCKED,
                                        reg.Status.RATE_LIMITED):
                    pool.penalise(p, hard=res.status == reg.Status.PROXY_DEAD)
        finally:
            jobs.task_done()
            if cfg.delay_max > 0:
                time.sleep(random.uniform(cfg.delay_min, cfg.delay_max))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser("fbreg", description="facebook account creator")
    ap.add_argument("-n", "--count", type=int, default=1)
    ap.add_argument("-w", "--workers", type=int, default=1)
    ap.add_argument("-p", "--proxy-file", default="proxies.txt")
    ap.add_argument("-d", "--domain", default="", help="catch-all email domain")
    ap.add_argument("--tempmail", action="store_true",
                    help="use temp-mail.org per identity and auto-read the "
                         "verification code / link")
    ap.add_argument("--solver", default="none",
                    choices=["none", "capsolver", "2captcha", "anticaptcha", "manual"])
    ap.add_argument("--solver-key", default="")
    ap.add_argument("--arkose-sitekey", default="")
    ap.add_argument("--dry-run", action="store_true",
                    help="fill the form + fingerprint + proxy, never submit")
    ap.add_argument("--mode", default="browser", choices=["browser", "requests"],
                    help="browser drives the real React form (default); "
                         "requests is the legacy <form> path")
    ap.add_argument("--headed", action="store_true",
                    help="show the browser window (required for --solver manual)")
    ap.add_argument("--check-proxies", action="store_true",
                    help="health-check the pool, print it, exit")
    ap.add_argument("--direct", action="store_true", help="allow running without proxies")
    ap.add_argument("--out", default="out")
    ap.add_argument("--delay", default="20,55", help="min,max seconds between attempts")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)

    cfg = Config.from_env()
    cfg.count = a.count
    cfg.workers = a.workers
    cfg.proxy_file = a.proxy_file
    cfg.email_domain = a.domain or cfg.email_domain
    if a.tempmail:
        cfg.mail_provider = "tempmail"
    cfg.solver = a.solver if a.solver != "none" else cfg.solver
    cfg.solver_key = a.solver_key or cfg.solver_key
    cfg.arkose_sitekey = a.arkose_sitekey or cfg.arkose_sitekey
    cfg.mode = a.mode
    cfg.headed = a.headed or cfg.headed
    cfg.dry_run = cfg.dry_run or a.dry_run
    cfg.out_dir = a.out
    cfg.require_proxy = not a.direct
    if a.delay:
        lo, _, hi = a.delay.partition(",")
        cfg.delay_min = float(lo or 0)
        cfg.delay_max = float(hi or lo or 0)
    setup_logging("DEBUG" if a.verbose else cfg.log_level)

    urls = proxymod.load_proxies(cfg.proxy_file)
    pool = proxymod.ProxyPool(urls, cfg.proxy_timeout, cfg.proxy_check_url,
                              cfg.proxy_cooldown)
    if pool.items:
        pool.check_all()
        if a.check_proxies:
            print(pool.report())
            return 0
    elif cfg.require_proxy:
        log.error("no proxies loaded from %s — use --direct to run without", cfg.proxy_file)
        return 2
    if a.check_proxies:
        print(pool.report())
        return 0

    out = Output(cfg.out_dir)
    jobs: queue.Queue = queue.Queue()
    for i in range(cfg.count):
        jobs.put(i)

    threads = [threading.Thread(target=worker, name=f"w{i}",
                                args=(i, jobs, pool, cfg, out), daemon=True)
               for i in range(max(1, min(cfg.workers, cfg.count)))]
    for t in threads:
        t.start()
    try:
        for t in threads:
            t.join()
    except KeyboardInterrupt:
        log.warning("interrupted — finishing in-flight attempts")
        return 130

    good = 0
    if out.txt.exists():
        good = sum(1 for _ in out.txt.open(encoding="utf-8"))
    log.info("done. accounts on file: %d", good)
    return 0


if __name__ == "__main__":
    sys.exit(main())
