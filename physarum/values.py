"""Understanding cell values: parsing (German-aware) and column profiling.

Every column of every table gets a profile: what kind of value it holds (date, money,
identifier, ...), which role it plays (name, e-mail, due date, status, ...), the parsed
values and a few statistics (fill rate, distinct values, entropy, dominant pattern).
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from datetime import time as dtime

from . import lexicon
from .text import fold, norm_key, tokens

EMPTY = {"", "-", "--", "—", "–", "n/a", "na", "null", "none", "#n/a", "#nv", "nan", "k.a.", "k. a.", "?", "/", "."}

KINDS = ("empty", "bool", "int", "number", "money", "percent", "duration", "date", "datetime", "time", "email",
         "phone", "url", "iban", "zip", "id", "text")
_TIME = re.compile(r"^([01]?\d|2[0-3])[:.]([0-5]\d)(?::([0-5]\d))?\s*(?:uhr|h)?$", re.I)
_NUM_PREFIX = re.compile(r"^(?:ca\.?|circa|etwa|rund|pauschal|ab|~|≈)\s*", re.I)

_CURRENCY = re.compile(r"(€|eur\b|euro\b|\$|usd\b|chf\b|£|gbp\b)", re.I)
_EMAIL = re.compile(r"^[\w.+%'-]+@[\w-]+(\.[\w-]+)*\.[a-z]{2,}$", re.I)
_URL = re.compile(r"^(https?://|www\.)\S+$", re.I)
_PHONE = re.compile(r"^\+?[\d][\d\s()/.\-]{4,}\d$|^\(\d+\)\s*[\d\s/.\-]+$")
_ISO_DATE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?:[T ](\d{1,2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?)?\s*(?:Z|[+-]\d{2}:?\d{2})?$")
_DE_DATE = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{4}|\d{2})(?:,?\s+(\d{1,2}):(\d{2})(?::(\d{2}))?(?:\s*uhr)?)?$", re.I)
_SLASH_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?$")
_DASH_DATE = re.compile(r"^(\d{1,2})-(\d{1,2})-(\d{4})$")
_TEXT_DATE_DMY = re.compile(r"^(\d{1,2})\.?\s+([a-zäöü]+)\.?\s+(\d{4})$", re.I)
_TEXT_DATE_MDY = re.compile(r"^([a-z]+)\.?\s+(\d{1,2}),?\s+(\d{4})$", re.I)
_DURATION = re.compile(r"^(\d+)\s*(tage?n?|t|d|days?|wochen?|w|weeks?|monate?n?|months?)?\.?\s*(netto)?$", re.I)
_MONTHS = {
    "jan": 1, "januar": 1, "january": 1, "jaenner": 1, "feb": 2, "februar": 2, "february": 2, "mar": 3, "maer": 3,
    "maerz": 3, "march": 3, "mrz": 3, "apr": 4, "april": 4, "mai": 5, "may": 5, "jun": 6, "juni": 6, "june": 6,
    "jul": 7, "juli": 7, "july": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "okt": 10,
    "oct": 10, "oktober": 10, "october": 10, "nov": 11, "november": 11, "dez": 12, "dec": 12, "dezember": 12,
    "december": 12,
}
_BOOL_TRUE = {"ja", "j", "yes", "y", "true", "wahr", "x", "✓", "✔", "ok", "1"}
_BOOL_FALSE = {"nein", "n", "no", "false", "falsch", "0", ""}
_DE_NUM = re.compile(r"^\d{1,3}(\.\d{3})+(,\d+)?$|^\d+,\d+$")
_EN_NUM = re.compile(r"^\d{1,3}(,\d{3})+(\.\d+)?$|^\d+\.\d+$")
_PLAIN_INT = re.compile(r"^\d+$")
_AMBIG_DE_THOUSAND = re.compile(r"^\d{1,3}\.\d{3}$")
_AMBIG_EN_THOUSAND = re.compile(r"^\d{1,3},\d{3}$")


def is_empty(v) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and math.isnan(v):
        return True
    if isinstance(v, str) and v.strip().lower() in EMPTY:
        return True
    return False


def parse_time(v) -> str | None:
    """'07:30', '7.30 Uhr', a spreadsheet time cell -> '07:30'."""
    if isinstance(v, dtime):
        return v.strftime("%H:%M")
    if isinstance(v, timedelta):
        mins = int(v.total_seconds() // 60)
        return f"{mins // 60:02d}:{mins % 60:02d}" if 0 <= mins < 24 * 60 else None
    if not isinstance(v, str):
        return None
    m = _TIME.match(v.strip())
    if not m:
        return None
    if "." in v and ":" not in v and "uhr" not in v.lower():
        return None  # "7.30" alone is a number, not a time
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def _clean_num_str(s: str) -> tuple[str, bool, str | None]:
    """Strip currency, spaces and sign markers. Returns (digits_and_separators, negative, currency)."""
    s = _NUM_PREFIX.sub("", s.strip())
    if re.search(r"[,.]-{1,2}\s*(€|eur)?$", s, re.I):
        s = re.sub(r"([,.])-{1,2}(\s*(€|eur)?)$", r"\g<1>00\2", s, flags=re.I)  # "139,-" is 139,00
    cur = None
    m = _CURRENCY.search(s)
    if m:
        cur = {"€": "EUR", "eur": "EUR", "euro": "EUR", "$": "USD", "usd": "USD", "chf": "CHF", "£": "GBP",
               "gbp": "GBP"}[m.group(1).lower()]
        s = _CURRENCY.sub("", s)
    s = s.replace(" ", "").replace(" ", "").replace(" ", "").replace("'", "")
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1]
    if s.endswith("-") and len(s) > 1:
        neg, s = True, s[:-1]
    if s.startswith("-") or s.startswith("−"):
        neg, s = (not neg), s[1:]
    elif s.startswith("+"):
        s = s[1:]
    return s, neg, cur


def number_locale_evidence(s: str) -> str | None:
    t, _, _ = _clean_num_str(s)
    if t.endswith("%"):
        t = t[:-1]
    if _DE_NUM.match(t) and not _AMBIG_DE_THOUSAND.match(t):
        return "de"
    if _EN_NUM.match(t) and not _AMBIG_EN_THOUSAND.match(t):
        return "en"
    return None


def parse_number(v, locale: str | None = "de") -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if not isinstance(v, str):
        return None
    t, neg, _cur = _clean_num_str(v)
    if t.endswith("%"):
        return None
    if not t or not re.fullmatch(r"[\d.,]+", t) or not any(c.isdigit() for c in t):
        return None
    if _PLAIN_INT.match(t):
        x = float(t)
    elif locale == "en":
        if not (_EN_NUM.match(t) or re.fullmatch(r"\d+\.\d+", t)):
            return None
        x = float(t.replace(",", ""))
    else:
        if _DE_NUM.match(t):
            x = float(t.replace(".", "").replace(",", "."))
        elif re.fullmatch(r"\d+\.\d{1,2}", t) or re.fullmatch(r"\d+\.\d{4,}", t):
            x = float(t)  # "12.5" in a German column: someone typed a dot
        else:
            return None
    return -x if neg else x


def parse_percent(v, locale: str | None = "de") -> float | None:
    """Return a fraction: '19%' -> 0.19, '7,5 %' -> 0.075."""
    if isinstance(v, str):
        s = v.strip()
        if s.endswith("%"):
            x = parse_number(s[:-1], locale)
            return None if x is None else x / 100.0
        return None
    return None


def _year(y: str) -> int:
    yi = int(y)
    if len(y) == 2:
        yi += 2000 if yi < 70 else 1900
    return yi


def _mk(y: int, m: int, d: int, hh=None, mm=None, ss=None):
    try:
        if hh is not None:
            return datetime(y, m, d, int(hh), int(mm or 0), int(ss or 0))
        return date(y, m, d)
    except ValueError:
        return None


def parse_date(v, order: str = "dmy"):
    """Parse many date notations. Returns date, datetime or None. `order` resolves 01/02/2026."""
    if isinstance(v, datetime):
        if v.time() == time(0, 0):
            return v.date()
        return v
    if isinstance(v, date):
        return v
    if not isinstance(v, str):
        return None
    s = v.strip()
    if not s or len(s) > 40:
        return None
    m = _ISO_DATE.match(s)
    if m:
        y, mo, d, hh, mi, ss = m.groups()
        r = _mk(int(y), int(mo), int(d), hh, mi, ss)
        if isinstance(r, datetime) and r.time() == time(0, 0):
            return r.date()
        return r
    m = _DE_DATE.match(s)
    if m:
        d, mo, y, hh, mi, ss = m.groups()
        r = _mk(_year(y), int(mo), int(d), hh, mi, ss)
        if isinstance(r, datetime) and r.time() == time(0, 0):
            return r.date()
        return r
    m = _SLASH_DATE.match(s)
    if m:
        a, b, y, hh, mi, ss = m.groups()
        a, b = int(a), int(b)
        if order == "mdy":
            a, b = b, a
        return _mk(_year(y), b, a, hh, mi, ss)
    m = _DASH_DATE.match(s)
    if m:
        d, mo, y = m.groups()
        return _mk(int(y), int(mo), int(d))
    m = _TEXT_DATE_DMY.match(s)
    if m:
        d, mon, y = m.groups()
        mo = _MONTHS.get(fold(mon)[:9]) or _MONTHS.get(fold(mon)[:3])
        if mo:
            return _mk(int(y), mo, int(d))
    m = _TEXT_DATE_MDY.match(s)
    if m:
        mon, d, y = m.groups()
        mo = _MONTHS.get(fold(mon)) or _MONTHS.get(fold(mon)[:3])
        if mo:
            return _mk(int(y), mo, int(d))
    return None


def slash_order_evidence(s: str) -> str | None:
    m = _SLASH_DATE.match(s.strip()) if isinstance(s, str) else None
    if not m:
        return None
    a, b = int(m.group(1)), int(m.group(2))
    if a > 12 >= b:
        return "dmy"
    if b > 12 >= a:
        return "mdy"
    return None


def iban_ok(s: str) -> bool:
    t = re.sub(r"\s+", "", s).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", t):
        return False
    r = t[4:] + t[:4]
    num = "".join(str(int(ch, 36)) for ch in r)
    return int(num) % 97 == 1


def shape(s: str) -> str:
    out = []
    for ch in s:
        if ch.isdigit():
            out.append("9")
        elif ch.isalpha():
            out.append("A")
        else:
            out.append(ch)
    return "".join(out)


def parse_duration(v) -> int | None:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return int(v) if float(v).is_integer() and 0 <= v <= 3650 else None
    if not isinstance(v, str):
        return None
    s = fold(v.strip())
    if s in ("sofort", "sofort netto", "immediately", "bar", "vorkasse", "zahlbar sofort", "sofort ohne abzug"):
        return 0
    m = _DURATION.match(s)
    if not m:
        # payment terms: "8 Tage 2 % Skonto, 30 Tage netto", "zahlbar innerhalb 14 Tagen ohne Abzug"
        net = re.search(r"(\d{1,3})\s*(?:tage?n?|t)\.?\s*(?:rein\s+)?(?:netto|ohne abzug|netto kasse)", s)
        if net:
            return int(net.group(1))
        days = [int(x) for x in re.findall(r"(\d{1,3})\s*(?:tage?n?|t\b)", s)]
        if days and ("zahlbar" in s or "skonto" in s or "netto" in s or "ziel" in s):
            return max(days)
        return None
    n = int(m.group(1))
    unit = (m.group(2) or "t")[0]
    return n * (7 if unit == "w" else 30 if unit == "m" else 1)


def parse_bool(v) -> bool | None:
    if isinstance(v, bool):
        return v
    s = fold(str(v)).strip()
    if s in _BOOL_TRUE:
        return True
    if s in _BOOL_FALSE:
        return False
    return None


@dataclass
class Profile:
    name: str
    kind: str = "empty"
    role: str | None = None
    concept: str | None = None
    locale: str | None = None
    date_order: str = "dmy"
    n: int = 0
    filled: int = 0
    distinct: int = 0
    values: list = field(default_factory=list, repr=False)
    keys: list = field(default_factory=list, repr=False)  # normalised match keys (str|None)
    top: list = field(default_factory=list)
    avg_len: float = 0.0
    entropy: float = 0.0
    pattern: str | None = None
    pattern_share: float = 0.0
    enum: list | None = None
    currency: str | None = None
    milestone: str | None = None
    unparsed: int = 0
    integer: bool = False

    @property
    def fill(self) -> float:
        return self.filled / self.n if self.n else 0.0

    @property
    def unique_ratio(self) -> float:
        return self.distinct / self.filled if self.filled else 0.0

    def bits(self) -> float:
        """Average information per value (used by the MDL decisions)."""
        return max(self.entropy, 0.5)


def _entropy(counter: Counter) -> float:
    total = sum(counter.values())
    if not total:
        return 0.0
    return -sum((c / total) * math.log2(c / total) for c in counter.values())


def profile_column(name: str, raw: list, meta: dict | None = None) -> Profile:
    """Profile one column. `meta` may carry hints: locale ('de'/'en'), number_format, native types."""
    meta = meta or {}
    p = Profile(name=name, n=len(raw))
    hrole = lexicon.header_role(name)
    p.concept = lexicon.header_concept(name)
    cells = [None if is_empty(v) else (v.strip() if isinstance(v, str) else v) for v in raw]
    present = [v for v in cells if v is not None]
    p.filled = len(present)
    if not present:
        p.kind = "empty"
        p.values = [None] * len(raw)
        p.keys = [None] * len(raw)
        return p

    strs = [v for v in present if isinstance(v, str)]
    natives = [v for v in present if not isinstance(v, str)]
    nfmt = (meta.get("number_format") or "").lower()
    sample = strs[:3000]

    def share(pred, items) -> float:
        if not items:
            return 0.0
        return sum(1 for x in items if pred(x)) / len(items)

    # locale evidence for numbers
    loc = Counter(e for e in (number_locale_evidence(s) for s in sample) if e)
    if loc:
        p.locale = "de" if loc["de"] >= loc["en"] else "en"
    else:
        p.locale = meta.get("locale") or "de"
    order = Counter(e for e in (slash_order_evidence(s) for s in sample) if e)
    p.date_order = "mdy" if order["mdy"] > order["dmy"] else ("dmy" if order else meta.get("date_order", "dmy"))

    kind = None
    n_nat = len(natives)
    # native types from spreadsheets
    if n_nat >= 0.8 * len(present):
        if all(isinstance(v, bool) for v in natives):
            kind = "bool"
        elif all(isinstance(v, (dtime, timedelta)) for v in natives):
            kind = "time"
        elif all(isinstance(v, (datetime, date)) for v in natives):
            kind = "datetime" if any(isinstance(v, datetime) and v.time() != time(0, 0) for v in natives) else "date"
        elif all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in natives):
            kind = "percent" if "%" in nfmt else "number"
            if any(c in nfmt for c in ("€", "eur", "$", "£")):
                kind = "money"
    if kind is None:
        s_all = [str(v) for v in present]
        tests = [
            ("email", lambda x: bool(_EMAIL.match(x))),
            ("url", lambda x: bool(_URL.match(x))),
            ("iban", lambda x: iban_ok(x)),
            ("time", lambda x: parse_time(x) is not None),
            ("date", lambda x: parse_date(x, p.date_order) is not None),
            ("percent", lambda x: parse_percent(x, p.locale) is not None),
            ("number", lambda x: parse_number(x, p.locale) is not None),
        ]
        for k, pred in tests:
            need = 0.9
            if k == "number" and hrole in ("money", "quantity"):
                need = 0.6  # "nach Aufwand" in an amount column does not make it text
            if share(pred, s_all[:3000]) >= need:
                kind = k
                break
        if kind == "date":
            parsed = [parse_date(x, p.date_order) for x in s_all[:3000]]
            if any(isinstance(d, datetime) and d.time() != time(0, 0) for d in parsed):
                kind = "datetime"
        if kind == "number" and share(lambda x: bool(_CURRENCY.search(x)), s_all[:3000]) >= 0.3:
            kind = "money"
        if kind is None:
            if hrole == "duration" and share(lambda x: parse_duration(x) is not None, s_all[:3000]) >= 0.8:
                kind = "duration"
            elif share(lambda x: parse_bool(x) is not None and fold(x) not in ("0", "1", ""), s_all[:3000]) >= 0.95 and \
                    len({fold(x) for x in s_all[:3000]}) <= 3:
                kind = "bool"
            elif hrole == "phone" or share(lambda x: bool(_PHONE.match(x)) and sum(c.isdigit() for c in x) >= 6
                                           and (x.startswith(("0", "+", "(")) or " " in x or "/" in x), s_all[:3000]) >= 0.9:
                kind = "phone"
            else:
                kind = "text"

    # header-driven refinements -------------------------------------------------------
    if kind == "number" and hrole == "duration":
        kind = "duration"
    if kind in ("number", "text") and hrole == "zip":
        digits = [re.sub(r"\D", "", str(v).split(".")[0]) for v in present]
        if share(lambda d: 4 <= len(d) <= 5, digits) >= 0.9:
            kind = "zip"
    if kind == "number" and hrole == "phone":
        kind = "phone"
    if kind == "number" and hrole == "money":
        kind = "money"
    if kind == "number" and hrole == "percent":
        vals = [parse_number(v, p.locale) for v in present]
        vals = [x for x in vals if x is not None]
        distinct_vals = len(set(vals))
        # rates are few and round (7, 19, 0.07, 7.5); amounts have arbitrary cents (46,52)
        odd_cents = sum(1 for x in vals if round(abs(x) * 100) % 50 != 0) / len(vals) if vals else 0
        if vals and odd_cents >= 0.5 and max(vals) > 1.0:
            kind = "money"  # "MwSt" holding tax amounts, not rates
        elif vals and max(vals) <= 1.0 and distinct_vals <= 12:
            kind = "percent"  # already fractions (0.07)
        elif vals and max(vals) <= 100 and distinct_vals <= 12:
            kind = "percent_whole"
        elif vals:
            kind = "money"
    if kind == "number" and hrole == "id":
        kind = "id"
    if kind == "bool" and hrole in ("quantity", "money"):
        kind = "number"
    if kind == "text" and hrole in ("money", "quantity"):
        # "12,50 EUR" mixed with "-" etc. already handled; leave as text
        pass

    # parse all values (each distinct raw value once) -------------------------------------
    values = []
    unparsed = 0
    cache: dict = {}
    for v in cells:
        if v is None:
            values.append(None)
            continue
        ck = (type(v), v) if not isinstance(v, (list, dict)) else None
        if ck is not None and ck in cache:
            x, bad = cache[ck]
        else:
            x = _parse_as(kind, v, p)
            bad = x is None
            if bad:
                x = str(v) if kind not in ("text", "id") else _as_text(v)
            if ck is not None:
                cache[ck] = (x, bad)
        unparsed += bad
        values.append(x)
    if kind == "percent_whole":
        kind = "percent"
    p.kind = kind
    p.unparsed = unparsed
    p.values = values

    # numbers: integer? currency?
    if kind in ("number", "money"):
        nums = [x for x in values if isinstance(x, (int, float))]
        p.integer = bool(nums) and all(float(x).is_integer() for x in nums)
        if kind == "money" or hrole == "money":
            cur = Counter(_clean_num_str(s)[2] for s in strs if _clean_num_str(s)[2])
            p.currency = cur.most_common(1)[0][0] if cur else "EUR"
    if kind == "number" and p.integer and hrole not in ("quantity", "money", "percent"):
        # integer columns that look like keys ("Nr", unique, wide range) become identifiers
        nums = sorted(x for x in values if isinstance(x, (int, float)))
        if hrole == "id" or (nums and len(set(nums)) == len(nums) and nums[0] >= 1000 and p.filled >= 5
                             and p.concept is not None):
            p.kind = kind = "id"
            p.values = values = [None if x is None else str(int(x)) if isinstance(x, (int, float)) else x
                                 for x in values]

    # keys, counts, entropy -------------------------------------------------------------
    keys = []
    kcache: dict = {}
    for x in values:
        if x is None:
            keys.append(None)
            continue
        try:
            hit = kcache.get(x)
        except TypeError:
            hit = None
        if hit is not None:
            keys.append(hit)
            continue
        if kind in ("date", "datetime"):
            k = x.isoformat() if isinstance(x, (date, datetime)) else norm_key(x)
        elif kind in ("number", "money", "percent", "duration"):
            k = repr(round(float(x), 6)) if isinstance(x, (int, float)) else norm_key(x)
        elif kind == "email":
            k = str(x).strip().casefold()
        else:
            k = norm_key(x)
        try:
            kcache[x] = k
        except TypeError:
            pass
        keys.append(k)
    p.keys = keys
    cnt = Counter(k for k in keys if k is not None)
    p.distinct = len(cnt)
    p.entropy = _entropy(cnt)
    first_value = {}
    for k, x in zip(keys, values):
        if k is not None and k not in first_value:
            first_value[k] = x
    p.top = [(first_value[k], c) for k, c in cnt.most_common(8)]
    lens = [len(str(v)) for v in present[:3000]]
    p.avg_len = sum(lens) / len(lens) if lens else 0.0

    if kind in ("text", "id"):
        shapes = Counter(shape(str(v)) for v in present[:3000])
        top_shape, top_n = shapes.most_common(1)[0]
        p.pattern = top_shape
        p.pattern_share = top_n / len(present[:3000])
        # id-like text: consistent shape with digits, no spaces
        if kind == "text":
            has_digit = "9" in top_shape
            spaced = share(lambda x: " " in str(x), present[:3000]) > 0.2
            coded = (has_digit and not spaced and p.avg_len <= 24 and
                     (p.pattern_share >= 0.6 or hrole == "id") and
                     share(lambda x: any(c.isdigit() for c in str(x)), present[:3000]) >= 0.9)
            if coded and (p.distinct > 12 or hrole == "id" or p.unique_ratio > 0.7 or p.pattern_share >= 0.95):
                p.kind = kind = "id"

    # role ---------------------------------------------------------------------------------
    p.role = _decide_role(p, hrole)
    if kind == "text" and p.role not in ("name", "person", "street", "notes", "email", "city"):
        limit = min(30, max(3, int(0.2 * p.filled)))
        if p.filled >= 6 and p.distinct <= limit and p.avg_len <= 32 and p.distinct < p.filled:
            p.enum = [v for v, _ in Counter(v for v in values if v is not None).most_common()]
            if p.role is None:
                p.role = "category"
    if kind in ("date", "datetime"):
        p.milestone = lexicon.milestone_label(name)
    return p


def _as_text(v) -> str:
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, (datetime, date)):
        return v.strftime("%d.%m.%Y")
    return str(v).strip()


def _parse_as(kind: str, v, p: Profile):
    if kind == "phone" and isinstance(v, (int, float)) and not isinstance(v, bool):
        digits = str(int(v))  # a spreadsheet ate the leading zero
        if digits.startswith("49") and len(digits) >= 11:
            return "+" + digits
        return digits if digits.startswith("0") else "0" + digits
    if kind == "time":
        return parse_time(v)
    if kind in ("text", "id", "phone"):
        return _as_text(v)
    if kind == "email":
        s = str(v).strip()
        return s if _EMAIL.match(s) else None
    if kind == "url":
        return str(v).strip()
    if kind == "iban":
        s = re.sub(r"\s+", "", str(v)).upper()
        return s if iban_ok(s) else None
    if kind == "zip":
        d = re.sub(r"\D", "", str(v).split(".")[0] if isinstance(v, float) else str(v))
        return d.zfill(5) if 4 <= len(d) <= 5 else None
    if kind in ("date", "datetime"):
        return parse_date(v, p.date_order)
    if kind in ("number", "money"):
        return parse_number(v, p.locale)
    if kind == "percent":
        if isinstance(v, str):
            x = parse_percent(v, p.locale)
            return x if x is not None else parse_number(v, p.locale)
        return float(v) if isinstance(v, (int, float)) else None
    if kind == "percent_whole":
        if isinstance(v, str):
            x = parse_percent(v, p.locale)
            if x is not None:
                return x
        x = parse_number(v, p.locale)
        return None if x is None else x / 100.0
    if kind == "duration":
        return parse_duration(v)
    if kind == "bool":
        return parse_bool(v)
    return v


def _decide_role(p: Profile, hrole: str | None) -> str | None:
    k = p.kind
    by_kind = {"email": "email", "phone": "phone", "url": "url", "iban": "iban", "zip": "zip",
               "percent": "percent", "duration": "duration", "bool": "flag"}
    if k in by_kind:
        return by_kind[k]
    if k in ("date", "datetime"):
        return "due" if hrole == "due" else "date"
    if k == "money":
        return "money"
    if k == "number":
        if hrole in ("money", "quantity", "percent"):
            return hrole
        return "quantity" if p.integer else "number"
    if k == "id":
        return "id"
    # text
    if hrole in ("name", "person", "street", "city", "country", "notes", "status", "category", "unit", "email",
                 "bic", "vat_id"):
        return hrole
    if hrole == "id":
        return "name" if p.avg_len > 3 else "id"
    if p.avg_len > 45:
        return "notes"
    if p.concept:
        return "name"  # a column named "Kunde" or "Lieferant" holds names
    return None


def profile_table(columns: list[str], rows: list[list], meta: dict | None = None) -> list[Profile]:
    meta = meta or {}
    formats = meta.get("number_formats") or {}
    out = []
    for j, name in enumerate(columns):
        col = [r[j] if j < len(r) else None for r in rows]
        out.append(profile_column(name, col, {"locale": meta.get("locale"), "number_format": formats.get(str(j))}))
    return out


# --- display ----------------------------------------------------------------------------------

def fmt_number(x: float, decimals: int = 2) -> str:
    s = f"{x:,.{decimals}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def display(value, kind: str, currency: str | None = None) -> str:
    if value is None or value == "":
        return ""
    try:
        if kind == "money":
            sym = {"EUR": "€", "USD": "$", "GBP": "£", "CHF": "CHF"}.get(currency or "EUR", currency or "€")
            return f"{fmt_number(float(value))} {sym}"
        if kind == "number":
            x = float(value)
            return fmt_number(x, 0) if x.is_integer() else fmt_number(x, 2).rstrip("0").rstrip(",")
        if kind == "percent":
            x = float(value) * 100
            return (fmt_number(x, 0) if abs(x - round(x)) < 1e-9 else fmt_number(x, 1)) + " %"
        if kind == "duration":
            n = int(value)
            return "sofort" if n == 0 else f"{n} Tage" if n != 1 else "1 Tag"
        if kind == "date":
            d = value if isinstance(value, date) else date.fromisoformat(str(value)[:10])
            return d.strftime("%d.%m.%Y")
        if kind == "datetime":
            d = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
            return d.strftime("%d.%m.%Y %H:%M")
        if kind == "bool":
            return "ja" if value in (True, "true", 1) else "nein"
    except (ValueError, TypeError):
        return str(value)
    return str(value)


def to_json_value(x):
    """Typed python value -> JSON-storable value."""
    if isinstance(x, datetime):
        return x.isoformat(timespec="minutes")
    if isinstance(x, date):
        return x.isoformat()
    if isinstance(x, float) and x.is_integer() and abs(x) < 1e15:
        return x  # keep floats as floats; JSON handles them
    return x


def as_date(x) -> date | None:
    if x is None:
        return None
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    try:
        return date.fromisoformat(str(x)[:10])
    except ValueError:
        return None


_PERIOD_NUM = re.compile(r"^(\d{1,2})\s*/\s*(\d{4})$")
_PERIOD_TXT = re.compile(r"^([a-zäöü]+)\.?\s+(\d{4})$", re.I)
_PERIOD_KW = re.compile(r"^(?:kw|kalenderwoche|woche|wk|cw|week)\s*\.?\s*(\d{1,2})\s*(?:[/.-]\s*|\s+)(\d{4})$", re.I)
_PERIOD_Q = re.compile(r"^(?:q\s*([1-4])|([1-4])\s*\.\s*quartal)\s*(?:[/.-]\s*|\s+)?(\d{4})$", re.I)


def _month_span(y: int, mo: int) -> tuple[date, date]:
    a = date(y, mo, 1)
    return a, (a + timedelta(days=32)).replace(day=1) - timedelta(days=1)


def parse_period(v) -> tuple[date, date] | None:
    """'10/2026', 'Okt. 2026', 'KW 44/2026', 'Q4/2026' -> (first day, last day). Planned dates in
    craft businesses are rarely days: "next maintenance in October"."""
    if v is None or isinstance(v, (int, float)):
        return None
    s = " ".join(str(v).strip().split())
    if not s or len(s) > 24:
        return None
    try:
        m = _PERIOD_KW.match(s)
        if m:
            a = date.fromisocalendar(int(m.group(2)), int(m.group(1)), 1)
            return a, a + timedelta(days=6)
        m = _PERIOD_Q.match(s)
        if m:
            q, y = int(m.group(1) or m.group(2)), int(m.group(3))
            return _month_span(y, 3 * q - 2)[0], _month_span(y, 3 * q)[1]
        m = _PERIOD_NUM.match(s)
        if m:
            mo, y = int(m.group(1)), int(m.group(2))
            return _month_span(y, mo) if 1 <= mo <= 12 and 1900 < y < 2200 else None
        m = _PERIOD_TXT.match(s)
        if m:
            f = fold(m.group(1))
            mo = _MONTHS.get(f) or _MONTHS.get(f[:3])
            y = int(m.group(2))
            return _month_span(y, mo) if mo and 1900 < y < 2200 else None
    except ValueError:
        return None
    return None


_KW_NOYEAR = re.compile(r"^(?:kw|kalenderwoche|woche|wk|cw)\s*\.?\s*(\d{1,2})$", re.I)


def event_date(v, near: date | None = None) -> date | None:
    """When something happened: a day, or the first day of a period. "KW 44" without a year
    takes the year that puts it right after `near` (the start of the case)."""
    d = as_date(v)
    if d:
        return d
    if v is None or isinstance(v, (int, float)):
        return None
    p = parse_period(v)
    if p:
        return p[0]
    m = _KW_NOYEAR.match(" ".join(str(v).strip().split()))
    if m and near:
        for y in (near.year, near.year + 1):
            try:
                c = date.fromisocalendar(y, int(m.group(1)), 1)
            except ValueError:
                continue
            if c >= near - timedelta(days=7):
                return c
    return None


def due_range(v) -> tuple[date, date] | None:
    """A due value: a day, or a period from its first to its last day."""
    d = as_date(v)
    if d:
        return d, d
    return parse_period(v)


def period_text(d: date, like: str | None = None) -> str:
    """The period of a day, written the way the firm writes it."""
    s = fold(like or "")
    if s.startswith(("kw", "woche", "kalenderwoche", "wk", "cw", "week")):
        y, w, _ = d.isocalendar()
        return f"KW {w}/{y}"
    if s[:1] == "q" or "quartal" in s:
        return f"Q{(d.month - 1) // 3 + 1}/{d.year}"
    if s[:1].isalpha():
        names = ["Jan.", "Feb.", "März", "Apr.", "Mai", "Juni", "Juli", "Aug.", "Sep.", "Okt.", "Nov.", "Dez."]
        return f"{names[d.month - 1]} {d.year}"
    return f"{d.month:02d}/{d.year}"


INTERVAL_MONTHS = {"monatlich": 1, "zweimonatlich": 2, "vierteljaehrlich": 3, "quartalsweise": 3, "quartal": 3,
                   "halbjaehrlich": 6, "jaehrlich": 12, "zweijaehrlich": 24, "alle 2 jahre": 24, "monthly": 1,
                   "quarterly": 3, "half-yearly": 6, "semiannual": 6, "yearly": 12, "annual": 12, "annually": 12,
                   "biennial": 24}


def interval_months(v) -> int | None:
    """'jährlich' -> 12, 'halbjährlich' -> 6, 'alle 3 Monate' -> 3."""
    if v is None:
        return None
    s = " ".join(fold(str(v)).replace("-", " ").split())
    if s in INTERVAL_MONTHS:
        return INTERVAL_MONTHS[s]
    m = re.match(r"^(?:alle|every)\s+(\d{1,2})\s+(monate?|months?|jahre?|years?)$", s)
    if m:
        n = int(m.group(1))
        return n if m.group(2).startswith(("monat", "month")) else 12 * n
    return None


def add_months(d: date, n: int) -> date:
    y, mo = divmod(d.month - 1 + n, 12)
    y += d.year
    mo += 1
    last = _month_span(y, mo)[1].day
    return date(y, mo, min(d.day, last))


def days_between(a, b) -> int | None:
    da, db = as_date(a), as_date(b)
    if da is None or db is None:
        return None
    return (db - da).days


def add_days(d, n: int):
    dd = as_date(d)
    return None if dd is None else dd + timedelta(days=int(n))


_ASOF_PATTERNS = [
    re.compile(r"(?:stand|stichtag|per|vom|zum|as of)\W{0,3}(\d{1,2}\.\d{1,2}\.\d{2,4})", re.I),
    re.compile(r"\b(\d{1,2}\.\d{1,2}\.\d{4})\b"),
    re.compile(r"\b(\d{4}-\d{2}-\d{2})\b"),
]
_KW = re.compile(r"\bKW\s*(\d{1,2})\s*[/.-]?\s*(\d{4})", re.I)
_MONTH_YEAR = re.compile(r"\b(januar|februar|m(?:ä|ae)rz|april|mai|juni|juli|august|september|oktober|november|dezember)\s+(\d{4})", re.I)


def asof_date(text: str | None) -> date | None:
    """'Kundenliste Stand: 15.01.2025', 'Lagerbestand KW 44/2026', 'Preise Oktober 2026' -> a date."""
    if not text:
        return None
    for rx in _ASOF_PATTERNS:
        m = rx.search(text)
        if m:
            d = parse_date(m.group(1))
            if d:
                return d.date() if isinstance(d, datetime) else d
    m = _KW.search(text)
    if m:
        try:
            return date.fromisocalendar(int(m.group(2)), int(m.group(1)), 1)
        except ValueError:
            pass
    m = _MONTH_YEAR.search(text)
    if m:
        mo = _MONTHS.get(fold(m.group(1))[:9]) or _MONTHS.get(fold(m.group(1))[:3])
        if mo:
            return date(int(m.group(2)), mo, 1)
    return None
