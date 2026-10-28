"""India: GSTIN (with its official check character), PAN, IFSC."""
from __future__ import annotations

import re

from identifiers import register

_GSTIN = re.compile(r"\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]")
_PAN = re.compile(r"[A-Z]{3}[ABCFGHLJPT][A-Z]\d{4}[A-Z]")
_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

#: GST state / union-territory codes a GSTIN can begin with (GSTN's published
#: list). 25 (Daman & Diu) and 28 (Andhra Pradesh, before division) stay in
#: it: GSTINs carrying them were issued. 97 is "Other Territory" and 99
#: "Centre Jurisdiction". 96 ("Other Country") is a place-of-supply code, not a
#: registration, and everything else (00, 39-95, 98) is unassigned — a GSTIN
#: starting with one is wrong however its check character comes out.
GST_STATE_CODES = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab",
    "04": "Chandigarh", "05": "Uttarakhand", "06": "Haryana", "07": "Delhi",
    "08": "Rajasthan", "09": "Uttar Pradesh", "10": "Bihar", "11": "Sikkim",
    "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur",
    "15": "Mizoram", "16": "Tripura", "17": "Meghalaya", "18": "Assam",
    "19": "West Bengal", "20": "Jharkhand", "21": "Odisha",
    "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat",
    "25": "Daman and Diu", "26": "Dadra and Nagar Haveli and Daman and Diu",
    "27": "Maharashtra", "28": "Andhra Pradesh (before division)",
    "29": "Karnataka", "30": "Goa", "31": "Lakshadweep", "32": "Kerala",
    "33": "Tamil Nadu", "34": "Puducherry", "35": "Andaman and Nicobar Islands",
    "36": "Telangana", "37": "Andhra Pradesh", "38": "Ladakh",
    "97": "Other Territory", "99": "Centre Jurisdiction",
}


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
    if norm[:2] not in GST_STATE_CODES:
        return False, f"{norm[:2]} is not an assigned GST state code"
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
