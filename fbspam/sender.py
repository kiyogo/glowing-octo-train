"""Fan-out engine: many accounts, many targets, one message per pair per round."""
from __future__ import annotations

import json
import random
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from .client import FBClient, Status, expand_spintax
from .cookies import Account

RE_URL = re.compile(r'profile\.php\?id=([0-9]+)|facebook\.com/([A-Za-z0-9._-]+)')


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ----------------------------------------------------------------- targets

def load_targets(path: str) -> list[str]:
    """Numeric ids, usernames, or profile links — all collapse to a bare token."""
    out: list[str] = []
    p = Path(path)
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = RE_URL.search(line)
        token = (m.group(1) or m.group(2)) if m else line
        token = token.split("?")[0].strip("/")
        if token and token not in out:
            out.append(token)
    return out


def load_messages(path: str) -> list[str]:
    p = Path(path)
    msgs = [ln.strip() for ln in p.read_text(encoding="utf-8", errors="ignore").splitlines()
            if ln.strip() and not ln.strip().startswith("#")]
    return msgs or ["hi"]


# ------------------------------------------------------------------- state

class State:
    """Resume ledger: which (account, target) pair already went out."""

    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        self.done: set[str] = set()
        if path.exists():
            try:
                self.done = set(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                self.done = set()
        self.fh = open(path, "a", encoding="utf-8")

    @staticmethod
    def key(a_uid: str, target: str) -> str:
        return f"{a_uid}|{target}"

    def seen(self, a_uid: str, target: str) -> bool:
        with self.lock:
            return self.key(a_uid, target) in self.done

    def mark(self, a_uid: str, target: str) -> None:
        k = self.key(a_uid, target)
        with self.lock:
            if k in self.done:
                return
            self.done.add(k)
            self.fh.write(json.dumps(k) + "\n")
            self.fh.flush()

    def close(self) -> None:
        self.fh.close()


# ------------------------------------------------------------------- stats

@dataclass
class Stats:
    sent: int = 0
    failed: int = 0
    skipped: int = 0
    checkpoint: int = 0
    dead: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def bump(self, attr: str, n: int = 1) -> None:
        with self.lock:
            setattr(self, attr, getattr(self, attr) + n)

    def line(self) -> str:
        return (f"sent={self.sent} failed={self.failed} skipped={self.skipped} "
                f"checkpoint={self.checkpoint} dead={self.dead}")


@dataclass
class Options:
    delay: tuple[float, float] = (35.0, 90.0)
    rounds: int = 1
    per_account: int = 0          # 0 = no cap
    workers: int = 4
    dry_run: bool = False
    stop_on_checkpoint: bool = False
    randomize: bool = True


# ---------------------------------------------------------------- the engine

class Sender:
    def __init__(self, accounts: list[Account], targets: list[str],
                 messages: list[str], opts: Options, state: State,
                 stop_event: threading.Event | None = None):
        self.accounts = [a for a in accounts if a.alive()]
        self.targets = targets
        self.messages = messages
        self.opts = opts
        self.state = state
        self.stats = Stats()
        self.stop = stop_event or threading.Event()
        self.lock = threading.Lock()

    def _pick_message(self) -> str:
        return expand_spintax(random.choice(self.messages))

    def _rip(self, target: str) -> str:
        return target

    def _plan(self, acc: Account) -> None:
        targets = list(self.targets)
        if self.opts.randomize:
            random.shuffle(targets)
        n = 0
        for _ in range(self.opts.rounds):
            for tgt in targets:
                if self.state.seen(acc.uid, tgt):
                    continue
                if self.opts.per_account and n >= self.opts.per_account:
                    self.stats.bump("sent", n)
                    return
                print(f"~  {acc} -> {tgt}: {self._pick_message()!r}")
                n += 1
        self.stats.bump("sent", n)

    def _run_account(self, acc: Account) -> None:
        if self.stop.is_set():
            return
        if self.opts.dry_run:
            self._plan(acc)
            return
        cli = FBClient(acc)
        st = cli.boot()
        if st is not Status.OK and st is not Status.RATE:
            self.stats.bump("dead")
            log(f"x  {acc} boot={st.value} {cli.detail}")
            cli.close()
            return
        log(f"+  {acc} up")

        targets = list(self.targets)
        if self.opts.randomize:
            random.shuffle(targets)

        sent_here = 0
        for rnd in range(self.opts.rounds):
            for tgt in targets:
                if self.stop.is_set():
                    cli.close()
                    return
                if self.opts.per_account and sent_here >= self.opts.per_account:
                    log(f"-  {acc} hit per-account cap ({self.opts.per_account})")
                    cli.close()
                    return
                uid = tgt
                if not tgt.isdigit():
                    uid = cli.resolve_username(tgt)
                    if not uid:
                        self.stats.bump("failed")
                        log(f"x  {acc} -> {tgt}: unresolved")
                        continue
                if self.state.seen(acc.uid, uid):
                    self.stats.bump("skipped")
                    continue

                body = self._pick_message()
                if self.opts.dry_run:
                    log(f"~  {acc} -> {uid}: {body!r}")
                    self.state.mark(acc.uid, uid)
                    self.stats.bump("sent")
                    sent_here += 1
                    continue

                res = cli.send(uid, body)
                if res.status is Status.OK:
                    self.stats.bump("sent")
                    self.state.mark(acc.uid, uid)
                    sent_here += 1
                    log(f"-> {acc} -> {uid} ok")
                elif res.status is Status.RATE:
                    self.stats.bump("failed")
                    log(f"!  {acc} rate limited, sleeping 5m")
                    if self.stop.wait(300):
                        cli.close()
                        return
                elif res.status is Status.CHECKPOINT:
                    self.stats.bump("checkpoint")
                    acc.dead = True
                    log(f"!  {acc} checkpoint -> parked")
                    if self.opts.stop_on_checkpoint:
                        self.stop.set()
                    cli.close()
                    return
                elif res.status is Status.DEAD:
                    self.stats.bump("dead")
                    acc.dead = True
                    log(f"!  {acc} session dead")
                    cli.close()
                    return
                else:
                    self.stats.bump("failed")
                    log(f"x  {acc} -> {uid}: {res.status.value} {res.detail}")

                time.sleep(random.uniform(*self.opts.delay))
        cli.close()

    def run(self) -> Stats:
        from concurrent.futures import ThreadPoolExecutor, wait
        log(f"accounts={len(self.accounts)} targets={len(self.targets)} "
            f"rounds={self.opts.rounds} dry={self.opts.dry_run}")

        pool = ThreadPoolExecutor(max_workers=max(1, self.opts.workers))
        futures = []
        try:
            for acc in self.accounts:
                if self.stop.is_set():
                    break
                futures.append(pool.submit(self._run_account, acc))
                time.sleep(random.uniform(0.3, 1.2))
            pending = set(futures)
            while pending:
                done, pending = wait(pending, timeout=5)
                if done:
                    log("  " + self.stats.line())
        except KeyboardInterrupt:
            log("ctrl-c — draining, state is saved")
            self.stop.set()
        finally:
            pool.shutdown(wait=True)
        log("done " + self.stats.line())
        return self.stats
