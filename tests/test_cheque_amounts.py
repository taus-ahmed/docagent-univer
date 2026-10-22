from decimal import Decimal as D

import pytest

from cheque_amounts import compare_amounts, parse_numeric_amount, parse_words_amount


@pytest.mark.parametrize("text,expected", [
    ("$1,234.56", D("1234.56")),
    ("1234.56", D("1234.56")),
    ("$ 3,572.78", D("3572.78")),
    ("$1,000", D("1000.00")),
    ("***$150.00***", D("150.00")),
    ("0.99", D("0.99")),
    ("$12,345,678.90", D("12345678.90")),
])
def test_numeric_ok(text, expected):
    assert parse_numeric_amount(text).value == expected


@pytest.mark.parametrize("text", [
    "", "   ", "abc", "1.234,56", "1.234.567", "1,23,456.00", "(150.00)",
    "-150.00", "150.5", "150.555", "12 and 3", "$", "1,2345.00",
])
def test_numeric_refuses_to_guess(text):
    assert parse_numeric_amount(text).value is None


@pytest.mark.parametrize("text,expected", [
    ("One thousand two hundred thirty-four and 56/100", D("1234.56")),
    ("One Thousand Two Hundred Thirty-Four and 56/100 Dollars", D("1234.56")),
    ("three thousand five hundred seventy two and 78/100", D("3572.78")),
    ("Three Thousand Five Hundred Seventy-Two Dollars and 78/100", D("3572.78")),
    ("one hundred fifty and 00/100", D("150.00")),
    ("one hundred fifty and xx/100", D("150.00")),
    ("one hundred fifty and no/100", D("150.00")),
    ("One hundred fifty only", D("150.00")),
    ("Fifty and 5/100", D("50.05")),
    ("twelve hundred and 00/100", D("1200.00")),
    ("Two hundred dollars and fifty-six cents", D("200.56")),
    ("forty five dollars and ninety nine cents", D("45.99")),
    ("fourty dollars and 00/100", D("40.00")),
    ("one million two hundred thousand and 00/100", D("1200000.00")),
    ("Nine hundred ninety-nine and 99/100 dollars", D("999.99")),
    ("**Seven hundred and 00/100**", D("700.00")),
])
def test_words_ok(text, expected):
    assert parse_words_amount(text).value == expected


@pytest.mark.parametrize("text", [
    "", "56/100", "and 56/100", "one hundred fifty and 3/7", "one hundrad fifty and 00/100",
    "one hundred fifty 5 and 00/100", "hundred and 00/100", "thousand",
    "one hundred fifty and 150/100", "one hundred and ninety nine hundred cents",
    "banana",
])
def test_words_refuse_to_guess(text):
    assert parse_words_amount(text).value is None


def test_match():
    r = compare_amounts("$3,572.78", "Three Thousand Five Hundred Seventy-Two and 78/100")
    assert r.status == "match" and r.numeric == r.words == D("3572.78")


def test_mismatch_catches_a_wrong_digit():
    # the OCR/pre-OCR case from Gate 1: $8,572.78 where the true amount is $3,572.78
    r = compare_amounts("$8,572.78", "Three Thousand Five Hundred Seventy-Two and 78/100")
    assert r.status == "mismatch" and "amounts_differ" in r.reasons


def test_mismatch_cents():
    r = compare_amounts("$150.50", "One hundred fifty and 00/100")
    assert r.status == "mismatch"


def test_unreadable_when_either_side_is_missing_or_junk():
    assert compare_amounts(None, "One hundred and 00/100").status == "unreadable"
    assert compare_amounts("$100.00", None).status == "unreadable"
    assert compare_amounts("$100.00", "On hundrad and 00/100").status == "unreadable"
    assert compare_amounts("1.234,56", "One thousand two hundred thirty-four and 56/100").status == "unreadable"


def test_unreadable_is_never_a_match_and_never_a_mismatch():
    # an unparseable side must not be turned into a confident verdict either way
    for words in ["", "banana", "56/100", "one hundrad"]:
        assert compare_amounts("$100.00", words).status == "unreadable"


def test_reasons_name_the_side():
    r = compare_amounts("abc", "banana")
    assert any(x.startswith("numeric:") for x in r.reasons)
    assert any(x.startswith("words:") for x in r.reasons)


@pytest.mark.parametrize("text", [
    "one two three and 00/100", "five twenty and 00/100", "one hundred hundred and 00/100",
    "twenty twenty and 00/100", "one thousand one thousand and 00/100",
    "five thousand million and 00/100", "twenty one hundred and 00/100",
    "ninety nine hundred and 00/100", "thousand five and 00/100", "one hundred twenty twenty and 00/100",
    "ten ten and 00/100", "zero hundred and 00/100",
])
def test_badly_ordered_number_words_are_unreadable_not_guessed(text):
    assert parse_words_amount(text).value is None


@pytest.mark.parametrize("text,expected", [
    ("nineteen hundred and 00/100", D("1900.00")),
    ("one hundred fifty dollars and no cents", D("150.00")),
    ("Two hundred and no cents", D("200.00")),
    ("fifty dollars and 00 cents", D("50.00")),
    ("one million and 00/100", D("1000000.00")),
    ("one thousand one and 00/100", D("1001.00")),
    ("two thousand five hundred and 00/100", D("2500.00")),
    ("zero dollars and 50/100", D("0.50")),
    ("one hundred one", D("101.00")),
])
def test_more_valid_phrasings(text, expected):
    assert parse_words_amount(text).value == expected
