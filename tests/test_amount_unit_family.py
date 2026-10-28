"""Recheck R3: a subunit of another currency makes the words unreadable.

"ten rupees fifty cents" read as 10.50 and "five dollars fifty paise" as
5.50. A cent is not a hundredth of a rupee; what the writer meant is not
knowable, so the amount is unreadable (`unit_mix`), never a number.
"""
import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

from cheque_amounts import UNIT_FAMILIES, _CENT_WORDS, _MAIN_UNITS, parse_words_amount  # noqa: E402


@pytest.mark.parametrize("text", ["ten rupees fifty cents", "five dollars fifty paise",
                                  "two pounds ten cents", "one euro five pence",
                                  "three yen fifty cents", "seven dirhams ten halalas",
                                  "six francs ten paise"])
def test_a_foreign_subunit_is_unreadable(text):
    r = parse_words_amount(text)
    assert r.value is None and "unit_mix" in r.reasons, (text, r)


@pytest.mark.parametrize("text,want", [("ten rupees fifty paise", "10.50"),
                                       ("five dollars and fifty cents", "5.50"),
                                       ("two pounds ten pence", "2.10"),
                                       ("one euro five cents", "1.05"),
                                       ("seven dirhams ten fils", "7.10"),
                                       ("six francs ten centimes", "6.10"),
                                       ("eight riyals five halalas", "8.05"),
                                       ("fifty five dollars only", "55.00")])
def test_a_currency_with_its_own_subunit_still_reads(text, want):
    r = parse_words_amount(text)
    assert str(r.value) == want, (text, r)


def test_every_main_unit_word_has_a_family():
    assert set(UNIT_FAMILIES) == set(_MAIN_UNITS)
    assert all(sub <= _CENT_WORDS for sub in UNIT_FAMILIES.values())
