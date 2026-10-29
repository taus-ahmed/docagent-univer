"""Recheck 2 S1: the MAIN-unit words are validated, not dropped as filler.

"dollars two dollars" read 2.00, "euros three euros" 3.00 and "one dollar
pound" 1.00: every main-unit token was removed unchecked once the subunit
checks had run. One main unit per amount, opening the amount or following
its whole number; anything else is unreadable with a reason, never a value.
"""
import itertools

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

from cheque_amounts import CURRENCY_OF, UNIT_FAMILIES, _MAIN_UNITS, parse_words_amount  # noqa: E402

UNITS = sorted(_MAIN_UNITS)


def _refused(text, reason):
    r = parse_words_amount(text)
    assert r.value is None and reason in r.reasons, (text, r)


@pytest.mark.parametrize("text,reason", [("dollars two dollars", "unit_repeat"),
                                         ("euros three euros", "unit_repeat"),
                                         ("one dollar pound", "unit_mix"),
                                         ("one thousand dollars two hundred", "unit_order")])
def test_the_reported_cases(text, reason):
    _refused(text, reason)


@pytest.mark.parametrize("w", UNITS)
def test_a_repeated_main_unit_is_unreadable_in_every_position(w):
    for text in (f"{w} two {w}", f"two {w} {w}", f"{w} {w} two",
                 f"two {w} and fifty {w}", f"{w} one hundred {w} only"):
        _refused(text, "unit_repeat")


@pytest.mark.parametrize("w", UNITS)
def test_a_number_after_a_closing_unit_is_unreadable(w):
    for text in (f"two {w} three", f"one hundred {w} twenty", f"five {w} and six"):
        _refused(text, "unit_order")


@pytest.mark.parametrize("a,b", [(a, b) for a, b in itertools.permutations(UNITS, 2)
                                 if CURRENCY_OF[a] != CURRENCY_OF[b]
                                 and (a, b) not in (("pound", "sterling"), ("pounds", "sterling"))])
def test_two_currencies_in_one_amount_are_unreadable(a, b):
    for text in (f"one {a} {b}", f"{a} one {b}", f"{a} {b} one"):
        _refused(text, "unit_mix")


@pytest.mark.parametrize("w", UNITS)
def test_one_unit_opening_or_closing_the_amount_still_reads(w):
    for text in (f"two {w}", f"{w} two", f"{w} two only", f"two hundred {w} only"):
        r = parse_words_amount(text)
        assert r.value is not None, (text, r)
    sub = sorted(UNIT_FAMILIES[w])
    if sub:
        assert str(parse_words_amount(f"two {w} and five {sub[0]}").value) == "2.05"
        assert str(parse_words_amount(f"{w} two and {sub[0]} five only").value) == "2.05"


def test_ordinary_written_amounts_are_unchanged():
    for text, want in [("Rupees One Lakh Twenty Thousand and Paise Fifty Only", "120000.50"),
                       ("One thousand two hundred thirty-four and 56/100 dollars", "1234.56"),
                       ("Ten pounds sterling", "10.00"), ("US Dollars Five Only", "5.00")]:
        assert str(parse_words_amount(text).value) == want, text
