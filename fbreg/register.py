"""The registration flow itself. One shot per identity, classified honestly."""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum

import requests

from . import captcha as cap
from . import form
from .client import FBSession
from .config import Config
from .identity import Identity

log = logging.getLogger("fbreg.register")


class Status(str, Enum):
    SUCCESS = "success"
    CHALLENGE = "challenge"          # arkose / photo check in the way
    NEEDS_PHONE = "needs_phone"      # hard phone gate
    EMAIL_USED = "email_used"
    NAME_REJECTED = "name_rejected"
    RATE_LIMITED = "rate_limited"
    PROXY_DEAD = "proxy_dead"
    BLOCKED = "blocked"
    DRY_RUN = "dry_run"
    ERROR = "error"


@dataclass
class RegistrationResult:
    status: Status
    email: str = ""
    password: str = ""
    full_name: str = ""
    user_id: str = ""
    cookies: list = field(default_factory=list)
    proxy: str = ""
    note: str = ""
    attempts: int = 1

    def as_dict(self) -> dict:
        return {
            "status": self.status.value, "email": self.email,
            "password": self.password, "full_name": self.full_name,
            "user_id": self.user_id, "cookies": self.cookies,
            "proxy": self.proxy, "note": self.note,
        }


REG_URLS = {
    True: ["https://m.facebook.com/reg/", "https://mbasic.facebook.com/reg/"],
    False: ["https://www.facebook.com/reg/", "https://m.facebook.com/reg/"],
}
SUBMIT = {
    True: "https://m.facebook.com/reg/submit/",
    False: "https://www.facebook.com/reg/submit/",
}

PHONE_HINTS = ("phone number", "add a mobile", "enter your mobile",
               "confirm with your phone")
CHECKPOINT_HINTS = ("checkpoint", "confirm your identity", "we need to verify",
                    "security check", "suspicious activity", "help us confirm")
RATE_HINTS = ("temporarily blocked", "try again later", "too many attempts",
              "you're temporarily", "we limit how often")
EMAIL_HINTS = ("already in use", "is invalid", "not a valid email",
               "please enter a valid email")
NAME_HINTS = ("please enter a name", "names can't", "that name isn't allowed",
              "enter your full name")


def build_payload(html: str, ident: Identity) -> tuple[dict, dict]:
    """Harvested tokens + identity fields. Returns (payload, tokens)."""
    fields = form.parse_fields(html)
    lsd = form.find_lsd(html) or fields.get("lsd", "")
    tokens = {
        "lsd": lsd,
        "jazoest": fields.get("jazoest") or form.jazoest_from(lsd),
        "fb_dtsg": form.find_dtsg(html) or fields.get("fb_dtsg", ""),
        "reg_instance": fields.get("reg_instance") or form.find_reg_instance(html),
        "ccp": fields.get("ccp") or form.find_ccp(html, "1"),
        "sitekey": cap.harvest_sitekey(html),
        "blob": cap.harvest_blob(html),
    }

    payload: dict[str, str] = {}
    # keep everything the page asked for (hidden fields, defaults, src tags)
    for k, v in fields.items():
        if k in ("firstname", "lastname", "reg_email__", "reg_email_confirmation__",
                 "reg_passwd__", "birthday_day", "birthday_month", "birthday_year",
                 "sex", "websubmit", "arkose_token", "captcha_response"):
            continue
        payload[k] = v

    payload.update({
        "firstname": ident.first,
        "lastname": ident.last,
        "reg_email__": ident.email,
        "reg_email_confirmation__": ident.email,
        "reg_passwd__": ident.password,
        "birthday_day": str(ident.day),
        "birthday_month": str(ident.month),
        "birthday_year": str(ident.year),
        "sex": str(ident.sex),
        "websubmit": "1",
    })
    if tokens["lsd"]:
        payload["lsd"] = tokens["lsd"]
    if tokens["jazoest"]:
        payload["jazoest"] = tokens["jazoest"]
    if tokens["reg_instance"]:
        payload["reg_instance"] = tokens["reg_instance"]
    if tokens["ccp"]:
        payload["ccp"] = tokens["ccp"]
    return payload, tokens


def classify(resp: requests.Response, sess: FBSession) -> tuple[Status, str]:
    if sess.c_user():
        return Status.SUCCESS, "c_user cookie set"
    body = (resp.text or "").lower()
    url = (resp.url or "").lower()
    if "/checkpoint" in url:
        return Status.CHALLENGE, f"redirected to {resp.url}"
    for h in PHONE_HINTS:
        if h in body and "required" in body:
            return Status.NEEDS_PHONE, "phone gate"
    for h in RATE_HINTS:
        if h in body:
            return Status.RATE_LIMITED, h
    if resp.status_code == 429:
        return Status.RATE_LIMITED, "http 429"
    for h in EMAIL_HINTS:
        if h in body:
            return Status.EMAIL_USED, h
    for h in NAME_HINTS:
        if h in body:
            return Status.NAME_REJECTED, h
    for h in CHECKPOINT_HINTS:
        if h in body:
            return Status.CHALLENGE, h
    if "arkose" in body or "funcaptcha" in body or "captcha" in body:
        return Status.CHALLENGE, "captcha in body"
    if resp.status_code >= 500:
        return Status.BLOCKED, f"server {resp.status_code}"
    if "reg_email__" in body:      # form came back = nothing took
        return Status.BLOCKED, "form bounced back"
    return Status.ERROR, f"unclassified ({resp.status_code})"


def _verify_cookies(sess: FBSession) -> bool:
    """A c_user cookie is not proof. If the account is real, home loads logged in."""
    try:
        r = sess.get("https://www.facebook.com/")
        if "logout" in (r.text or "").lower() or "log out" in (r.text or "").lower():
            return True
        return bool(sess.c_user()) and "/login" not in (r.url or "")
    except requests.RequestException:
        return bool(sess.c_user())


def register(cfg: Config, ident: Identity, sess: FBSession) -> RegistrationResult:
    res = RegistrationResult(status=Status.ERROR, email=ident.email,
                             password=ident.password, full_name=ident.full_name,
                             proxy=str(sess.proxy) if sess.proxy else "direct")

    if cfg.warmup and not sess.warmup():
        res.status = Status.PROXY_DEAD
        res.note = "warmup failed"
        return res

    reg_url = None
    resp = None
    for candidate in REG_URLS[ident.mobile]:
        try:
            r = sess.get(candidate, referer="https://www.facebook.com/")
        except requests.RequestException as exc:
            res.status = Status.PROXY_DEAD
            res.note = f"reg page: {type(exc).__name__}"
            return res
        if r.status_code == 200 and "reg_email__" in (r.text or ""):
            reg_url, resp = candidate, r
            break
        resp = r
    if reg_url is None:
        res.status = Status.BLOCKED
        res.note = f"no registration form served ({resp.status_code if resp else 'no response'})"
        return res

    payload, tokens = build_payload(resp.text, ident)

    if cfg.dry_run:
        res.status = Status.DRY_RUN
        res.note = f"{len(payload)} fields, lsd={'yes' if tokens['lsd'] else 'no'}, " \
                   f"sitekey={'yes' if tokens['sitekey'] else 'no'}"
        return res

    submit = SUBMIT[ident.mobile]
    time.sleep(0.4 + (ident.day % 7) / 10.0)      # small human beat before submit
    r = sess.post(submit, payload, referer=reg_url)
    status, note = classify(r, sess)

    # one captcha pass, if the page handed us a solvable challenge
    if status == Status.CHALLENGE and cfg.solver != "none":
        sitekey = tokens["sitekey"] or cfg.arkose_sitekey
        try:
            token = cap.solve(cfg.solver, cfg.solver_key, sitekey,
                              str(r.url or reg_url), tokens["blob"],
                              cfg.captcha_timeout)
        except Exception as exc:                  # noqa: BLE001
            res.status = Status.CHALLENGE
            res.note = f"captcha: {exc}"
            return res
        retry_payload = dict(payload)
        retry_payload["arkose_token"] = token
        retry_payload["captcha_response"] = token
        # re-harvest: the challenge response carries fresh session keys
        try:
            fresh = sess.get(reg_url, referer=str(r.url or reg_url))
            fresh_payload, fresh_tokens = build_payload(fresh.text, ident)
            for k in ("lsd", "jazoest", "reg_instance", "ccp"):
                if fresh_tokens.get(k):
                    retry_payload[k] = fresh_tokens[k]
            retry_payload["arkose_token"] = token
            retry_payload["captcha_response"] = token
        except requests.RequestException:
            pass
        r2 = sess.post(submit, retry_payload, referer=str(r.url or reg_url))
        status, note = classify(r2, sess)
        res.attempts = 2

    if status == Status.SUCCESS and not _verify_cookies(sess):
        status, note = Status.CHALLENGE, "cookie set but home not logged in"

    res.status = status
    res.note = note
    res.user_id = sess.c_user()
    res.cookies = sess.cookie_jar()
    return res
