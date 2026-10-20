"""Browser backend. The 2026 signup is a React app — there is no <form> to post.

The CAA form (verified against the live page, Oct 2026):

  input[type=text] #0  first name
  input[type=text] #1  surname
  input[type=text] #2  mobile or email
  input[type=password]  password
  div[role=combobox]    day / month / year / gender  (custom pickers)
  div[role=button]      "Submit"

No name attributes, no ids worth using — position and role are the stable handles.
"""
from __future__ import annotations

import logging
import random
import re
import time
from pathlib import Path
from urllib.parse import urlparse, unquote

from . import captcha as cap
from .config import Config
from .identity import DESKTOP_PROFILES, Identity
from .register import RegistrationResult, Status

log = logging.getLogger("fbreg.browser")

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    HAVE_PW = True
except ImportError:                                    # pragma: no cover
    HAVE_PW = False
    PWTimeout = Exception


REG_URLS = ["https://www.facebook.com/reg/", "https://www.facebook.com/r.php"]
MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December"]
OTP_SELECTORS = ['input[autocomplete="one-time-code"]',
                 'input[inputmode="numeric"]',
                 'input[name="code"]',
                 'input[name="confirmation_code"]',
                 'input[aria-label*="code" i]']


def _pw_proxy(url: str | None) -> dict | None:
    """Playwright wants proxy credentials split out, not in the URL."""
    if not url:
        return None
    u = urlparse(url if "://" in url else f"http://{url}")
    d = {"server": f"{u.scheme or 'http'}://{u.hostname}"
                   + (f":{u.port}" if u.port else "")}
    if u.username:
        d["username"] = unquote(u.username)
    if u.password:
        d["password"] = unquote(u.password)
    return d


def _pick_option(page, combo, value: str, exact: bool = True) -> bool:
    """Open a custom combobox and click the option whose text is `value`."""
    try:
        combo.scroll_into_view_if_needed(timeout=4000)
        combo.click(timeout=6000)
    except Exception as exc:                           # noqa: BLE001
        log.debug("combo click: %s", exc)
        return False
    page.wait_for_timeout(700)

    pattern = re.compile(rf"^{re.escape(value)}$") if exact else re.compile(re.escape(value))
    for attempt in range(3):
        try:
            opt = page.get_by_role("option", name=pattern).first
            if opt.count() and opt.is_visible():
                opt.scroll_into_view_if_needed(timeout=3000)
                opt.click(timeout=5000)
                page.wait_for_timeout(350)
                return True
        except Exception as exc:                       # noqa: BLE001
            log.debug("option pick (%s): %s", value, exc)
        page.wait_for_timeout(500)
    # close the popup so the next combobox is reachable
    try:
        page.keyboard.press("Escape")
    except Exception:                                  # noqa: BLE001
        pass
    return False


def _fill_text(page, index: int, value: str) -> bool:
    try:
        box = page.locator('input[type="text"]').nth(index)
        box.wait_for(state="visible", timeout=8000)
        box.click(timeout=4000)
        box.fill("", timeout=4000)
        box.type(value, delay=random.randint(25, 70))
        return box.input_value() == value
    except Exception as exc:                           # noqa: BLE001
        log.debug("text fill #%d: %s", index, exc)
        return False


def _submit(page) -> bool:
    for attempt in (
        lambda: page.get_by_role("button", name="Submit", exact=True).first.click(timeout=8000),
        lambda: page.locator('div[role="button"]', has_text=re.compile(r"^Submit$")).first.click(timeout=8000),
        lambda: page.get_by_text("Submit", exact=True).first.click(timeout=8000),
    ):
        try:
            attempt()
            return True
        except Exception:                              # noqa: BLE001
            continue
    return False


def _visible_otp(page):
    for sel in OTP_SELECTORS:
        loc = page.locator(sel).first
        try:
            if loc.count() and loc.is_visible():
                return loc
        except Exception:                              # noqa: BLE001
            continue
    # the confirmemail.php screen ships one anonymous input[type=text]
    try:
        body = page.content().lower()
        if "confirmation code" in body or "enter the code" in body \
                or "enter the confirmation" in body:
            candidates = page.locator('input[type="text"]:visible')
            if candidates.count() == 1:
                return candidates.first
    except Exception:                                  # noqa: BLE001
        pass
    return None


def _resend_code(page) -> bool:
    for name in (r"didn'?t get the code", r"resend", r"send again", r"new code"):
        try:
            loc = page.get_by_role("button", name=re.compile(name, re.I)).first
            if loc.count() and loc.is_visible():
                loc.click(timeout=5000)
                page.wait_for_timeout(2000)
                return True
        except Exception:                              # noqa: BLE001
            continue
    return False


def _confirm_by_link(page, link: str) -> bool:
    """Open the confirmation link inside the same context, so cookies carry over."""
    try:
        page.goto(link, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2500)
        return True
    except Exception as exc:                           # noqa: BLE001
        log.debug("confirm link: %s", exc)
        return False


def _fill_otp(page, mailbox, timeout: int = 150) -> bool:
    """If FB is asking for a code, pull it from the inbox and type it."""
    loc = _visible_otp(page)
    if loc is None:
        return False
    log.info("verification screen — waiting for the mail")
    value = mailbox.wait_for_code(timeout=timeout)
    if not value:
        log.warning("no mail arrived in %ss", timeout)
        return False
    if value.startswith("http"):
        return _confirm_by_link(page, value)
    try:
        loc.click(timeout=4000)
        loc.fill("", timeout=4000)
        loc.type(value, delay=random.randint(60, 140))
        page.wait_for_timeout(400)
        for attempt in (
            lambda: page.get_by_role("button", name=re.compile(r"continue|confirm|next|submit", re.I)).first.click(timeout=6000),
            lambda: page.keyboard.press("Enter"),
        ):
            try:
                attempt()
                break
            except Exception:                          # noqa: BLE001
                continue
        page.wait_for_timeout(1500)
        return True
    except Exception as exc:                           # noqa: BLE001
        log.debug("otp fill: %s", exc)
        return False


def _settle_confirmation(page, ctx, mailbox, rounds: int = 3) -> str:
    """FB asks for a second code / link after the account row exists. Keep up."""
    for _ in range(rounds):
        try:
            needs = ("confirmemail" in (page.url or "")
                     or _visible_otp(page) is not None)
        except Exception:                              # noqa: BLE001
            needs = False
        if not needs:
            return "confirmed"
        value = mailbox.wait_for_code(timeout=20)
        if not value:
            if _resend_code(page):
                log.info("asked FB to resend")
                value = mailbox.wait_for_code(timeout=120)
            if not value:
                return "no mail"
        if value.startswith("http"):
            _confirm_by_link(page, value)
            continue
        loc = _visible_otp(page)
        if loc is None:
            try:
                page.goto("https://www.facebook.com/confirmemail.php",
                          wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(2000)
            except Exception:                          # noqa: BLE001
                return "no code field"
            loc = _visible_otp(page)
            if loc is None:
                return "no code field"
        try:
            loc.fill("", timeout=4000)
            loc.type(value, delay=random.randint(60, 140))
            page.wait_for_timeout(400)
            page.get_by_role("button", name=re.compile(r"continue|confirm|next|submit", re.I)) \
                .first.click(timeout=6000)
            page.wait_for_timeout(2500)
        except Exception as exc:                       # noqa: BLE001
            log.debug("settle fill: %s", exc)
            return "fill failed"
    try:
        return "confirmed" if "confirmemail" not in (page.url or "") else "still pending"
    except Exception:                                  # noqa: BLE001
        return "unknown"


def _click_continue(page) -> bool:
    attempts = [
        lambda: page.get_by_role("button", name=re.compile(r"^continue$", re.I)).first.click(timeout=6000),
        lambda: page.locator('[role="button"]:has-text("Continue")').first.click(timeout=6000),
        lambda: page.get_by_text("Continue", exact=True).first.click(timeout=6000),
        lambda: page.evaluate("""() => {
            const els = [...document.querySelectorAll('[role=button],button,a,div')];
            const el = els.find(e => (e.innerText || '').trim().toLowerCase() === 'continue'
                                     && e.getBoundingClientRect().width > 0);
            if (el) { el.click(); return true; }
            return false;
        }"""),
    ]
    for fn in attempts:
        try:
            if fn() is not False:
                return True
        except Exception:                              # noqa: BLE001
            continue
    return False


def _clear_checkpoint(page, ctx, cfg: Config, headed: bool, rounds: int = 2) -> str:
    """New accounts land on 'confirm that you're human'. Click through it."""
    for _ in range(rounds):
        if "/checkpoint/" not in (page.url or ""):
            return "cleared"
        log.info("checkpoint: %s", page.url.split("?")[0])
        if not _click_continue(page):
            return "no continue control"
        page.wait_for_timeout(2500)
        deadline = time.time() + 90
        while time.time() < deadline:
            if "/checkpoint/" not in (page.url or ""):
                return "cleared"
            if _has_captcha(page):
                if cfg.solver in ("capsolver", "2captcha", "anticaptcha"):
                    _capsolver_in_page(page, cfg)
                    page.wait_for_timeout(4000)
                    continue
                if cfg.solver == "manual" and headed:
                    log.info("solve the checkpoint challenge in the window")
                    end = time.time() + cfg.captcha_timeout
                    while time.time() < end and "/checkpoint/" in (page.url or ""):
                        page.wait_for_timeout(1500)
                    continue
                return "checkpoint needs captcha"
            page.wait_for_timeout(1200)
    return "cleared" if "/checkpoint/" not in (page.url or "") else "checkpoint stuck"


def _c_user(ctx) -> str:
    try:
        for c in ctx.cookies():
            if c.get("name") == "c_user" and c.get("value"):
                return c["value"]
    except Exception:                                  # noqa: BLE001
        pass
    return ""


def _has_captcha(page) -> bool:
    try:
        for f in page.frames:
            u = f.url or ""
            if "arkose" in u or "funcaptcha" in u:
                return True
        body = page.content().lower()
        return "arkose" in body or "funcaptcha" in body
    except Exception:                                  # noqa: BLE001
        return False


def _capsolver_in_page(page, cfg: Config) -> bool:
    """Solve arkose out-of-band, then hand the token to the page callbacks."""
    try:
        html = page.content()
    except Exception:                                  # noqa: BLE001
        return False
    sitekey = cap.harvest_sitekey(html) or cfg.arkose_sitekey
    blob = cap.harvest_blob(html)
    if not sitekey:
        log.warning("arkose present but no sitekey found")
        return False
    try:
        token = cap.solve(cfg.solver, cfg.solver_key, sitekey, page.url, blob,
                          cfg.captcha_timeout)
    except Exception as exc:                           # noqa: BLE001
        log.warning("captcha solve failed: %s", exc)
        return False

    js = """
    (token) => {
      try {
        if (window.parent && window.parent !== window) {
          window.parent.postMessage(JSON.stringify({
            eventId: 'challenge-complete',
            payload: {sessionToken: token}
          }), '*');
        }
        return true;
      } catch (e) { return false; }
    }
    """
    try:
        for fr in page.frames:
            u = fr.url or ""
            if "arkose" in u or "funcaptcha" in u:
                fr.evaluate(js, token)
    except Exception as exc:                           # noqa: BLE001
        log.debug("token inject: %s", exc)
    return True


def register_browser(cfg: Config, ident: Identity, proxy_url: str | None,
                     headed: bool = False, cookie_dir: str = "out/cookies",
                     state_dir: str | None = None,
                     mailbox=None) -> RegistrationResult:
    res = RegistrationResult(status=Status.ERROR, email=ident.email,
                             password=ident.password, full_name=ident.full_name,
                             proxy=proxy_url or "direct")
    if not HAVE_PW:
        res.note = ("playwright missing: pip install playwright && "
                    "python -m playwright install chromium")
        return res

    with sync_playwright() as pw:
        browser = None
        try:
            # Desktop is the only variant that serves the CAA form; mobile hosts
            # bounce to the Instagram login-via-app flow.
            ua, ua_hints, ua_plat, _ = random.choice(DESKTOP_PROFILES)
            browser = pw.chromium.launch(
                headless=not headed,
                proxy=_pw_proxy(proxy_url),
                args=["--disable-blink-features=AutomationControlled",
                      "--no-first-run", "--no-default-browser-check"],
            )
            ctx = browser.new_context(
                user_agent=ua,
                locale=ident.locale,
                timezone_id=ident.timezone,
                viewport={"width": 1366, "height": 900},
                device_scale_factor=1.0,
                is_mobile=False,
                has_touch=False,
                extra_http_headers={
                    "sec-ch-ua": ua_hints,
                    "sec-ch-ua-mobile": "?0",
                    "sec-ch-ua-platform": f'"{ua_plat}"',
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
            page = ctx.new_page()

            page.goto("https://www.facebook.com/", wait_until="domcontentloaded",
                      timeout=60000)
            page.wait_for_timeout(1200 + (ident.day % 5) * 300)

            for url in REG_URLS:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(1800)
                try:
                    page.locator('input[type="text"]').first.wait_for(
                        state="visible", timeout=15000)
                    break
                except Exception:                      # noqa: BLE001
                    log.info("no form at %s (landed %s)", url, page.url)

            if page.locator('input[type="text"]').count() < 3:
                res.status = Status.BLOCKED
                res.note = f"form not served (url={page.url}, " \
                           f"inputs={page.locator('input').count()})"
                return res

            filled = {
                "first": _fill_text(page, 0, ident.first),
                "last": _fill_text(page, 1, ident.last),
                "email": _fill_text(page, 2, ident.email),
                "pass": False,
            }
            try:
                pw_box = page.locator('input[type="password"]').first
                pw_box.click(timeout=4000)
                pw_box.type(ident.password, delay=random.randint(30, 75))
                filled["pass"] = pw_box.input_value() == ident.password
            except Exception as exc:                   # noqa: BLE001
                log.debug("password fill: %s", exc)

            if not all(filled.values()):
                res.status = Status.BLOCKED
                res.note = f"fields not fillable: {filled} (url={page.url})"
                return res

            combos = page.locator('[role="combobox"]')
            n_combos = combos.count()
            filled["month"] = _pick_option(
                page, page.locator('[role="combobox"][aria-label*="month" i]').first,
                MONTH_NAMES[ident.month - 1]) if n_combos >= 3 else False
            filled["day"] = _pick_option(
                page, page.locator('[role="combobox"][aria-label*="day" i]').first,
                str(ident.day)) if n_combos >= 3 else False
            filled["year"] = _pick_option(
                page, page.locator('[role="combobox"][aria-label*="year" i]').first,
                str(ident.year)) if n_combos >= 3 else False

            if n_combos >= 4:
                gender_combo = page.locator('[role="combobox"]').nth(3)
                filled["gender"] = _pick_option(
                    page, gender_combo, "Female" if ident.sex == 1 else "Male")
            page.wait_for_timeout(400 + (ident.day % 4) * 150)

            if cfg.dry_run:
                shot = Path(cfg.out_dir) / f"dry_{ident.email}.png"
                shot.parent.mkdir(parents=True, exist_ok=True)
                try:
                    page.screenshot(path=str(shot), full_page=True)
                except Exception:                      # noqa: BLE001
                    pass
                res.status = Status.DRY_RUN
                res.note = (f"{sum(filled.values())}/{len(filled)} fields, "
                            f"shot={shot.name}, url={page.url}")
                return res

            if not _submit(page):
                res.status = Status.BLOCKED
                res.note = "no submit control"
                return res

            # ---- after submit ----
            deadline = time.time() + 120
            solved = False
            otp_rounds = 0
            while time.time() < deadline:
                page.wait_for_timeout(1200)
                if _c_user(ctx):
                    break
                if mailbox and otp_rounds < 3:
                    if _fill_otp(page, mailbox):
                        otp_rounds += 1
                        deadline = time.time() + 120
                        continue
                if _has_captcha(page) and not solved:
                    solved = True
                    if cfg.solver in ("capsolver", "2captcha", "anticaptcha"):
                        _capsolver_in_page(page, cfg)
                    elif cfg.solver == "manual" and headed:
                        log.info("solve the challenge in the window — waiting")
                        end = time.time() + cfg.captcha_timeout
                        while time.time() < end and not _c_user(ctx):
                            page.wait_for_timeout(1500)
                    else:
                        break
                if "checkpoint" in (page.url or ""):
                    break
                try:
                    body = page.content().lower()
                except Exception:                      # noqa: BLE001
                    break
                if "confirm your identity" in body or "phone number" in body:
                    break

            uid = _c_user(ctx)
            try:
                cookies = [{"name": c["name"], "value": c["value"],
                            "domain": c["domain"], "path": c["path"]}
                           for c in ctx.cookies()]
            except Exception:                          # noqa: BLE001
                cookies = []

            if uid:
                d = Path(cookie_dir)
                d.mkdir(parents=True, exist_ok=True)
                try:
                    ctx.storage_state(path=str(d / f"{ident.email}.json"))
                except Exception:                      # noqa: BLE001
                    pass
                res.status = Status.SUCCESS
                res.user_id = uid
                res.cookies = cookies
                res.note = "c_user set"
                if "/checkpoint/" in (page.url or ""):
                    state = _clear_checkpoint(page, ctx, cfg, headed)
                    res.note = f"c_user set, checkpoint {state}"
                    if state == "checkpoint needs captcha":
                        res.status = Status.CHALLENGE
                if mailbox and "/checkpoint/" not in (page.url or ""):
                    try:
                        # the code confirms the contact step, not the account: FB
                        # then asks for a second one / a link before clearing
                        state = _settle_confirmation(page, ctx, mailbox)
                        res.note = f"c_user set, email {state}"
                    except Exception as exc:           # noqa: BLE001
                        log.debug("settle: %s", exc)
                        res.note = "c_user set, email unsettled"
                return res

            try:
                body = page.content().lower()
            except Exception:                          # noqa: BLE001
                body = ""
            if _has_captcha(page):
                res.status, res.note = Status.CHALLENGE, "arkose unsolved"
            elif "confirm your identity" in body or "checkpoint" in (page.url or ""):
                res.status, res.note = Status.CHALLENGE, "identity checkpoint"
            elif "phone number" in body:
                res.status, res.note = Status.NEEDS_PHONE, "phone gate"
            elif "already" in body and ("email" in body or "account" in body):
                res.status, res.note = Status.EMAIL_USED, "email already used"
            elif "temporarily" in body or "too many" in body:
                res.status, res.note = Status.RATE_LIMITED, "rate limited"
            else:
                res.status, res.note = Status.BLOCKED, f"no c_user (url={page.url})"
            res.cookies = cookies
            return res
        except PWTimeout as exc:
            res.status = Status.PROXY_DEAD
            res.note = f"timeout: {str(exc).splitlines()[0][:150]}"
            return res
        except Exception as exc:                       # noqa: BLE001
            res.status = Status.ERROR
            res.note = f"{type(exc).__name__}: {str(exc)[:150]}"
            return res
        finally:
            try:
                if browser:
                    browser.close()
            except Exception:                          # noqa: BLE001
                pass
