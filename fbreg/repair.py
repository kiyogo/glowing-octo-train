"""Finish the email confirmation on an account that was created but not confirmed.

    python -m fbreg.repair --state out/cookies/x.json --mailbox out/cookies/x.mailbox.json

Both files are written by the normal run, so this always works on something the
tool itself produced.
"""
from __future__ import annotations

import argparse
import json
import logging
import random
import re
import sys
from pathlib import Path

from . import tempmail
from .browser import (_resend_code, _visible_otp, HAVE_PW, _confirm_by_link)
from .identity import DESKTOP_PROFILES

log = logging.getLogger("fbreg.repair")


def repair(state_file: str, mailbox_file: str, headed: bool = False,
           timeout: int = 120, solver: str = "none", solver_key: str = "") -> str:
    if not HAVE_PW:
        return "playwright missing"
    from playwright.sync_api import sync_playwright

    from .config import Config
    from .browser import _clear_checkpoint

    state = json.loads(Path(state_file).read_text(encoding="utf-8"))
    mb_data = json.loads(Path(mailbox_file).read_text(encoding="utf-8"))
    mailbox = tempmail.Mailbox(mb_data["email"], mb_data["token"])
    cfg = Config.from_env()
    cfg.solver = solver or cfg.solver
    cfg.solver_key = solver_key or cfg.solver_key

    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=not headed)
        ctx = b.new_context(storage_state=state, locale="en-US",
                            viewport={"width": 1366, "height": 900})
        page = ctx.new_page()
        page.goto("https://www.facebook.com/", wait_until="domcontentloaded",
                  timeout=60000)
        page.wait_for_timeout(3000)
        log.info("landed: %s", page.url)

        if "/checkpoint/" in (page.url or ""):
            outcome = _clear_checkpoint(page, ctx, cfg, headed)
            log.info("checkpoint: %s", outcome)
            if outcome != "cleared":
                page.goto("https://www.facebook.com/", wait_until="domcontentloaded",
                          timeout=60000)
                page.wait_for_timeout(2500)
                if "/checkpoint/" in (page.url or ""):
                    b.close()
                    return f"checkpoint — {outcome}"

        if "confirmemail" not in (page.url or "") and _visible_otp(page) is None:
            b.close()
            return "already confirmed"

        loc = _visible_otp(page)

        # a code that already exists in the inbox is stale — only fresh mail counts
        for d in mailbox.messages():
            mid = str(d.get("_id") or d.get("id") or "")
            if mid:
                mailbox._seen.add(mid)

        value = mailbox.wait_for_code(timeout=15)
        if not value:
            if _resend_code(page):
                log.info("resend requested")
                value = mailbox.wait_for_code(timeout=timeout)
        if not value:
            b.close()
            return "no new code"

        if value.startswith("http"):
            _confirm_by_link(page, value)
        else:
            if loc is None:
                page.goto("https://www.facebook.com/confirmemail.php",
                          wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(2000)
                loc = _visible_otp(page)
            if loc is None:
                b.close()
                return "no code field"
            loc.fill("", timeout=4000)
            loc.type(value, delay=random.randint(60, 140))
            page.wait_for_timeout(400)
            page.get_by_role("button", name=re.compile(r"continue|confirm", re.I)) \
                .first.click(timeout=6000)
            page.wait_for_timeout(3000)

        page.goto("https://www.facebook.com/", wait_until="domcontentloaded",
                  timeout=60000)
        page.wait_for_timeout(3000)
        ok = "confirmemail" not in (page.url or "")
        try:
            ctx.storage_state(path=state_file)
        except Exception:                              # noqa: BLE001
            pass
        b.close()
        return "confirmed" if ok else "still pending"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser("fbreg.repair")
    ap.add_argument("--state", required=True)
    ap.add_argument("--mailbox", required=True)
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--solver", default="none",
                    choices=["none", "capsolver", "2captcha", "anticaptcha", "manual"])
    ap.add_argument("--solver-key", default="")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")
    print(repair(a.state, a.mailbox, a.headed, solver=a.solver,
                 solver_key=a.solver_key))
    return 0


if __name__ == "__main__":
    sys.exit(main())
