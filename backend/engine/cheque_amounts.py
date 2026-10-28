"""Cheque amount cross-check: does the written amount agree with the digits?

Pure functions, standard library only (Decimal). No I/O, no engine imports, so it
can be adopted anywhere in backend/engine.

Principle: review is the backstop, not the quality mechanism. This
module never *raises* confidence on its own. It reports one of three statuses:

  "match"       numeric and written amounts parse and agree exactly
  "mismatch"    both parse and DISAGREE: at least one of the two is wrong
  "unreadable"  one side (or both) could not be parsed with certainty

A caller should treat "mismatch" as a reason to mark BOTH values low (reason code
"amount_mismatch"), "unreadable" as a reason to keep the value flagged
("amount_unreadable"), and "match" as supporting evidence only.
Anything we are not certain about is "unreadable", never guessed.

Scope (Part 1.2): English number words in any common currency — dollars and
cents, pounds and pence, euros and cents, rupees and paise, dirhams and fils,
yen (no subunit), francs, riyals, dinars — on the short scale (thousand,
million, billion), the Indian scale (lakh, crore) and, on request
(`long_scale=True`), the long scale (milliard 10^9, billion 10^12). The two
systems never mix in one amount ("one million two lakh" is unreadable).
Figures in any locale go through the shared parser (engine/amounts.py). Words
in another language are unreadable, never translated.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import List, Optional

_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_SCALES = {"thousand": 1_000, "million": 1_000_000, "billion": 1_000_000_000,
           "milliard": 1_000_000_000}
_LONG_SCALES = {"thousand": 1_000, "million": 1_000_000,
                "milliard": 1_000_000_000, "billion": 1_000_000_000_000}
#: the Indian system: lakh 10^5, crore 10^7 (a crore's multiplier may itself
#: be any number below a crore: "one hundred crore", "five lakh crore")
_INDIAN = {"thousand": 1_000, "lakh": 100_000, "lakhs": 100_000, "lac": 100_000,
           "lacs": 100_000}
_CRORE = {"crore", "crores"}
#: main-unit and subunit names (both are filler to the number itself)
_MAIN_UNITS = {"dollars", "dollar", "pounds", "pound", "sterling", "euros",
               "euro", "rupees", "rupee", "rs", "dirhams", "dirham", "yen",
               "francs", "franc", "riyals", "riyal", "rials", "rial", "dinars",
               "dinar", "usd", "gbp", "eur", "inr", "aed", "jpy", "chf", "sar",
               "cad", "aud", "sgd"}
_FILLER = {"only", "and", "us", "exactly", "the", "of"} | _MAIN_UNITS
_CENT_WORDS = {"cent", "cents", "penny", "pence", "paise", "paisa", "fils",
               "centime", "centimes", "halala", "halalas", "rappen"}

#: the subunit words each main-unit word may be followed by (Recheck R3): a
#: cent is not a hundredth of a rupee, so "ten rupees fifty cents" is
#: unreadable (`unit_mix`), never 10.50. Yen has no subunit in use.
_CENTS = frozenset({"cent", "cents"})
_PENCE = frozenset({"penny", "pence"})
_PAISE = frozenset({"paise", "paisa"})
_FILS = frozenset({"fils"})
_HALALA = frozenset({"halala", "halalas"})
_SWISS = frozenset({"centime", "centimes", "rappen"})
UNIT_FAMILIES = {
    **{w: _CENTS for w in ("dollars", "dollar", "usd", "cad", "aud", "sgd",
                           "euros", "euro", "eur")},
    **{w: _PENCE for w in ("pounds", "pound", "sterling", "gbp")},
    **{w: _PAISE for w in ("rupees", "rupee", "rs", "inr")},
    **{w: _FILS for w in ("dirhams", "dirham", "aed", "dinars", "dinar",
                          "rials", "rial")},
    **{w: _HALALA for w in ("riyals", "riyal", "sar")},
    **{w: _SWISS for w in ("francs", "franc", "chf")},
    "yen": frozenset(), "jpy": frozenset(),
}


def _unit_mix(tokens) -> bool:
    """True when a subunit word does not belong to the main unit named."""
    mains = [t for t in tokens if t in _MAIN_UNITS]
    subs = [t for t in tokens if t in _CENT_WORDS]
    return bool(mains and subs) and any(
        s not in UNIT_FAMILIES.get(m, frozenset()) for m in mains for s in subs)


@dataclass
class ParsedAmount:
    value: Optional[Decimal]
    reasons: List[str] = field(default_factory=list)  # why value is None, or notes


@dataclass
class AmountCheck:
    status: str  # "match" | "mismatch" | "unreadable"
    numeric: Optional[Decimal]
    words: Optional[Decimal]
    reasons: List[str] = field(default_factory=list)


def parse_numeric_amount(text: str, decimal_hint: Optional[str] = None) -> ParsedAmount:
    """The courtesy amount as a Decimal, read by the shared parser
    (engine/amounts.py) in any locale: '$1,234.56', '1.234,56 €', '₹1,23,456.00'.

    Refused (value None, with a reason) rather than guessed: a negative or
    bracketed amount (a cheque cannot be drawn for one), letters or several
    amounts, an ambiguous notation ('1,234' with nothing to resolve it — the
    amount in words may: `compare_amounts`), and a fraction other than none or
    the currency's own minor units (two when the currency is unknown).
    """
    from amounts import DOCUMENT_HINT, parse_amount, minor_units
    if text is None or not str(text).strip():
        return ParsedAmount(None, ["empty"])
    hint = decimal_hint if decimal_hint is not None else DOCUMENT_HINT.get()
    a = parse_amount(text, hint)
    if a.negative:
        return ParsedAmount(None, ["negative_or_bracketed"])
    if a.ambiguous:
        return ParsedAmount(None, ["ambiguous_notation"])
    if not a.ok or a.percent:
        return ParsedAmount(None, ["not_a_plain_number"])
    allowed = {0, minor_units(a.currency) if a.currency else 2}
    if a.currencies and not a.currency:
        allowed |= {minor_units(c) for c in a.currencies}
    if a.decimals not in allowed:
        return ParsedAmount(None, ["unexpected_decimal_places"])
    return ParsedAmount(a.value)


def _group_value(tokens: List[str], only_group: bool) -> Optional[int]:
    """Value (0..999) of a group of number words, or None if not well formed.

    Accepted shapes: [d hundred] [tens [unit] | teen | unit] with d in 1..9,
    the colloquial '<10..19> hundred' ('twelve hundred'), and 'zero' on its own.
    Anything else (for example 'one two three', 'five twenty', 'hundred hundred')
    is rejected rather than guessed.
    """
    if not tokens:
        return None
    toks = list(tokens)
    n = 0
    if toks == ["zero"]:
        return 0 if only_group else None
    if len(toks) >= 2 and toks[1] == "hundred":
        first = _UNITS.get(toks[0])
        if first is None or first == 0 or first > 19:
            return None
        n = first * 100  # also the colloquial '<10..19> hundred' ('twelve hundred')
        toks = toks[2:]
    elif "hundred" in toks:
        return None
    if not toks:
        return n
    if len(toks) == 1:
        t = toks[0]
        if t in _UNITS and _UNITS[t] != 0:
            return n + _UNITS[t]
        if t in _TENS:
            return n + _TENS[t]
        return None
    if len(toks) == 2 and toks[0] in _TENS and toks[1] in _UNITS and 1 <= _UNITS[toks[1]] <= 9:
        return n + _TENS[toks[0]] + _UNITS[toks[1]]
    return None


def _words_to_int(tokens: List[str], long_scale: bool = False) -> Optional[int]:
    """Convert number words (no cents, no filler) to an int, or None if unsure.

    Scales must appear at most once each and in strictly descending order; each
    scale needs a well formed group before it. Indian (lakh, crore) and
    international (million, billion) scales never mix in one amount.
    """
    if not tokens:
        return None
    indian = any(t in _INDIAN or t in _CRORE for t in tokens if t != "thousand")
    western = any(t in ("million", "billion", "milliard") for t in tokens)
    if indian and western:
        return None
    if indian:
        return _indian_to_int(tokens)
    return _scaled_to_int(tokens, _LONG_SCALES if long_scale else _SCALES)


def _indian_to_int(tokens: List[str]) -> Optional[int]:
    """[N crore] [lakh-part]: the multiplier of a crore is itself any number
    below a crore; what follows the last crore is below a crore."""
    if any(t in _CRORE for t in tokens):
        i = max(k for k, t in enumerate(tokens) if t in _CRORE)
        left, right = tokens[:i], tokens[i + 1:]
        mult = _scaled_to_int(left, _INDIAN) if left else None   # no crore of crores
        if not mult:
            return None
        rest = _scaled_to_int(right, _INDIAN) if right else 0
        if rest is None or rest >= 10_000_000:
            return None
        return mult * 10_000_000 + rest
    return _scaled_to_int(tokens, _INDIAN)


def _scaled_to_int(tokens: List[str], scales: dict) -> Optional[int]:
    if not tokens:
        return None
    total = 0
    group: List[str] = []
    last_scale: Optional[int] = None
    saw_scale = False
    for tok in tokens:
        if tok in scales:
            scale = scales[tok]
            if last_scale is not None and scale >= last_scale:
                return None
            val = _group_value(group, only_group=False)
            if val is None or val == 0:
                return None
            total += val * scale
            last_scale = scale
            saw_scale = True
            group = []
        else:
            group.append(tok)
    if group:
        val = _group_value(group, only_group=not saw_scale)
        if val is None:
            return None
        total += val
    elif not saw_scale:
        return None
    return total


def _is_number_word(tok: str) -> bool:
    return (tok in _UNITS or tok in _TENS or tok == "hundred" or tok in _SCALES
            or tok in _LONG_SCALES or tok in _INDIAN or tok in _CRORE
            or tok.isdigit())


def _unit_order_problem(tokens: List[str]) -> bool:
    """True when the subunit is not the LAST part of the amount.

    Accepted: '<n> dollars [and] <n> cents', 'dollars <n> and <n> cents',
    '<n> rupees and paise <n>'. Refused: any main-unit word after the subunit
    word ('fifty cents one dollar' is not 50.01), more than one subunit word,
    and a subunit word with a number on BOTH sides of it ('fifty cents one'):
    which number it counts is not knowable, so it is unreadable, never guessed.
    """
    subs = [i for i, tok in enumerate(tokens) if tok in _CENT_WORDS]
    if not subs:
        return False
    if len(subs) > 1:
        return True
    i = subs[0]
    if any(tok in _MAIN_UNITS for tok in tokens[i + 1:]):
        return True
    after = [x for x in tokens[i + 1:] if x not in _FILLER]
    if after and i > 0 and _is_number_word(tokens[i - 1]):
        return True
    return False


_FRACTION_RE = re.compile(r"(?:^|\s)(xx|no|zero|\d{1,2})\s*/\s*100(?:ths?)?(?=\s|$)")


def parse_words_amount(text: str, long_scale: bool = False) -> ParsedAmount:
    """Parse 'One thousand two hundred thirty-four and 56/100 dollars',
    'Rupees One Lakh Twenty Thousand and Paise Fifty Only', etc.

    Understood subunit forms: '56/100', 'xx/100', 'no/100', 'and fifty-six
    cents' (pence, paise, fils, …), and the subunit word BEFORE its number
    ('and paise fifty').
    Any unknown token, missing dollar part with no cents, or other fraction makes
    the result unreadable (value=None).
    """
    if text is None:
        return ParsedAmount(None, ["empty"])
    t = str(text).lower().strip()
    if not t:
        return ParsedAmount(None, ["empty"])
    t = t.replace("-", " ").replace(",", " ").replace("*", " ")
    t = re.sub(r"[^a-z0-9/\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()

    cents: Optional[int] = None
    m = _FRACTION_RE.search(t)
    if m:
        raw = m.group(1)
        cents = 0 if raw in ("xx", "no", "zero") else int(raw)
        # The fraction closes the amount: '56/100 one dollar' is not 1.56.
        if any(_is_number_word(x) for x in t[m.end():].split()):
            return ParsedAmount(None, ["unit_order"])
        t = (t[:m.start()] + " " + t[m.end():]).strip()
    elif re.search(r"/", t):
        return ParsedAmount(None, ["unsupported_fraction"])

    tokens = t.split()
    if _unit_mix(tokens):
        return ParsedAmount(None, ["unit_mix"])
    if _unit_order_problem(tokens):
        return ParsedAmount(None, ["unit_order"])
    numberish = set(_UNITS) | set(_TENS) | {"hundred"}
    if cents is None and any(tok in _CENT_WORDS for tok in tokens):
        idx = max(i for i, tok in enumerate(tokens) if tok in _CENT_WORDS)
        after = [x for x in tokens[idx + 1:] if x not in _FILLER]
        if after and all(x in numberish for x in after):
            # "... and paise fifty only": the subunit word comes first
            c = _words_to_int(after)
            if c is None or c > 99:
                return ParsedAmount(None, ["unreadable_cents"])
            cents = c
            tokens = tokens[:idx]
            while tokens and tokens[-1] == "and":
                tokens = tokens[:-1]
    if cents is None and any(tok in _CENT_WORDS for tok in tokens):
        idx = max(i for i, tok in enumerate(tokens) if tok in _CENT_WORDS)
        before = tokens[:idx]
        # dollars part ends at the last 'dollar(s)' token if present
        split_at = None
        for i, tok in enumerate(before):
            if tok in _MAIN_UNITS:
                split_at = i
        if split_at is None:
            # find the 'and' that separates dollars from cents
            ands = [i for i, tok in enumerate(before) if tok == "and"]
            split_at = ands[-1] if ands else None
        if split_at is None:
            return ParsedAmount(None, ["cannot_split_dollars_and_cents"])
        dollars_tokens = before[:split_at]
        cents_tokens = [x for x in before[split_at + 1:] if x != "and"]
        cents_words = [x for x in cents_tokens if x not in _FILLER]
        if cents_words in (["no"], ["zero"]):
            c = 0
        elif len(cents_words) == 1 and cents_words[0].isdigit() and len(cents_words[0]) <= 2:
            c = int(cents_words[0])
        else:
            c = _words_to_int(cents_words)
        if c is None or c > 99:
            return ParsedAmount(None, ["unreadable_cents"])
        cents = c
        tokens = dollars_tokens
    tokens = [tok for tok in tokens if tok not in _FILLER and tok not in _CENT_WORDS]
    if any(tok.isdigit() for tok in tokens):
        return ParsedAmount(None, ["digits_in_words"])
    if not tokens:
        # e.g. "56/100" alone is not a full written amount
        return ParsedAmount(None, ["no_dollar_words"])
    dollars = _words_to_int(tokens, long_scale)
    if dollars is None:
        return ParsedAmount(None, ["unreadable_words"])
    if cents is None:
        cents = 0
    if not 0 <= cents <= 99:
        return ParsedAmount(None, ["cents_out_of_range"])
    return ParsedAmount(Decimal(f"{dollars}.{cents:02d}"))


def compare_amounts(numeric_text: Optional[str], words_text: Optional[str]) -> AmountCheck:
    """Cross-check the numeric (courtesy) amount against the written (legal) amount."""
    n = parse_numeric_amount(numeric_text) if numeric_text is not None else ParsedAmount(None, ["missing"])
    w = parse_words_amount(words_text) if words_text is not None else ParsedAmount(None, ["missing"])
    if n.value is None and n.reasons == ["ambiguous_notation"] and w.value is not None:
        # THE WORDS ARE EVIDENCE. "1,234" is 1234 or 1.234; the legal amount
        # says which. Exactly one reading must agree, else nothing is decided.
        fits = [r.value for r in (parse_numeric_amount(numeric_text, "."),
                                  parse_numeric_amount(numeric_text, ","))
                if r.value is not None and r.value == w.value]
        if len(fits) == 1:
            return AmountCheck("match", fits[0], w.value,
                               ["numeric:notation_resolved_by_words"])
    reasons = [f"numeric:{r}" for r in n.reasons] + [f"words:{r}" for r in w.reasons]
    if n.value is None or w.value is None:
        return AmountCheck("unreadable", n.value, w.value, reasons)
    if n.value == w.value:
        return AmountCheck("match", n.value, w.value, [])
    return AmountCheck("mismatch", n.value, w.value, ["amounts_differ"])
