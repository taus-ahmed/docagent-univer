"""Recheck R4: a UK VAT number carries a check, and an IBAN's account part
has a shape.

Codex mutated valid ids at random: 269 of 1,575 UK VAT mutants (and
GB000000000) were accepted, because only the digit count was checked; and
letter-for-digit IBAN mutants passed wherever mod 97 happened to agree,
because the account part's per-country format was not checked.

UK VAT: the HMRC weighted check — weights 8..2 over the first seven digits
plus the two check digits — must be 0 mod 97, or for numbers from 100 0000
upwards also the "97-55" scheme (+55, i.e. 42 mod 97; python-stdnum also
accepts 55). Seven leading zeros is no number at all.
"""
import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

from identifiers import validate  # noqa: E402
from identifiers.banking import BBAN_FORMAT, IBAN_LENGTH, iban_mod97  # noqa: E402


@pytest.mark.parametrize("vat", ["GB980780684",        # HMRC mod 97
                                 "GB123456727",        # 97-55 scheme
                                 "GB012345620",        # mod 97, prefix below 100
                                 "GB980780684001",     # branch trader
                                 "GBGD001", "GBHA599", "XI980780684"])
def test_valid_uk_vat_numbers(vat):
    assert validate("vat", vat).ok, validate("vat", vat)


@pytest.mark.parametrize("vat", ["GB000000000", "GB000000097", "GB123456789",
                                 "GB980780685", "GB980780648", "GB012345662",
                                 "GB980780684-01"])
def test_invalid_uk_vat_numbers(vat):
    assert not validate("vat", vat).ok, vat


def test_random_mutations_of_a_uk_vat_number_are_rejected():
    import random
    rnd = random.Random(5)
    base = "980780684"
    accepted = 0
    for _ in range(500):
        s = list(base)
        i = rnd.randrange(9)
        s[i] = rnd.choice([d for d in "0123456789" if d != s[i]])
        accepted += bool(validate("vat", "GB" + "".join(s)).ok)
    assert accepted <= 20, accepted          # a 2-digit check: about 3 in 97 survive


def test_every_registry_country_has_an_account_format_of_the_right_length():
    import re
    assert set(BBAN_FORMAT) == set(IBAN_LENGTH)
    for cc, fmt in BBAN_FORMAT.items():
        total = sum(int(n) for n in re.findall(r"(\d+)[nac]", fmt))
        assert total + 4 == IBAN_LENGTH[cc], (cc, fmt)


def _with_check(cc, bban):
    for d in range(2, 99):
        s = f"{cc}{d:02d}{bban}"
        if iban_mod97(s) == 1:
            return s
    raise AssertionError(cc)


@pytest.mark.parametrize("iban", ["GB29NWBK6016133192681T", "NO938601111794W",
                                  _with_check("DE", "37040044053201300A"),
                                  _with_check("GB", "1WBK60161331926819"),
                                  _with_check("NL", "ABN10417164300")])
def test_an_account_part_of_the_wrong_shape_is_invalid(iban):
    assert iban_mod97(iban) == 1                 # the check digits agree…
    v = validate("iban", iban)
    assert not v.ok and "format" in v.note, v    # …the shape does not


def test_real_ibans_still_pass():
    for s in ["GB82WEST12345698765432", "DE89370400440532013000",
              "FR1420041010050500013M02606", "NO9386011117947",
              "BR1800360305000010009795493C1", "MU17BOMM0101101030300200000MUR"]:
        assert validate("iban", s).ok, (s, validate("iban", s))
