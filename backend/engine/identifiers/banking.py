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
    # added to the registry since the table was first written
    "BI": 27, "BY": 28, "DJ": 27, "FK": 18, "HN": 28, "LC": 32, "LY": 25,
    "MN": 20, "NI": 28, "OM": 23, "RU": 33, "SD": 18, "SO": 23, "ST": 25,
    "SV": 28, "TL": 23, "VA": 22, "YE": 30,
}


#: the account part (BBAN) of each registry country, in the SWIFT IBAN
#: registry's notation: n = digits, a = upper-case letters, c = either
#: (Recheck R4). Mod 97 alone passes a letter typed for a digit about one time
#: in 97; the shape does not. Every registry country is listed — a test holds
#: each format's length to IBAN_LENGTH — so none is checksum-only.
BBAN_FORMAT = {
    "AD": "4n4n12c", "AE": "3n16n", "AL": "8n16c", "AT": "5n11n", "AZ": "4a20c",
    "BA": "3n3n8n2n", "BE": "3n7n2n", "BG": "4a4n2n8c", "BH": "4a14c",
    "BI": "5n5n11n2n", "BR": "8n5n10n1a1c", "BY": "4c4n16c", "CH": "5n12c",
    "CR": "4n14n", "CY": "3n5n16c", "CZ": "4n6n10n", "DE": "8n10n",
    "DJ": "5n5n11n2n", "DK": "4n9n1n", "DO": "4c20n", "EE": "2n2n11n1n",
    "EG": "4n4n17n", "ES": "4n4n1n1n10n", "FI": "3n11n", "FK": "2a12n",
    "FO": "4n9n1n", "FR": "5n5n11c2n", "GB": "4a6n8n", "GE": "2a16n",
    "GI": "4a15c", "GL": "4n9n1n", "GR": "3n4n16c", "GT": "4c20c",
    "HN": "4a20n", "HR": "7n10n", "HU": "3n4n1n15n1n", "IE": "4a6n8n",
    "IL": "3n3n13n", "IQ": "4a3n12n", "IS": "4n2n6n10n", "IT": "1a5n5n12c",
    "JO": "4a4n18c", "KW": "4a22c", "KZ": "3n13c", "LB": "4n20c",
    "LC": "4a24c", "LI": "5n12c", "LT": "5n11n", "LU": "3n13c", "LV": "4a13c",
    "LY": "3n3n15n", "MC": "5n5n11c2n", "MD": "2c18c", "ME": "3n13n2n",
    "MK": "3n10c2n", "MN": "4n12n", "MR": "5n5n11n2n", "MT": "4a5n18c",
    "MU": "4a2n2n12n3n3a", "NI": "4a20n", "NL": "4a10n", "NO": "4n6n1n",
    "OM": "3n16c", "PK": "4a16c", "PL": "8n16n", "PS": "4a21c",
    "PT": "4n4n11n2n", "QA": "4a21c", "RO": "4a16c", "RS": "3n13n2n",
    "RU": "9n5n15c", "SA": "2n18c", "SC": "4a2n2n16n3a", "SD": "2n12n",
    "SE": "3n16n1n", "SI": "5n8n2n", "SK": "4n6n10n", "SM": "1a5n5n12c",
    "SO": "4n3n12n", "ST": "4n4n11n2n", "SV": "4a20n", "TL": "3n14n2n",
    "TN": "2n3n13n2n", "TR": "5n1n16c", "UA": "6n19c", "VA": "3n15n",
    "VG": "4a16n", "XK": "4n10n2n", "YE": "4a4n18c",
}
_BBAN_CLASS = {"n": "[0-9]", "a": "[A-Z]", "c": "[A-Z0-9]"}


def _bban_re(fmt):
    return re.compile("".join(f"{_BBAN_CLASS[k]}{{{n}}}"
                              for n, k in re.findall(r"(\d+)([nac])", fmt)))


_BBAN_RE = {cc: _bban_re(f) for cc, f in BBAN_FORMAT.items()}


def iban_mod97(norm: str) -> int:
    s = norm[4:] + norm[:4]
    return int("".join(str(int(c, 36)) for c in s)) % 97


@register("iban", "iban_invalid")
def iban(norm):
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", norm):
        return False, "not shaped like an IBAN"
    want = IBAN_LENGTH.get(norm[:2])
    if want is None:
        # A country that issues no IBANs: the mod-97 check alone passes one
        # string in 97, so it is no evidence (Review-3 F6).
        return False, f"{norm[:2]} is not a country in the IBAN registry"
    if len(norm) != want:
        return False, f"{norm[:2]} IBANs have {want} characters, this has {len(norm)}"
    if iban_mod97(norm) != 1:
        return False, "the check digits do not match (mod 97)"
    shape = _BBAN_RE.get(norm[:2])
    if shape is not None and not shape.fullmatch(norm[4:]):
        return False, (f"the account part is not in the {norm[:2]} format "
                       f"({BBAN_FORMAT[norm[:2]]}: n digit, a letter, c either)")
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
