# -*- coding: utf-8 -*-
"""One parser for every amount the engine reads — any common locale.

Every validator (cheque, invoice, bank, payslip, receipt), the duplicate
check and the export read amounts through `parse_amount`. There were three
parsers: the cheque's (US only, refusing anything else), the validators'
`money` (US only, accepting "1,234" as 1234 whatever the document), and the
exporter's (which turned "1.234,56" into 1.23456 — a wrong number, silently).

WHAT IT READS

    grouping / decimal   1,234.56   1.234,56   1 234,56   1'234.56
                         1,23,456.78 (Indian lakh grouping)   1234.56   1234
    currency             a symbol or an ISO 4217 code, before or after:
                         $ US$ C$ A$ S$ £ € ¥ 円 ₹ Rs Rs. د.إ AED CHF … any code
    negatives            -10  10-  (10)  10 Dr   (Cr is positive)
    percent              8.25%

WHAT IT RETURNS — `Amount`: the exact `Decimal` (or None), the currency
(ISO code, or None when unknown or when a symbol names several), the
notation detected, `ambiguous`, and reason codes.

AMBIGUITY IS NEVER GUESSED. "1,234" and "1.234" are a thousand-and-something
in one locale and one-and-something in another. They are resolved only by
evidence, in this order:

  1. a decimal-separator hint: the template's locale, then the firm's
     (`locale:` in its YAML), then the DOCUMENT itself (`document_hint`: the
     other numbers on it whose style is unambiguous, when they all agree);
  2. the currency's ISO 4217 minor units: a 2-decimal currency cannot have a
     3-digit fraction, so "$1,234" is 1234; a 0-decimal currency (JPY) has no
     fraction at all.

Unresolved, `value` is None, `ambiguous` is True and the reason is
`number_ambiguous`: the caller keeps the verbatim text and sends it for
review. A fraction that disagrees with the currency's minor units (a yen
amount with decimals, a dollar amount with three) parses, and carries
`minor_units_mismatch`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Iterable, Optional

# ── ISO 4217 minor units (decimal places). Everything not listed is 2. ──────
_MINOR = {
    # 0 decimals
    "JPY": 0, "KRW": 0, "VND": 0, "CLP": 0, "ISK": 0, "PYG": 0, "UGX": 0,
    "XAF": 0, "XOF": 0, "XPF": 0, "KMF": 0, "DJF": 0, "GNF": 0, "RWF": 0,
    "VUV": 0, "BIF": 0, "UYI": 0,
    # 3 decimals
    "BHD": 3, "IQD": 3, "JOD": 3, "KWD": 3, "LYD": 3, "OMR": 3, "TND": 3,
}

#: Every active ISO 4217 code (2024). A three-letter word outside this set is
#: not a currency, so "TOTAL 12.00" does not read "TOT" as one.
ISO_4217 = frozenset("""
AED AFN ALL AMD ANG AOA ARS AUD AWG AZN BAM BBD BDT BGN BHD BIF BMD BND BOB
BRL BSD BTN BWP BYN BZD CAD CDF CHF CLP CNY COP CRC CUP CVE CZK DJF DKK DOP
DZD EGP ERN ETB EUR FJD FKP GBP GEL GHS GIP GMD GNF GTQ GYD HKD HNL HTG HUF
IDR ILS INR IQD IRR ISK JMD JOD JPY KES KGS KHR KMF KPW KRW KWD KYD KZT LAK
LBP LKR LRD LSL LYD MAD MDL MGA MKD MMK MNT MOP MRU MUR MVR MWK MXN MYR MZN
NAD NGN NIO NOK NPR NZD OMR PAB PEN PGK PHP PKR PLN PYG QAR RON RSD RUB RWF
SAR SBD SCR SDG SEK SGD SHP SLE SOS SRD SSP STN SVC SYP SZL THB TJS TMT TND
TOP TRY TTD TWD TZS UAH UGX USD UYU UZS VES VND VUV WST XAF XCD XOF XPF YER
ZAR ZMW ZWL
""".split())


def minor_units(code: Optional[str]) -> Optional[int]:
    if not code or code not in ISO_4217:
        return None
    return _MINOR.get(code, 2)


#: symbol -> the currencies it may name. One candidate = that currency.
SYMBOLS = {
    "US$": ("USD",), "C$": ("CAD",), "CA$": ("CAD",), "A$": ("AUD",),
    "AU$": ("AUD",), "S$": ("SGD",), "HK$": ("HKD",), "NZ$": ("NZD",),
    "R$": ("BRL",), "MX$": ("MXN",),
    "$": ("USD", "CAD", "AUD", "SGD", "HKD", "NZD", "MXN"),
    "£": ("GBP",), "€": ("EUR",), "円": ("JPY",), "¥": ("JPY", "CNY"),
    "元": ("CNY",), "₹": ("INR",), "Rs.": ("INR",), "Rs": ("INR",),
    "₨": ("INR", "PKR", "LKR", "NPR"), "د.إ": ("AED",), "Dhs": ("AED",),
    "₩": ("KRW",), "₽": ("RUB",), "₺": ("TRY",), "₪": ("ILS",), "₱": ("PHP",),
    "฿": ("THB",), "₫": ("VND",), "zł": ("PLN",), "Fr.": ("CHF",),
    "kr": ("SEK", "NOK", "DKK", "ISK"),
}
#: longest first, so "US$" wins over "$" and "Rs." over "Rs"
_SYMBOL_ORDER = sorted(SYMBOLS, key=len, reverse=True)

#: decimal separator by locale (language or language-region). A locale not
#: here gives no hint.
_LOCALE_DECIMAL = {
    "en": ".", "ja": ".", "zh": ".", "ko": ".", "hi": ".", "ar": ".",
    "he": ".", "th": ".", "ms": ".", "en-in": ".", "de-ch": ".", "fr-ch": ".",
    "it-ch": ".", "es-mx": ".",
    "de": ",", "fr": ",", "es": ",", "it": ",", "nl": ",", "pt": ",",
    "da": ",", "sv": ",", "nb": ",", "no": ",", "fi": ",", "pl": ",",
    "cs": ",", "ru": ",", "tr": ",", "id": ",", "vi": ",", "el": ",",
}

#: the spaces a number may be grouped with (space, no-break, narrow no-break,
#: thin)
_SPACES = "    "
_GROUP_CHARS = ",.'’" + _SPACES

NUMBER_AMBIGUOUS = "number_ambiguous"
MINOR_UNITS_MISMATCH = "minor_units_mismatch"


@dataclass(frozen=True)
class Amount:
    text: str
    value: Optional[Decimal] = None
    currency: Optional[str] = None          # ISO code, when one is certain
    currencies: tuple = ()                   # every currency the text may name
    notation: str = ""                       # e.g. "1,234.56", "1.234,56", "lakh"
    decimal_sep: Optional[str] = None        # "." / "," / None (integer or ambiguous)
    decimals: int = 0
    negative: bool = False
    percent: bool = False
    ambiguous: bool = False
    #: how an ambiguity was resolved, when it was ("hint", "minor_units")
    resolved_by: str = ""
    reasons: tuple = ()

    @property
    def ok(self) -> bool:
        return self.value is not None


def decimal_for_locale(locale: Optional[str]) -> Optional[str]:
    """The decimal separator a locale uses (`de-DE` -> ","), or None."""
    if not locale:
        return None
    loc = str(locale).strip().lower().replace("_", "-")
    return _LOCALE_DECIMAL.get(loc) or _LOCALE_DECIMAL.get(loc.split("-")[0])


# ── tokenising ───────────────────────────────────────────────────────────────

_ISO_RE = re.compile(r"(?<![A-Za-z])([A-Z]{3})(?![A-Za-z])")


def _take_currency(t: str):
    """(rest, candidates) with one currency marker removed, or (t, ())."""
    m = _ISO_RE.search(t)
    # "VND-0041", "EUR/12": a code glued to an identifier by - or / is part of
    # the identifier, not a currency
    if m and t[m.end():m.end() + 1] in ("-", "/") and t[m.end() + 1:m.end() + 2].isdigit():
        return t, ()
    if m and m.group(1) in ISO_4217:
        rest = (t[:m.start()] + t[m.end():]).strip()
        # "US$ 10" / "CAD $10": the symbol beside a code is the same currency
        for sym in _SYMBOL_ORDER:
            if sym in rest and not sym.isalpha():
                rest = rest.replace(sym, "", 1).strip()
                break
        return rest, (m.group(1),)
    for sym in _SYMBOL_ORDER:
        i = t.find(sym)
        if i < 0:
            continue
        if sym[0].isalpha():
            # a letter symbol must stand alone: "Rs 10", "10 kr", never "Prs"
            before = t[i - 1] if i else " "
            after = t[i + len(sym)] if i + len(sym) < len(t) else " "
            if before.isalpha() or (after.isalpha() and sym[-1] != "."):
                continue
        return (t[:i] + t[i + len(sym):]).strip(), SYMBOLS[sym]
    return t, ()


def _strip_sign(t: str):
    """(rest, negative, percent, marker) — sign markers removed."""
    t = t.strip()
    neg = False
    marker = ""
    m = re.fullmatch(r"(.*?)[\s]*\b(Dr|DR|dr|Cr|CR|cr)\.?", t)
    if m:
        t, marker = m.group(1).strip(), m.group(2).lower()
        neg = marker == "dr"
    else:
        m = re.fullmatch(r"(Dr|DR|Cr|CR)\.?\s+(.*)", t)
        if m:
            marker, t = m.group(1).lower(), m.group(2).strip()
            neg = marker == "dr"
    pct = t.endswith("%")
    if pct:
        t = t[:-1].strip()
    if t.startswith("(") and t.endswith(")"):
        neg, t = True, t[1:-1].strip()
    if t[:1] in "-−–":
        neg, t = True, t[1:].strip()
    elif t[-1:] in "-−–" and not t.endswith("/-"):
        neg, t = True, t[:-1].strip()
    if t.endswith("/-"):                     # Indian "1,000/-": whole rupees
        t = t[:-2].strip()
        marker = "whole"
    if t.startswith("+"):
        t = t[1:].strip()
    return t, neg, pct, marker


# ── separators ───────────────────────────────────────────────────────────────

def _western_groups(groups) -> bool:
    return (bool(groups) and 1 <= len(groups[0]) <= 3
            and all(len(g) == 3 for g in groups[1:]))


def _lakh_groups(groups) -> bool:
    """1,23,456 / 12,34,56,789: last group 3, the others 2, first 1-2."""
    return (len(groups) >= 3 and len(groups[-1]) == 3 and 1 <= len(groups[0]) <= 2
            and all(len(g) == 2 for g in groups[1:-1]))


def _integer(whole: str, sep: str):
    """(digits, notation) for an integer part grouped with `sep`, or None."""
    if not sep:
        return (whole, "") if whole.isdigit() else None
    groups = whole.split(sep)
    if not all(g.isdigit() for g in groups):
        return None
    if _western_groups(groups):
        return "".join(groups), "grouped"
    if sep == "," and _lakh_groups(groups):
        return "".join(groups), "lakh"
    return None


def _split_body(body: str, decimal_hint: Optional[str]):
    """(whole_digits, frac_digits, decimal_sep, notation, ambiguous) or None."""
    if not body or not body[0].isdigit() or not body[-1].isdigit():
        return None
    if re.search(r"[^0-9" + re.escape(_GROUP_CHARS) + r"]", body):
        return None
    body = re.sub("[" + _SPACES + "]", " ", body).replace("’", "'")
    seps = [c for c in ",.' " if c in body]
    if len(body) > 1 and body[0] == "0" and body[1].isdigit():
        return None                   # "0041", "007": a zero-led code, not an amount
    if not seps:
        return body, "", None, "plain", False
    # A separator that appears after the last digit group of another is the
    # decimal: 1,234.56 / 1.234,56 / 1 234,56 / 1'234.56
    last = max(body.rfind(c) for c in ",.")
    if len([c for c in ",." if c in body]) == 2:
        dec = body[last]
        whole, frac = body[:last], body[last + 1:]
        others = [c for c in ",.' " if c in whole]
        if len(others) != 1 or dec in whole:
            return None
        got = _integer(whole, others[0])
        if got is None or not frac.isdigit():
            return None
        return got[0], frac, dec, _notation(others[0], dec, got[1]), False
    if "'" in body or " " in body:
        grp = "'" if "'" in body else " "
        if ("'" in body and " " in body):
            return None
        dec = next((c for c in ",." if c in body), None)
        if dec:
            whole, _, frac = body.rpartition(dec)
            if dec in whole or not frac.isdigit():
                return None
        else:
            whole, frac = body, ""
        got = _integer(whole, grp)
        if got is None:
            return None
        return got[0], frac, dec, _notation(grp, dec, got[1]), False
    sep = seps[0]                                   # only "," or only "."
    parts = body.split(sep)
    if len(parts) > 2:                              # 1,234,567 / 1.234.567 / 1,23,456
        got = _integer(body, sep)
        if got is None:
            return None
        return got[0], "", None, _notation(sep, None, got[1]), False
    whole, frac = parts
    if len(frac) != 3 or len(whole) > 3 or whole == "0":
        # cannot be a thousands group: a decimal separator
        return whole, frac, sep, _notation("", sep, ""), False
    # "1,234" / "1.234": a group or three decimals. Evidence, or ambiguous.
    if decimal_hint == sep:
        return whole, frac, sep, _notation("", sep, ""), "hint"
    if decimal_hint and decimal_hint != sep:
        return whole + frac, "", None, _notation(sep, None, "grouped"), "hint"
    return whole, frac, sep, "", True


def _notation(group, dec, kind):
    if kind == "lakh":
        return "1,23,456" + (f"{dec}78" if dec else "")
    g = {",": "1,234", ".": "1.234", "'": "1'234", " ": "1 234"}.get(group, "1234")
    return g + (f"{dec}56" if dec else "")


# ── the parser ───────────────────────────────────────────────────────────────

def parse_amount(text, decimal_hint: Optional[str] = None,
                 currency_hint: Optional[str] = None) -> Amount:
    """One amount, read as printed. Never raises. See the module docstring."""
    raw = "" if text is None else str(text)
    s0 = raw.strip()
    t = s0.strip("*#=")                       # cheque protectors ***1,234.56***
    if not t:
        return Amount(raw, reasons=("empty",))
    # A MASK is not a protector: "****7743" (an account's last four) has stars
    # on one side only and no money notation, and is an identifier.
    one_sided = (s0[:1] in "*#") != (s0[-1:] in "*#")
    if one_sided and not re.search(r"[.,]\d{1,3}$|[^\d\s.,'*#=()-]", t):
        return Amount(raw, reasons=("not_a_number",))
    t, neg, pct, m1 = _strip_sign(t)
    t, cands = _take_currency(t)
    t = t.strip("*#= ")                       # "$***150.00"
    t, neg2, pct2, m2 = _strip_sign(t)        # "-$10", "$(10)", "€ 10-"
    whole_only = "whole" in (m1, m2)          # "/-": no fraction exists
    neg, pct = neg or neg2, pct or pct2
    if not cands and currency_hint and currency_hint in ISO_4217:
        cands = (currency_hint,)
    currency = cands[0] if len(cands) == 1 else None
    split = _split_body(t, decimal_hint)
    if split is None:
        return Amount(raw, currency=currency, currencies=cands, negative=neg,
                      percent=pct, reasons=("not_a_number",))
    whole, frac, dec, notation, ambiguous = split
    resolved = ambiguous if ambiguous == "hint" else ""
    ambiguous = ambiguous is True
    minors = {minor_units(c) for c in cands} if cands else set()
    minors.discard(None)
    if ambiguous:
        # Only a 0-decimal currency (JPY, KRW, …: every candidate) settles it:
        # it has no fraction at all, so "¥1,234" is a group. A 2-decimal
        # currency does NOT: unit prices carry three decimals ("$10.125/l").
        if whole_only or (minors and all(m == 0 for m in minors)):
            sep = dec
            return _finish(raw, whole + frac, "", None, _notation(sep, None, "grouped"),
                           currency, cands, neg, pct,
                           "whole_marker" if whole_only else "minor_units")
        return Amount(raw, currency=currency, currencies=cands, negative=neg,
                      percent=pct, ambiguous=True, reasons=(NUMBER_AMBIGUOUS,))
    return _finish(raw, whole, frac, dec, notation, currency, cands, neg, pct,
                   resolved)


def _finish(raw, whole, frac, dec, notation, currency, cands, neg, pct, resolved):
    try:
        v = Decimal(f"{int(whole)}.{frac}" if frac else str(int(whole)))
    except (InvalidOperation, ValueError):
        return Amount(raw, reasons=("not_a_number",))
    reasons = []
    minors = {minor_units(c) for c in cands} - {None}
    if frac and len(minors) == 1 and not pct and len(frac) != next(iter(minors)):
        reasons.append(MINOR_UNITS_MISMATCH)
    return Amount(raw, value=-v if neg else v, currency=currency,
                  currencies=cands, notation=notation, decimal_sep=dec,
                  decimals=len(frac), negative=neg, percent=pct,
                  resolved_by=resolved, reasons=tuple(reasons))


# ── currency consistency (Part 1.5) ──────────────────────────────────────────

CURRENCY_MISMATCH = "currency_mismatch"
CURRENCY_AMBIGUOUS = "currency_ambiguous"


def currency_agreement(texts) -> tuple:
    """("ok" | CURRENCY_MISMATCH | CURRENCY_AMBIGUOUS, sorted currencies).

    Amounts that are summed or compared must be in one currency. Within one
    document the SAME marker names the same currency (a page of "$" amounts is
    consistent whichever dollar it is); an unmarked amount takes the
    document's currency. Two markers that cannot name the same currency
    ("£" and "€", "$" and "€") are a mismatch; two that may or may not ("$"
    and "C$", "¥" and "元") are ambiguous unless one stated code settles it."""
    sets, stated = [], set()
    for t in texts or ():
        a = parse_amount(t)
        if a.ok and a.currencies:
            sets.append(frozenset(a.currencies))
            codes = [c for c in _ISO_RE.findall(str(t)) if c in ISO_4217]
            stated.update(codes)
    distinct = set(sets)
    if len(distinct) <= 1:
        return "ok", sorted(next(iter(distinct))) if distinct else []
    common = frozenset.intersection(*distinct)
    named = sorted(set().union(*distinct))
    if not common:
        return CURRENCY_MISMATCH, named
    # a CODE printed on one of them ("CAD 10.00") settles what "C$" or "$"
    # means beside it; a symbol alone never does
    if len(stated) == 1 and next(iter(stated)) in common:
        return "ok", sorted(stated)
    return CURRENCY_AMBIGUOUS, named


# ── evidence from the document ───────────────────────────────────────────────

def document_hint(texts: Iterable, locale: Optional[str] = None) -> Optional[str]:
    """The decimal separator this document uses, or None.

    The locale wins when it names one. Otherwise every number on the document
    whose style is unambiguous votes (`1,234.56` votes "."; `1.234,56` and
    `12,5` vote ","); the hint is returned only when every vote agrees — a
    document mixing styles resolves nothing."""
    loc = decimal_for_locale(locale)
    if loc:
        return loc
    votes = set()
    for t in texts or ():
        for tok in _number_tokens(str(t or "")):
            a = parse_amount(tok)
            if a.ok and a.decimal_sep:
                votes.add(a.decimal_sep)
    return votes.pop() if len(votes) == 1 else None


_TOKEN = re.compile(r"\d[\d,.'’    ]*\d|\d")


def _number_tokens(text):
    for m in _TOKEN.finditer(text):
        tok = m.group(0).strip()
        # a token spanning words ("2024 1,234.56") is two numbers
        for piece in re.split(r"\s{2,}", tok):
            yield piece


#: The decimal separator of the document being CHECKED — set by
#: `validators.run_checks` for the duration of one record, so every family
#: validator reads amounts with the same evidence without threading it
#: through each call. A ContextVar, because records run on several threads.
from contextvars import ContextVar  # noqa: E402

DOCUMENT_HINT: ContextVar = ContextVar("document_decimal_hint", default=None)

#: The firm's locale (`locale:` in its schema YAML), set by the job worker for
#: the job it runs. Second in line after a template's own locale.
FIRM_LOCALE: ContextVar = ContextVar("firm_locale", default=None)


def money(text, decimal_hint: Optional[str] = None,
          currency_hint: Optional[str] = None) -> Optional[Decimal]:
    """The value, or None when the text is not one amount or is ambiguous.
    With no hint given, the hint of the record being checked is used."""
    hint = decimal_hint if decimal_hint is not None else DOCUMENT_HINT.get()
    a = parse_amount(text, hint, currency_hint)
    return a.value if a.ok and not a.percent else None


__all__ = ["CURRENCY_AMBIGUOUS", "CURRENCY_MISMATCH", "currency_agreement",
           "DOCUMENT_HINT", "FIRM_LOCALE", "Amount", "ISO_4217", "MINOR_UNITS_MISMATCH", "NUMBER_AMBIGUOUS",
           "SYMBOLS", "decimal_for_locale", "document_hint", "minor_units",
           "money", "parse_amount"]
