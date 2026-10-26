"""Amounts in words in any common currency and scale (Part 1.2).

A match never raises confidence; a mismatch is exactly low with
amount_mismatch; anything not read with certainty is unreadable — badly
ordered or repeated scales, mixed systems, other languages."""
from decimal import Decimal as D

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

from cheque_amounts import compare_amounts, parse_words_amount  # noqa: E402


@pytest.mark.parametrize("text,value", [
    ("One Lakh Twenty Thousand Rupees Only", "120000.00"),
    ("Rupees One Lakh Twenty Thousand and Paise Fifty Only", "120000.50"),
    ("Rupees Twelve Crore Fifty Lakh Only", "125000000.00"),
    ("One Crore Twenty Three Lakh Forty Five Thousand Six Hundred Seventy Eight", "12345678.00"),
    ("Five Lakh Crore Rupees", "5000000000000.00"),
    ("One Hundred Crore", "1000000000.00"),
    ("Two thousand five hundred pounds and fifty pence", "2500.50"),
    ("Ten thousand euros and 25/100", "10000.25"),
    ("Three thousand dirhams and seventy five fils only", "3000.75"),
    ("One hundred twenty thousand yen only", "120000.00"),
    ("Seven milliard", "7000000000.00"),
    ("two billion", "2000000000.00"),
    ("Fifteen thousand Swiss francs", None),       # "swiss" is not a number word
    ("One thousand two hundred thirty-four and 56/100", "1234.56"),
])
def test_scales_and_currencies(text, value):
    got = parse_words_amount(text).value
    assert got == (D(value) if value else None), (text, got)


def test_long_scale_on_request():
    assert parse_words_amount("two billion", long_scale=True).value == D("2000000000000.00")


@pytest.mark.parametrize("text", [
    "One lakh One lakh", "One thousand one lakh", "one million two lakh",
    "lakh five", "crore", "twenty crore crore", "eine tausend", "mille deux cents",
    "एक लाख", "ألف درهم", "thousand thousand", "five hundred million million",
])
def test_unreadable_never_guessed(text):
    assert parse_words_amount(text).value is None, text


def test_cross_check_statuses_in_rupees():
    ok = compare_amounts("₹1,20,000.50", "Rupees One Lakh Twenty Thousand and Paise Fifty Only")
    assert ok.status == "match"
    bad = compare_amounts("₹1,20,000.50", "Rupees One Lakh Twelve Thousand Only")
    assert bad.status == "mismatch"
    assert compare_amounts("₹1,20,000.50", "एक लाख").status == "unreadable"
