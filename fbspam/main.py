"""fbspam — cookie-driven messenger fan-out.

    python -m fbspam dump   --from-browsers
    python -m fbspam check  -a accounts.jsonl
    python -m fbspam run    -a accounts.jsonl -t targets.txt -m messages.txt
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import threading
import time
from pathlib import Path

from .client import FBClient
from .cookies import Account, extract_browsers, load_accounts
from .sender import Options, Sender, State, load_messages, load_targets, log


# ----------------------------------------------------------------- helpers

def write_playwright(path: Path, accounts: list[Account]) -> None:
    """Dump in the same shape fbreg/Playwright already use, one file each."""
    path.mkdir(parents=True, exist_ok=True)
    for acc in accounts:
        blob = {
            "cookies": [
                {"name": k, "value": v, "domain": ".facebook.com", "path": "/",
                 "secure": True} for k, v in acc.cookies.items()
            ],
            "proxy": acc.proxy or "direct",
            "note": acc.note,
        }
        (path / f"{acc.name}.json").write_text(json.dumps(blob, indent=2), encoding="utf-8")
    log(f"wrote {len(accounts)} cookie files -> {path}")


def collect(args) -> list[Account]:
    accounts = load_accounts(args.accounts or [], from_browsers=args.from_browsers,
                             browsers=args.browsers)
    if args.proxy:
        pool = [ln.strip() for ln in Path(args.proxy).read_text(encoding="utf-8").splitlines()
                if ln.strip() and not ln.strip().startswith("#")] or [None]
        if not args.keep_proxy:
            for acc in accounts:
                acc.proxy = pool[(accounts.index(acc)) % len(pool)] if pool else None
    return accounts


# ------------------------------------------------------------------ commands

def cmd_dump(args) -> int:
    accounts = extract_browsers(args.browsers) if args.from_browsers else \
        load_accounts(args.accounts or [])
    if not accounts:
        log("nothing found — no live FB session in those stores")
        return 1
    for acc in accounts:
        log(f"  {acc.name:<28} uid={acc.uid:<18} cookies={len(acc.cookies)}")
    if args.out:
        write_playwright(Path(args.out), accounts)
    return 0


def cmd_check(args) -> int:
    accounts = collect(args)
    if not accounts:
        log("no accounts loaded")
        return 1
    live = 0
    for acc in accounts:
        cli = FBClient(acc, proxy=acc.proxy)
        ok = cli.ping()
        log(("+" if ok else "x") + f"  {acc}  {cli.detail or ('live' if ok else 'dead')}")
        live += ok
        cli.close()
        time.sleep(random.uniform(1.0, 2.5))
    log(f"live {live}/{len(accounts)}")
    return 0 if live else 1


def cmd_run(args) -> int:
    accounts = collect(args)
    if not accounts:
        log("no accounts loaded — run `dump --from-browsers` first")
        return 1
    targets = load_targets(args.targets)
    if not targets:
        log("no targets")
        return 1
    messages = load_messages(args.messages)

    opts = Options(
        delay=(args.delay_min, args.delay_max),
        rounds=args.rounds,
        per_account=args.per_account,
        workers=args.workers,
        dry_run=args.dry_run,
        stop_on_checkpoint=args.stop_on_checkpoint,
        randomize=not args.no_shuffle,
    )
    state = State(Path(args.state))
    sender = Sender(accounts, targets, messages, opts, state)
    try:
        sender.run()
    finally:
        state.close()

    Path("stats.json").write_text(json.dumps({
        "sent": sender.stats.sent, "failed": sender.stats.failed,
        "skipped": sender.stats.skipped, "checkpoint": sender.stats.checkpoint,
        "dead": sender.stats.dead, "when": time.time(),
    }, indent=2), encoding="utf-8")
    return 0


# --------------------------------------------------------------------- cli

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="fbspam", description="cookie-driven messenger fan-out")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("-a", "--accounts", nargs="*", default=[],
                        help="cookie json / accounts.jsonl / dir / txt")
        sp.add_argument("--from-browsers", action="store_true", help="pull live sessions from local browsers")
        sp.add_argument("--browsers", nargs="*", default=None,
                        help="chrome edge brave opera vivaldi firefox")
        sp.add_argument("--proxy", help="proxy list file; assigned round-robin")
        sp.add_argument("--keep-proxy", action="store_true", help="respect proxies stored per account")

    d = sub.add_parser("dump", help="extract cookies and list accounts")
    common(d)
    d.add_argument("-o", "--out", help="write one cookie json per account into this dir")
    d.set_defaults(func=cmd_dump)

    c = sub.add_parser("check", help="ping every account")
    common(c)
    c.set_defaults(func=cmd_check)

    r = sub.add_parser("run", help="send messages")
    common(r)
    r.add_argument("-t", "--targets", required=True, help="file with uids / usernames / links")
    r.add_argument("-m", "--messages", required=True, help="one message per line, spintax ok")
    r.add_argument("--rounds", type=int, default=1)
    r.add_argument("--per-account", type=int, default=0, help="cap sends per account (0 = no cap)")
    r.add_argument("--workers", type=int, default=4)
    r.add_argument("--delay-min", type=float, default=35.0)
    r.add_argument("--delay-max", type=float, default=90.0)
    r.add_argument("--state", default="state.jsonl", help="resume ledger")
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--stop-on-checkpoint", action="store_true")
    r.add_argument("--no-shuffle", action="store_true")
    r.set_defaults(func=cmd_run)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
