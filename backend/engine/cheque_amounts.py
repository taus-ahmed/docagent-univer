"""Cheque amount cross-check: does the written amount agree with the digits?

Pure functions, standard library only (Decimal). No I/O, no engine imports, so it
can be adopted anywhere in backend/engine.

Principle (Tauseef): review is the backstop, not the quality mechanism. This
module never *raises* confidence on its own. It reports one of three statuses:

  "match"       numeric and written amounts parse and agree exactly
  "mismatch"    both parse and DISAGREE: at least one of the two is wrong
  "unreadable"  one side (or both) could not be parsed with certainty

A caller should treat "mismatch" as a reason to mark BOTH values low (reason code
"amount_mismatch"), "unreadable" as a reason to keep the value flagged
("amount_unverified_cross_check"), and "match" as supporting evidence only.
Anything we are not certain about is "unreadable", never guessed.

Scope: English words, US/Canadian style (dollars and cents). European number
notation (1.234,56) is deliberately reported as "unreadable" (roadmap item C11).
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
_SCALES = {"thousand": 1_000, "million": 1_000_000, "billion": 1_000_000_000}
_FILLER = {"only", "and", "dollars", "dollar", "usd", "us", "exactly", "the", "of"}
_CENT_WORDS = {"cent", "cents"}


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


def parse_numeric_amount(text: str) -> ParsedAmount:
    """Parse '$1,234.56', '1234.56', '$ 1,234.50', '1,234' into a Decimal.

    Returns value=None (with a reason) when the notation is ambiguous or not a
    plain amount: European 1.234,56, negative amounts, letters, several amounts.
    """
    if text is None:
        return ParsedAmount(None, ["empty"])
    t = str(text).strip()
    if not t:
        return ParsedAmount(None, ["empty"])
    t = t.replace("$", "").replace("USD", "").replace("usd", "")
    t = re.sub(r"\s+", "", t)
    t = t.strip("*#=")  # check protectors such as ***1,234.56*** or =1,234.56= (never a minus sign)
    if t.startswith("(") or t.startswith("-") or t.endswith("-"):
        return ParsedAmount(None, ["negative_or_bracketed"])
    if not re.fullmatch(r"[0-9][0-9,\.]*", t):
        return ParsedAmount(None, ["not_a_plain_number"])
    if "," in t and "." in t and t.rfind(",") > t.rfind("."):
        return ParsedAmount(None, ["ambiguous_notation"])  # 1.234,56
    if t.count(".") > 1:
        return ParsedAmount(None, ["ambiguous_notation"])  # 1.234.567
    if "." in t:
        whole, _, frac = t.partition(".")
        if len(frac) != 2:
            return ParsedAmount(None, ["unexpected_decimal_places"])
        if "," in frac:
            return ParsedAmount(None, ["ambiguous_notation"])
    else:
        whole, frac = t, "00"
    if "," in whole:
        groups = whole.split(",")
        if not groups[0] or len(groups[0]) > 3 or any(len(g) != 3 for g in groups[1:]):
            return ParsedAmount(None, ["ambiguous_notation"])
        whole = "".join(groups)
    if not whole.isdigit() or not frac.isdigit():
        return ParsedAmount(None, ["not_a_plain_number"])
    return ParsedAmount(Decimal(f"{int(whole)}.{frac}"))


def _words_to_int(tokens: List[str]) -> Optional[int]:
    """Convert number words (no cents, no filler) to an int, or None if unsure."""
    if not tokens:
        return None
    total = 0
    current = 0
    seen = False
    for tok in tokens:
        if tok in _UNITS:
            current += _UNITS[tok]
            seen = True
        elif tok in _TENS:
            current += _TENS[tok]
            seen = True
        elif tok == "hundred":
            if current == 0:
                return None
            current *= 100
            seen = True
        elif tok in _SCALES:
            if current == 0:
                return None
            total += current * _SCALES[tok]
            current = 0
            seen = True
        else:
            return None  # unknown token: never guess
    return total + current if seen else None


_FRACTION_RE = re.compile(r"(?:^|\s)(xx|no|zero|\d{1,2})\s*/\s*100(?:ths?)?(?=\s|$)")


def parse_words_amount(text: str) -> ParsedAmount:
    """Parse 'One thousand two hundred thirty-four and 56/100 dollars' etc.

    Understood cents forms: '56/100', 'xx/100', 'no/100', 'and fifty-six cents'.
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
        t = (t[:m.start()] + " " + t[m.end():]).strip()
    elif re.search(r"/", t):
        return ParsedAmount(None, ["unsupported_fraction"])

    tokens = t.split()
    if cents is None and any(tok in _CENT_WORDS for tok in tokens):
        idx = max(i for i, tok in enumerate(tokens) if tok in _CENT_WORDS)
        before = tokens[:idx]
        # dollars part ends at the last 'dollar(s)' token if present
        split_at = None
        for i, tok in enumerate(before):
            if tok in ("dollar", "dollars"):
                split_at = i
        if split_at is None:
            # find the 'and' that separates dollars from cents
            ands = [i for i, tok in enumerate(before) if tok == "and"]
            split_at = ands[-1] if ands else None
        if split_at is None:
            return ParsedAmount(None, ["cannot_split_dollars_and_cents"])
        dollars_tokens = before[:split_at]
        cents_tokens = [x for x in before[split_at + 1:] if x != "and"]
        c = _words_to_int([x for x in cents_tokens if x not in _FILLER])
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
    dollars = _words_to_int(tokens)
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
    reasons = [f"numeric:{r}" for r in n.reasons] + [f"words:{r}" for r in w.reasons]
    if n.value is None or w.value is None:
        return AmountCheck("unreadable", n.value, w.value, reasons)
    if n.value == w.value:
        return AmountCheck("match", n.value, w.value, [])
    return AmountCheck("mismatch", n.value, w.value, ["amounts_differ"])
