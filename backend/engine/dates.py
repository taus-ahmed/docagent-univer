# -*- coding: utf-8 -*-
"""One date reader for every locale (Part 1.3).

Reads ISO (2024-03-05), numeric day/month/year in either order with `/ - .`
or spaces, year-first numerics (2024/03/05), English month names (5 Mar 2024,
March 5, 2024, 05-Mar-24) and two-digit years (pivot: 00-69 -> 20xx,
70-99 -> 19xx; recorded).

DAY AND MONTH ARE NEVER GUESSED. 03/05/2024 is 3 May in most of the world and
March 5 in the United States. When both parts are 12 or below and differ, the
order is taken only from evidence, in this order: the template's or firm's
locale, then the document's other dates (one whose day is above 12 settles
the order — when every such date agrees). Unresolved: `value` is None,
`ambiguous` is True, reason `date_ambiguous`; the verbatim text is kept.

Digits in another script (Devanagari, Arabic-Indic, …) are not read:
`date_unreadable`. Nothing is converted between scripts or calendars.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Iterable, Optional

DATE_AMBIGUOUS = "date_ambiguous"
DATE_UNREADABLE = "date_unreadable"

_MONTHS = {}
for _i, _names in enumerate([
        ("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"),
        ("may",), ("jun", "june"), ("jul", "july"), ("aug", "august"),
        ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"),
        ("dec", "december")], 1):
    for _n in _names:
        _MONTHS[_n] = _i

#: the numeric order a locale writes; a locale not here gives no hint
_MDY_LOCALES = {"en-us", "en-ph", "en-pr", "es-us", "en-fm", "en-mh", "en-pw"}
_YMD_LANGS = {"ja", "zh", "ko", "hu", "lt", "mn"}


def order_for_locale(locale) -> Optional[str]:
    """"MDY", "DMY", "YMD" or None for an unknown locale. A bare language
    ("en") says nothing: English is written both ways."""
    if not locale:
        return None
    loc = str(locale).strip().lower().replace("_", "-")
    if loc in _MDY_LOCALES:
        return "MDY"
    lang = loc.split("-")[0]
    if lang in _YMD_LANGS:
        return "YMD"
    if "-" in loc or lang != "en":
        return "DMY"
    return None


@dataclass(frozen=True)
class DateValue:
    text: str
    value: Optional[date] = None
    order: str = ""              # "DMY" / "MDY" / "YMD" / "ISO" / "named"
    ambiguous: bool = False
    resolved_by: str = ""        # "locale" / "document" / "" (not needed)
    two_digit_year: bool = False
    reasons: tuple = ()

    @property
    def ok(self):
        return self.value is not None


_NUMERIC = re.compile(r"^(\d{1,4})[\s/.\-](\d{1,2})[\s/.\-](\d{1,4})$")
_NAMED_DMY = re.compile(r"^(\d{1,2})(?:st|nd|rd|th)?[\s\-./,]+([A-Za-z]{3,9})\.?[\s\-./,]+(\d{2,4})$")
_NAMED_MDY = re.compile(r"^([A-Za-z]{3,9})\.?[\s\-./]+(\d{1,2})(?:st|nd|rd|th)?,?[\s\-./]+(\d{2,4})$")

def _year(y: str):
    n = int(y)
    if len(y) == 2:
        return (2000 + n if n < 70 else 1900 + n), True
    if len(y) == 4:
        return n, False
    return None, False


def _make(y, m, d):
    try:
        return date(y, m, d)
    except ValueError:
        return None


def parse_date(text, order_hint: Optional[str] = None) -> DateValue:
    raw = "" if text is None else str(text)
    t = raw.strip()
    if not t:
        return DateValue(raw, reasons=("empty",))
    if any(ch.isdigit() and not ("0" <= ch <= "9") for ch in t):
        return DateValue(raw, reasons=(DATE_UNREADABLE,))
    m = _NAMED_DMY.match(t)
    if m and m.group(2).lower() in _MONTHS:
        y, two = _year(m.group(3))
        v = _make(y, _MONTHS[m.group(2).lower()], int(m.group(1))) if y else None
        return DateValue(raw, v, "named", two_digit_year=two,
                         reasons=() if v else ("not_a_date",))
    m = _NAMED_MDY.match(t)
    if m and m.group(1).lower() in _MONTHS:
        y, two = _year(m.group(3))
        v = _make(y, _MONTHS[m.group(1).lower()], int(m.group(2))) if y else None
        return DateValue(raw, v, "named", two_digit_year=two,
                         reasons=() if v else ("not_a_date",))
    m = _NUMERIC.match(t)
    if not m:
        return DateValue(raw, reasons=("not_a_date",))
    a, b, c = m.groups()
    if len(a) == 4:                                   # year first: YMD
        v = _make(int(a), int(b), int(c))
        return DateValue(raw, v, "ISO" if "-" in t else "YMD",
                         reasons=() if v else ("not_a_date",))
    if len(c) not in (2, 4):
        return DateValue(raw, reasons=("not_a_date",))
    y, two = _year(c)
    p, q = int(a), int(b)
    dmy, mdy = _make(y, q, p), _make(y, p, q)
    if dmy and not mdy:
        return DateValue(raw, dmy, "DMY", two_digit_year=two)
    if mdy and not dmy:
        return DateValue(raw, mdy, "MDY", two_digit_year=two)
    if not dmy:
        return DateValue(raw, reasons=("not_a_date",))
    if dmy == mdy:                                    # 05/05/2024
        return DateValue(raw, dmy, "DMY", two_digit_year=two)
    if order_hint in ("DMY", "MDY"):
        return DateValue(raw, dmy if order_hint == "DMY" else mdy, order_hint,
                         resolved_by="hint", two_digit_year=two)
    return DateValue(raw, ambiguous=True, two_digit_year=two,
                     reasons=(DATE_AMBIGUOUS,))


def document_order(texts: Iterable, locale=None):
    """("DMY"|"MDY"|None, how): the locale's order, else the order every
    UNAMBIGUOUS numeric date on the document agrees on."""
    loc = order_for_locale(locale)
    if loc in ("DMY", "MDY"):
        return loc, "locale"
    votes = set()
    for t in texts or ():
        d = parse_date(t)
        if d.ok and d.order in ("DMY", "MDY") and not d.resolved_by:
            p, q = (int(x) for x in _NUMERIC.match(str(t).strip()).groups()[:2])
            if p != q:
                votes.add(d.order)
    if len(votes) == 1:
        return votes.pop(), "document"
    return None, ""


def looks_like_a_date(text) -> bool:
    """Shaped like one of the dates above (digits of any script counted)."""
    t = str(text or "").strip()
    if not t or len(t) > 32:
        return False
    norm = "".join("0" if c.isdigit() and not ("0" <= c <= "9") else c for c in t)
    return bool(_NUMERIC.match(norm) or _NAMED_DMY.match(norm)
                or _NAMED_MDY.match(norm))


__all__ = ["DATE_AMBIGUOUS", "DATE_UNREADABLE", "DateValue", "document_order",
           "looks_like_a_date", "order_for_locale", "parse_date"]
