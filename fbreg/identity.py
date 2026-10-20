"""Identity generation: names, mail, password, birthday, device fingerprint."""
from __future__ import annotations

import random
import secrets
import string
from dataclasses import dataclass, asdict, field

FIRST_M = ["james", "michael", "daniel", "chris", "andrew", "joshua", "ryan",
           "tyler", "brandon", "kevin", "marcus", "ethan", "noah", "liam",
           "connor", "adam", "eric", "justin", "nathan", "caleb", "mateo",
           "andre", "dylan", "lucas", "oscar"]
FIRST_F = ["emma", "olivia", "sophia", "ava", "isabella", "mia", "chloe",
           "grace", "hannah", "emily", "sarah", "rachel", "laura", "julia",
           "natalie", "ella", "zoe", "lily", "amber", "claire", "nina",
           "elena", "maya", "sofia", "leah"]
LAST = ["smith", "johnson", "williams", "brown", "jones", "miller", "davis",
        "garcia", "rodriguez", "wilson", "martinez", "anderson", "taylor",
        "thomas", "moore", "jackson", "martin", "lee", "perez", "thompson",
        "white", "harris", "sanchez", "clark", "ramirez", "lewis", "robinson",
        "walker", "young", "allen", "king", "wright", "scott", "torres",
        "nguyen", "hill", "flores", "green", "adams", "nelson"]

# Mobile UA families, each with the sec-ch-ua that actually matches it.
ANDROID_PROFILES = [
    ("Mozilla/5.0 (Linux; Android 14; SM-S911B) AppleWebKit/537.36 (KHTML, like Gecko) "
     "Chrome/133.0.0.0 Mobile Safari/537.36",
     '"Chromium";v="133", "Not(A:Brand";v="24", "Google Chrome";v="133"', "Android", "14.0.0"),
    ("Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) "
     "Chrome/132.0.0.0 Mobile Safari/537.36",
     '"Chromium";v="132", "Not(A:Brand";v="24", "Google Chrome";v="132"', "Android", "13.0.0"),
    ("Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) "
     "Chrome/134.0.0.0 Mobile Safari/537.36",
     '"Chromium";v="134", "Not(A:Brand";v="99", "Google Chrome";v="134"', "Android", "14.0.0"),
    ("Mozilla/5.0 (Linux; Android 12; moto g(60)) AppleWebKit/537.36 (KHTML, like Gecko) "
     "Chrome/131.0.0.0 Mobile Safari/537.36",
     '"Chromium";v="131", "Not(A:Brand";v="24", "Google Chrome";v="131"', "Android", "12.0.0"),
    ("Mozilla/5.0 (Linux; Android 14; SM-A546B) AppleWebKit/537.36 (KHTML, like Gecko) "
     "Chrome/133.0.0.0 Mobile Safari/537.36",
     '"Chromium";v="133", "Not(A:Brand";v="24", "Google Chrome";v="133"', "Android", "14.0.0"),
]

DESKTOP_PROFILES = [
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
     "Chrome/133.0.0.0 Safari/537.36",
     '"Chromium";v="133", "Not(A:Brand";v="24", "Google Chrome";v="133"', "Windows", "15.0.0"),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
     "Chrome/132.0.0.0 Safari/537.36",
     '"Chromium";v="132", "Not(A:Brand";v="24", "Google Chrome";v="132"', "macOS", "14.5.0"),
]


def _pw(n: int = 14) -> str:
    """Mixed-case + digits + one symbol, no ambiguous glyphs."""
    lower = "abcdefghjkmnpqrstuvwxyz"
    upper = "ABCDEFGHJKMNPQRSTUVWXYZ"
    digit = "23456789"
    sym = "!@#$%&*?"
    core = [random.choice(lower) for _ in range(n - 4)]
    core += [random.choice(upper), random.choice(digit), random.choice(sym),
             random.choice(lower + digit)]
    random.shuffle(core)
    return "".join(core)


@dataclass
class Identity:
    first: str
    last: str
    email: str
    password: str
    day: int
    month: int
    year: int
    sex: int                  # 1 = female, 2 = male (FB's own encoding)
    user_agent: str
    sec_ch_ua: str
    platform: str
    platform_version: str
    mobile: bool
    locale: str = "en_US"
    timezone: str = "America/New_York"

    def as_dict(self) -> dict:
        return asdict(self)

    @property
    def full_name(self) -> str:
        return f"{self.first} {self.last}".title()


def make_identity(email_domain: str = "", age_min: int = 18, age_max: int = 42,
                  mobile: bool | None = None, prefix_len: int = 12) -> Identity:
    sex = random.choice([1, 2])
    first = random.choice(FIRST_F if sex == 1 else FIRST_M)
    last = random.choice(LAST)

    if mobile is None:
        mobile = random.random() < 0.75          # mobile traffic is the quiet path
    ua, ch, plat, platv = random.choice(ANDROID_PROFILES if mobile else DESKTOP_PROFILES)

    year = 2026 - random.randint(age_min, age_max)
    month = random.randint(1, 12)
    day = random.randint(1, 28)

    if email_domain:
        alphabet = string.ascii_lowercase + string.digits
        local = "".join(secrets.choice(alphabet) for _ in range(prefix_len))
        email = f"{local}@{email_domain}"
    else:
        # fallback: no catch-all configured, still emits a shape the flow accepts
        alphabet = string.ascii_lowercase + string.digits
        local = "".join(secrets.choice(alphabet) for _ in range(prefix_len))
        email = f"{local}@gmail.com"

    return Identity(
        first=first, last=last, email=email, password=_pw(),
        day=day, month=month, year=year, sex=sex,
        user_agent=ua, sec_ch_ua=ch, platform=plat, platform_version=platv,
        mobile=mobile,
    )
