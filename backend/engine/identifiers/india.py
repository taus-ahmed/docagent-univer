"""India: GSTIN (with its official check character), PAN, IFSC."""
from __future__ import annotations

import re

from identifiers import register

_GSTIN = re.compile(r"\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]")
_PAN = re.compile(r"[A-Z]{3}[ABCFGHLJPT][A-Z]\d{4}[A-Z]")
_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def gstin_check_char(first14: str) -> str:
    """The GSTN check character: base-36 values weighted 1, 2, 1, 2, …; each
    product contributes its quotient plus remainder by 36."""
    total = 0
    for i, ch in enumerate(first14):
        p = _CHARS.index(ch) * (2 if i % 2 else 1)
        total += p // 36 + p % 36
    return _CHARS[(36 - total % 36) % 36]


@register("gstin", "gstin_invalid")
def gstin(norm):
    if not _GSTIN.fullmatch(norm):
        return False, "not shaped like a GSTIN (2 digits, a PAN, entity, Z, check)"
    if not 1 <= int(norm[:2]) <= 99:
        return False, "the state code is not 01-99"
    if not _PAN.fullmatch(norm[2:12]):
        return False, "characters 3-12 are not a PAN"
    if gstin_check_char(norm[:14]) != norm[14]:
        return False, "the check character does not match"
    return True, ""


@register("pan", "pan_invalid")
def pan(norm):
    return (True, "") if _PAN.fullmatch(norm) else \
        (False, "a PAN is 5 letters (the 4th the holder type), 4 digits, 1 letter")


@register("ifsc", "ifsc_invalid")
def ifsc(norm):
    return (True, "") if re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", norm) else \
        (False, "an IFSC is 4 letters, a zero, then 6 letters or digits")
