"""Bank identifiers: IBAN (ISO 13616, mod 97), SWIFT/BIC (ISO 9362), ABA
routing (US), UK sort code. Format and check digits only; no network."""
from __future__ import annotations

import re

from identifiers import register

#: IBAN length by country (ISO 13616 registry)
IBAN_LENGTH = {
    "AD": 24, "AE": 23, "AL": 28, "AT": 20, "AZ": 28, "BA": 20, "BE": 16,
    "BG": 22, "BH": 22, "BR": 29, "CH": 21, "CR": 22, "CY": 28, "CZ": 24,
    "DE": 22, "DK": 18, "DO": 28, "EE": 20, "EG": 29, "ES": 24, "FI": 18,
    "FO": 18, "FR": 27, "GB": 22, "GE": 22, "GI": 23, "GL": 18, "GR": 27,
    "GT": 28, "HR": 21, "HU": 28, "IE": 22, "IL": 23, "IQ": 23, "IS": 26,
    "IT": 27, "JO": 30, "KW": 30, "KZ": 20, "LB": 28, "LI": 21, "LT": 20,
    "LU": 20, "LV": 21, "MC": 27, "MD": 24, "ME": 22, "MK": 19, "MR": 27,
    "MT": 31, "MU": 30, "NL": 18, "NO": 15, "PK": 24, "PL": 28, "PS": 29,
    "PT": 25, "QA": 29, "RO": 24, "RS": 22, "SA": 24, "SC": 31, "SE": 24,
    "SI": 19, "SK": 24, "SM": 27, "TN": 24, "TR": 26, "UA": 29, "VG": 24,
    "XK": 20,
}


def iban_mod97(norm: str) -> int:
    s = norm[4:] + norm[:4]
    return int("".join(str(int(c, 36)) for c in s)) % 97


@register("iban", "iban_invalid")
def iban(norm):
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", norm):
        return False, "not shaped like an IBAN"
    want = IBAN_LENGTH.get(norm[:2])
    if want and len(norm) != want:
        return False, f"{norm[:2]} IBANs have {want} characters, this has {len(norm)}"
    if iban_mod97(norm) != 1:
        return False, "the check digits do not match (mod 97)"
    return True, ""


#: ISO 3166-1 alpha-2
COUNTRIES = frozenset(
    "AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ "
    "BL BM BN BO BQ BR BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR "
    "CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR "
    "GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU "
    "ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW KY KZ "
    "LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ "
    "MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF "
    "PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI "
    "SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR "
    "TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS XK YE YT ZA ZM ZW".split())


@register("swift", "swift_invalid")
def swift(norm):
    if not re.fullmatch(r"[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}([A-Z0-9]{3})?", norm):
        return False, "a BIC is 4 letters, a country, 2 characters, optionally 3 more"
    if norm[4:6] not in COUNTRIES:
        return False, f"{norm[4:6]} is not a country code"
    return True, ""


@register("bic", "swift_invalid")
def bic(norm):
    return swift(norm)


@register("aba", "checksum_failed")
def aba(norm):
    from micr import aba_is_valid
    if not re.fullmatch(r"\d{9}", norm):
        return False, "an ABA routing number is nine digits"
    return (True, "") if aba_is_valid(norm) else (False, "fails the ABA check digit")


@register("uk_sort_code", "sort_code_invalid")
def uk_sort_code(norm):
    return (True, "") if re.fullmatch(r"\d{6}", norm) else \
        (False, "a sort code is six digits (12-34-56)")
