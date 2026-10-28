"""Tax identifiers by FORMAT: EU VAT numbers (and GB / XI), UAE TRN, US EIN.
Format only — no checksum is claimed where none is implemented."""
from __future__ import annotations

import re

from identifiers import register

#: country prefix -> body pattern (the VIES formats)
EU_VAT = {
    "AT": r"U\d{8}", "BE": r"[01]\d{9}", "BG": r"\d{9,10}", "CY": r"\d{8}[A-Z]",
    "CZ": r"\d{8,10}", "DE": r"\d{9}", "DK": r"\d{8}", "EE": r"\d{9}",
    "EL": r"\d{9}", "ES": r"[A-Z0-9]\d{7}[A-Z0-9]", "FI": r"\d{8}",
    "FR": r"[A-HJ-NP-Z0-9]{2}\d{9}", "HR": r"\d{11}", "HU": r"\d{8}",
    "IE": r"\d{7}[A-W][A-I]?|\d[A-Z+*]\d{5}[A-W]", "IT": r"\d{11}",
    "LT": r"\d{9}|\d{12}", "LU": r"\d{8}", "LV": r"\d{11}", "MT": r"\d{8}",
    "NL": r"\d{9}B\d{2}", "PL": r"\d{10}", "PT": r"\d{9}", "RO": r"\d{2,10}",
    "SE": r"\d{12}", "SI": r"\d{8}", "SK": r"\d{10}",
    # GD000-GD499 are government departments, HA500-HA999 health
    # authorities; the other halves of each range are not issued.
    "XI": r"\d{9}|\d{12}|GD[0-4]\d{2}|HA[5-9]\d{2}",
    "GB": r"\d{9}|\d{12}|GD[0-4]\d{2}|HA[5-9]\d{2}",
}


def uk_vat_check_ok(body: str) -> bool:
    """HMRC's check on a 9-digit UK VAT number (the first 9 of a 12-digit
    branch number): weights 8..2 over the first seven digits plus the two
    check digits as a number. Mod 97 must be 0; from 100 0000 upwards the
    "97-55" scheme (+55, so 42 mod 97) is also issued, and python-stdnum
    accepts 55 there too. Seven leading zeros is no number (Recheck R4)."""
    d = body[:9]
    if int(d[:7]) == 0:
        return False
    total = sum(w * int(c) for w, c in zip((8, 7, 6, 5, 4, 3, 2), d[:7])) + int(d[7:9])
    return total % 97 in ((0, 42, 55) if int(d[:3]) >= 100 else (0,))


@register("vat", "vat_format_invalid")
def vat(norm):
    cc, body = norm[:2], norm[2:]
    if cc == "GR":
        cc = "EL"
    pat = EU_VAT.get(cc)
    if not pat:
        return False, f"{norm[:2]!r} is not an EU (or GB) VAT prefix"
    if not re.fullmatch(pat, body):
        return False, f"not the {cc} VAT number format"
    if cc in ("GB", "XI") and body.isdigit() and not uk_vat_check_ok(body):
        return False, "the UK VAT check digits do not match"
    return True, ""


@register("trn", "trn_invalid")
def uae_trn(norm):
    return (True, "") if re.fullmatch(r"\d{15}", norm) else \
        (False, "a UAE TRN is 15 digits")


#: IRS prefixes never assigned
_EIN_BAD = {"00", "07", "08", "09", "17", "18", "19", "28", "29", "49", "69",
            "70", "78", "79", "89", "96", "97"}


@register("ein", "ein_invalid")
def us_ein(norm):
    if not re.fullmatch(r"\d{9}", norm):
        return False, "an EIN is nine digits (12-3456789)"
    if norm[:2] in _EIN_BAD:
        return False, f"{norm[:2]} is not an assigned EIN prefix"
    return True, ""
