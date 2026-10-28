"""Review-3 F6: an identifier from an UNASSIGNED range is invalid, however its
check digits come out.

A GSTIN beginning `50` passed: the plug-in tested the state code as 01-99 and
then the check character, which is computed over whatever is there. The same
class of gap — a closed published list checked as an open numeric range, or
not at all — was looked for in every plug-in:

  gstin   state code      FIXED: GSTN's list (01-38, 97, 99)
  iban    country         FIXED: a country outside the IBAN registry passed
                          on mod 97 alone, which one string in 97 does
  vat     GB/XI GD/HA     FIXED: GD500-999 and HA000-499 are not issued
  vat     country prefix  already closed (the 27 EU states, EL for GR, XI, GB)
  pan     entity letter   already closed (A B C F G H J L P T)
  swift   country         already closed (ISO 3166-1)
  ein     prefix          already closed (IRS unassigned prefixes refused)
  ifsc    bank code       FORMAT ONLY, on purpose: the RBI's ~1,300 bank codes
                          change monthly, and a stale copy refuses real banks
  trn     (UAE)           FORMAT ONLY: the FTA publishes no checksum or ranges
"""
import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

from identifiers import validate  # noqa: E402
from identifiers.banking import IBAN_LENGTH  # noqa: E402
from identifiers.india import GST_STATE_CODES, gstin_check_char  # noqa: E402

PAN = "AABCU9603R"


def gstin(state, pan=PAN, entity="1"):
    first = f"{state}{pan}{entity}Z"
    return first + gstin_check_char(first)


@pytest.mark.parametrize("state", sorted(GST_STATE_CODES))
def test_every_assigned_state_code_is_valid(state):
    v = validate("gstin", gstin(state))
    assert v.ok, (state, v)


@pytest.mark.parametrize("state", ["00", "39", "40", "50", "77", "95", "96", "98"])
def test_an_unassigned_state_code_is_invalid_even_with_a_good_check_character(state):
    v = validate("gstin", gstin(state))
    assert v.ok is False and v.reason == "gstin_invalid" and "state code" in v.note, v


def test_the_published_list_is_exactly_01_to_38_97_99():
    assert set(GST_STATE_CODES) == {f"{i:02d}" for i in range(1, 39)} | {"97", "99"}


def test_a_known_good_gstin_still_passes():
    assert validate("gstin", "27AAPFU0939F1ZV").ok


def _iban(cc, length):
    """Good mod-97 check digits for `cc`, with an account part in the
    country's own format (Recheck R4) when it has one, else all zeros."""
    import re
    from identifiers.banking import BBAN_FORMAT
    fmt = BBAN_FORMAT.get(cc)
    body = ("".join(("A" if k == "a" else "0") * int(n)
                    for n, k in re.findall(r"(\d+)([nac])", fmt))
            if fmt and length == IBAN_LENGTH.get(cc) else "0" * (length - 4))
    for chk in range(2, 99):
        s = f"{cc}{chk:02d}{body}"
        from identifiers.banking import iban_mod97
        if iban_mod97(s) == 1:
            return s
    raise AssertionError(cc)


@pytest.mark.parametrize("cc", ["ZZ", "US", "CA", "AU", "IN", "QQ"])
def test_an_iban_from_a_country_outside_the_registry_is_invalid(cc):
    v = validate("iban", _iban(cc, 22))
    assert v.ok is False and "registry" in v.note, v


@pytest.mark.parametrize("cc", sorted(IBAN_LENGTH))
def test_a_registry_country_with_good_check_digits_is_valid(cc):
    assert validate("iban", _iban(cc, IBAN_LENGTH[cc])).ok


def test_real_ibans_still_pass():
    for s in ["GB82 WEST 1234 5698 7654 32", "DE89 3704 0044 0532 0130 00",
              "FR14 2004 1010 0505 0001 3M02 606"]:
        assert validate("iban", s).ok, s


@pytest.mark.parametrize("vat, ok", [
    ("GBGD001", True), ("GBGD499", True), ("GBGD500", False), ("GBGD999", False),
    ("GBHA500", True), ("GBHA999", True), ("GBHA000", False), ("GBHA499", False),
    ("XIGD100", True), ("XIHA100", False), ("GB980780684", True),
])
def test_uk_government_and_health_authority_ranges(vat, ok):
    assert bool(validate("vat", vat).ok) is ok


@pytest.mark.parametrize("vat", ["US123456789", "EU372000041", "CH123456789", "GR123"])
def test_a_vat_prefix_outside_the_list_or_a_bad_body_is_invalid(vat):
    assert validate("vat", vat).ok is False


@pytest.mark.parametrize("letter", list("ABCFGHJLPT"))
def test_every_pan_entity_letter_is_valid(letter):
    assert validate("pan", f"AAA{letter}A1234A").ok


@pytest.mark.parametrize("letter", list("DEIKMNOQRSUVWXYZ"))
def test_an_unassigned_pan_entity_letter_is_invalid(letter):
    assert validate("pan", f"AAA{letter}A1234A").ok is False
