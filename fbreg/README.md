# fbreg

Facebook account creation over a rotating proxy pool. One identity per attempt, one
proxy per identity, coherent fingerprint, honest classification of what came back.

**Two backends.** `browser` (default) drives the real 2026 signup — a React app with
no `<form>` at all. `requests` is the legacy plain-HTML path, kept for the odd
bucket that still serves one.

## One file, double-click

`TAO-ACC.cmd` in the repo root runs the whole thing: dependency check, Chromium
check, proxy validation, the run, then the confirmation/checkpoint pass, then a
summary. Edit the block at the top, save, double-click.

```bat
set "COUNT=5"                 how many accounts
set "WORKERS=1"               parallel attempts
set "USE_TEMPMAIL=1"          1 = temp-mail.org per account
set "EMAIL_DOMAIN=mail.mydomain.tld"   only when USE_TEMPMAIL=0
set "SOLVER=none"             none, capsolver, 2captcha, anticaptcha, manual
set "SOLVER_KEY="             solver api key
set "HEADED=1"                1 = show the browser
set "ALLOW_DIRECT=1"          1 = run without proxies
set "DELAY=20,55"             seconds between attempts
set "REPAIR=1"                finish confirmation / clear checkpoints
set "DRYRUN=0"                1 = fill the form but never submit
```

Behaviour worth knowing:

- `HEADED=1` with `SOLVER=none` auto-falls back to manual, so a solver key is not
  required to get a working (if babysat) run.
- `SOLVER=capsolver` with an empty key falls back to manual with a warning.
- Each run writes a timestamped folder: `out\run_YYYYMMDD_HHMMSS\`.
- The repair pass walks `cookies\*.mailbox.json` and finishes every account.
- `DRYRUN=1` is the safe way to prove the pipeline after editing settings.

## Install

```bash
cd fbreg
pip install -r requirements.txt
python -m playwright install chromium
```

## Run

```bash
# sanity pass: check pool, print latency + exit IP
python -m fbreg --check-proxies

# dry run: proxy warmup, open /reg, fill every field, screenshot, never submit
python -m fbreg -n 1 --dry-run -d mail.yourdomain.tld

# real run: 20 accounts, 4 at a time, catch-all mail domain
python -m fbreg -n 20 -w 4 -d mail.yourdomain.tld --proxy-file proxies.txt

# with captcha solving
python -m fbreg -n 5 -w 2 -d mail.yourdomain.tld --solver capsolver --solver-key KEY

# watch it work / solve by hand
python -m fbreg -n 1 -d mail.yourdomain.tld --headed --solver manual

# disposable inbox per identity — the code / confirm link is read and typed for you
python -m fbreg -n 5 -w 2 --tempmail --solver capsolver --solver-key KEY
```

Output lands in `out/`:

| file | contents |
|---|---|
| `accounts.jsonl` | only successes — cookies, uid, proxy, password |
| `accounts.txt` | `email<TAB>password<TAB>name<TAB>uid<TAB>proxy` |
| `attempts.log` | every attempt with its verdict |
| `cookies/<email>.json` | Playwright storage state, ready to reload |
| `dry_<email>.png` | dry-run screenshot of the filled form |

## What the browser backend does per attempt

1. **Proxy bind** — Chromium launches with the proxy baked into the context, so
   DNS, TLS and WebRTC all leave through it.
2. **Desktop context** — the form is the CAA desktop variant. Mobile hosts bounce
   to the Instagram `login_via/app` flow, so the UA is forced to desktop Chrome
   with matching `sec-ch-ua` hints.
3. **Warm the session** — land on `facebook.com`, linger, then `/reg/` (falls back
   to `/r.php` if `/reg` doesn't render inputs).
4. **Fill by role and position** — the form has no usable `name` attributes:
   - `input[type=text]` #0 → first name, #1 → surname, #2 → mobile or email
   - `input[type=password]` → password
   - `[role=combobox]` → day, month, year, gender (custom pickers, options are
     `[role=option]`, matched on exact text)
   - `div[role=button]` with text `Submit`
5. **Submit, then wait** — success is a `c_user` cookie *and* a session that
   survives. Everything else is labelled: `challenge`, `needs_phone`,
   `email_used`, `rate_limited`, `proxy_dead`, `blocked`.
6. **Captcha** — arkose iframe detected → solver token posted back into the frame
   via `challenge-complete`; or, with `--headed --solver manual`, it waits for you
   to solve it in the window.

## The three gates you cannot code around

- **Arkose (FunCaptcha).** Every registration hits it. No solver, no account.
  The live page hands out the sitekey (`E715CBC2-…` at time of writing) and the
  encrypted blob — both are harvested, never hardcoded.
- **Phone gate.** A share of registrations demand SMS after the email step, and
  the number must be unused. Shows up as `needs_phone`.
- **Reputation.** Residential/mobile ASNs clear in a few tries; datacenter ASNs
  get `rate_limited` almost immediately. That's what `--check-proxies` is for.

## Disposable inboxes (`--tempmail`)

With `--tempmail`, each identity gets its own temp-mail.org inbox instead of a
catch-all domain:

```
POST https://web2.temp-mail.org/mailbox   -> {"token": "...", "mailbox": "x@y"}
GET  https://web2.temp-mail.org/messages  -> {"mailbox": "x@y", "messages": [...]}
GET  https://web2.temp-mail.org/messages/<id>  -> text + html
```

The address is filled into the form, and after Submit the flow watches for a
verification screen:

- a code field (`input[autocomplete=one-time-code]`, `inputmode=numeric`,
  `input[name=code]`, …) → the inbox is polled, the 5–8 digit code is extracted
  and typed, submit pressed;
- a confirmation link → opened **inside the same browser context**, so the
  cookie is set on the session that created the account.

After the account row exists, `confirmemail.php` still asks for a code on an
anonymous `input[type=text]` (no name, no `inputmode`, no `autocomplete`). The
tool matches it by page text + "exactly one visible text input", asks FB to
resend via **"I didn't get the code"**, and types the fresh code. A stale code is
never retried — that is what pushes an account into a checkpoint.

`--tempmail` and `-d` are mutually exclusive in practice; `--tempmail` wins.

## The new-account checkpoint

Freshly created accounts land on `/checkpoint/<id>/`:

```
"<Name>, confirm that you're human to use your profile"
Continue   ·   Takes about 30 seconds
```

The flow handles it: click Continue (four fallback strategies — the control is
sometimes a `div[role=button]`, sometimes a bare `<a>`), then clear whatever
arkose appears. Without a solver this reports `checkpoint needs captcha`; with
`--headed --solver manual` it waits for you to solve it in the window.

This is a **second** captcha per account, separate from the signup one.

## Repairing an unconfirmed account

Every run writes `cookies/<email>.json` (storage state) and
`cookies/<email>.mailbox.json` (inbox token). Feed both back in:

```bash
python -m fbreg.repair --state out/cookies/x.json --mailbox out/cookies/x.mailbox.json
python -m fbreg.repair --state out/cookies/x.json --mailbox out/cookies/x.mailbox.json \
    --headed --solver manual
```

Returns `confirmed`, `already confirmed`, `checkpoint — checkpoint needs captcha`,
`no new code`, or `still pending`. The state file is rewritten on success.

## Tuning

- `-w` should not exceed live proxies ÷ 3.
- `--delay 20,55` is the default floor before the classifier treats the run as
  automation.
- The email domain must actually receive mail — a dangling domain gets flagged in
  the form itself ("it looks like you may have entered an incorrect email").
- `FB_*` env vars override everything (see `config.py`).

## Layout

```
fbreg/
  config.py     runtime knobs, env override
  proxy.py      parse / health-check / rotate / cooldown
  identity.py   names, mail, password, birthday, UA + client-hint sets
  browser.py    Playwright backend — the one that actually works today
  client.py     requests backend: headers, retries, warmup
  form.py       hidden-field / LSD / jazoest / dtsg harvesting (requests path)
  captcha.py    capsolver, 2captcha, anticaptcha, manual
  register.py   requests flow and its verdicts
  tempmail.py   temp-mail.org inbox: create, poll, extract code / link
  repair.py     finish the email confirmation on a created account
  verify.py     IMAP catch-all polling for the confirmation mail
  main.py       CLI, worker pool, output sinks
```
