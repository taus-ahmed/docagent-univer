"""Review-3 F1: the subunit must close a written amount.

"fifty cents one dollar" was read as 50.01, "ninety nine cents two dollars"
as 99.02 and "one pence two pounds" as 1.02: the subunit-first branch
('and paise fifty') took the number AFTER the subunit word as the cents and
the one before it as the main amount. Any order the parser cannot read
unambiguously must come back unreadable (value None), never as a number.

The property tests enumerate every order of the four parts — a number, the
main unit, another number, the subunit — for every main-unit and subunit word
the parser knows, and read the result by ROLE: the first number phrase is the
main amount, the second the subunit.
"""
import itertools
import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "engine"))

from cheque_amounts import (_CENT_WORDS, _MAIN_UNITS, compare_amounts,  # noqa: E402
                            parse_words_amount)

NUMBERS = {"one": 1, "twenty three": 23, "fifty": 50, "ninety nine": 99,
           "one thousand two hundred": 1200}
#: shapes a reader can take one way only; N = a number phrase
CANONICAL = {"NUNS", "UNNS", "NUSN", "UNSN"}


@pytest.mark.parametrize("text", [
    "fifty cents one dollar",
    "ninety nine cents two dollars",
    "one pence two pounds",
    "fifty paise one rupee",
    "seventy five fils three dirhams",
    "cents fifty one dollar",
    "dollar fifty cents one",
    "fifty cents one",
    "one dollar fifty cents two cents",
    "56/100 one dollar",
    "and 56/100 one thousand dollars",
])
def test_reported_and_neighbouring_orders_are_unreadable(text):
    r = parse_words_amount(text)
    assert r.value is None, (text, r)
    assert compare_amounts("1.00", text).status == "unreadable"


@pytest.mark.parametrize("text, value", [
    ("one dollar and fifty cents", "1.50"),
    ("Two thousand five hundred pounds and fifty pence", "2500.50"),
    ("Rupees One Lakh Twenty Thousand and Paise Fifty Only", "120000.50"),
    ("one thousand and 56/100 dollars", "1000.56"),
    ("Dollars one thousand and 56/100", "1000.56"),
    ("Three thousand dirhams and seventy five fils only", "3000.75"),
])
def test_ordinary_orders_still_read(text, value):
    assert parse_words_amount(text).value == Decimal(value)


def _shape(parts):
    return "".join("N" if p[0] == "N" else p[0] for p in parts)


@pytest.mark.parametrize("main", sorted(_MAIN_UNITS))
def test_every_order_reads_by_role_or_not_at_all(main):
    for sub in sorted(_CENT_WORDS):
        for a, b in itertools.permutations(NUMBERS, 2):
            parts = [("N", a), ("U", main), ("N", b), ("S", sub)]
            for order in itertools.permutations(parts):
                shape = _shape(order)
                words = [w for _, w in order]
                for text in (" ".join(words),
                             " ".join(words[:2] + ["and"] + words[2:])):
                    got = parse_words_amount(text).value
                    nums = [w for k, w in order if k == "N"]
                    first, second = NUMBERS[nums[0]], NUMBERS[nums[1]]
                    if shape not in CANONICAL:
                        assert got is None, (text, got)
                        continue
                    want = (Decimal(f"{first}.{second:02d}")
                            if second <= 99 else None)
                    assert got in (None, want), (text, got, want)
                    if shape.index("S") < shape.index("U"):
                        assert got is None, (text, got)


@pytest.mark.parametrize("main", sorted(_MAIN_UNITS))
def test_the_standard_order_reads_for_every_currency_word(main):
    for sub in sorted(_CENT_WORDS):
        text = f"twenty three {main} and ninety nine {sub}"
        assert parse_words_amount(text).value == Decimal("23.99"), text


@pytest.mark.parametrize("main", ["dollars", "pounds", "rupees", "euros"])
def test_a_fraction_closes_the_amount(main):
    for text, ok in [(f"one thousand and 56/100 {main}", True),
                     (f"{main} one thousand and 56/100", True),
                     (f"one thousand {main} and 56/100", True),
                     (f"56/100 one thousand {main}", False),
                     (f"56/100 {main} one thousand", False),
                     (f"{main} 56/100 one thousand", False)]:
        got = parse_words_amount(text).value
        assert (got == Decimal("1000.56")) if ok else (got is None), (text, got)
