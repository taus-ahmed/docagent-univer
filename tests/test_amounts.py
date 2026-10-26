"""engine/amounts.py — one locale-aware amount parser (Part 1.1).

The property: a number rendered in ANY supported style either parses back to
exactly itself, or is flagged ambiguous. Never a different number.
"""
from __future__ import annotations

import random
from decimal import Decimal

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

from amounts import (NUMBER_AMBIGUOUS, MINOR_UNITS_MISMATCH,  # noqa: E402
                     document_hint, money, parse_amount)


def _group(digits: str, sep: str, lakh=False) -> str:
    if not sep:
        return digits
    if lakh and len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        return sep.join(parts + [tail])
    out = []
    while len(digits) > 3:
        out.insert(0, digits[-3:])
        digits = digits[:-3]
    out.insert(0, digits)
    return sep.join(out)


STYLES = [  # (group, decimal, lakh)
    (",", ".", False), (".", ",", False), (" ", ",", False), (" ", ",", False),
    ("'", ".", False), (",", ".", True), ("", ".", False), ("", ",", False),
    (" ", ".", False), (" ", ",", False),
]
WRAPS = ["{n}", "${n}", "{n} €", "£{n}", "₹ {n}", "Rs. {n}", "AED {n}", "{n} CHF",
         "USD {n}", "({n})", "-{n}", "{n}-", "{n} Dr", "{n} Cr", "EUR{n}"]


def _render(value: Decimal, style, decimals: int) -> str:
    grp, dec, lakh = style
    q = abs(value).quantize(Decimal(1).scaleb(-decimals)) if decimals else abs(value).to_integral_value()
    whole, _, frac = format(q, "f").partition(".")
    s = _group(whole, grp, lakh)
    return s + (dec + frac if decimals else "")


@pytest.mark.parametrize("seed", range(40))
def test_rendered_numbers_parse_back_or_are_flagged(seed):
    rnd = random.Random(seed)
    for _ in range(150):
        decimals = rnd.choice([0, 0, 1, 2, 2, 2, 3])
        mag = rnd.choice([1, 10, 100, 1000, 10 ** 4, 10 ** 5, 10 ** 6, 10 ** 8])
        value = Decimal(rnd.randrange(0, mag * 10 ** decimals)).scaleb(-decimals)
        style = rnd.choice(STYLES)
        body = _render(value, style, decimals)
        wrap = rnd.choice(WRAPS)
        text = wrap.format(n=body)
        neg = wrap.startswith(("(", "-")) or wrap.endswith(("-", "Dr"))
        want = -value if neg and value else value
        a = parse_amount(text)
        if a.ambiguous:
            assert a.value is None and NUMBER_AMBIGUOUS in a.reasons, text
            continue
        assert a.ok, (text, a)
        assert a.value == want, (text, a.value, want)


@pytest.mark.parametrize("text,value,currency", [
    ("$1,234.56", "1234.56", None), ("1.234,56 €", "1234.56", "EUR"),
    ("1 234,56", "1234.56", None), ("1'234.56", "1234.56", None),
    ("1,23,456.78", "123456.78", None), ("₹ 1,23,456", "123456", "INR"),
    ("Rs. 1,000/-", "1000", "INR"), ("AED 2,500.00", "2500.00", "AED"),
    ("د.إ 100", "100", "AED"), ("CHF 1'000.50", "1000.50", "CHF"),
    ("1,234円", "1234", "JPY"), ("JPY 1000", "1000", "JPY"),
    ("(1,234.00)", "-1234.00", None), ("1,234.00-", "-1234.00", None),
    ("500.00 Dr", "-500.00", None), ("500.00 Cr", "500.00", None),
    ("1.234.567,89", "1234567.89", None), ("12,34,56,789", "123456789", None),
    ("£1.50", "1.50", "GBP"), ("SGD 12.00", "12.00", "SGD"),
    ("***1,234.56***", "1234.56", None), ("0,123", "0.123", None),
])
def test_known_notations(text, value, currency):
    a = parse_amount(text)
    assert a.value == Decimal(value), (text, a)
    assert a.currency == currency


@pytest.mark.parametrize("text", ["1,234", "1.234", "KWD 1.234", "$1,234",
                                  "USD 10.123", "¥1,234"])
def test_three_digit_groups_are_ambiguous_without_evidence(text):
    a = parse_amount(text)
    assert a.value is None and a.ambiguous and NUMBER_AMBIGUOUS in a.reasons


def test_evidence_resolves_and_says_how():
    assert parse_amount("1,234", ".").value == 1234
    assert parse_amount("1,234", ",").value == Decimal("1.234")
    assert parse_amount("1,234", ",").resolved_by == "hint"
    assert parse_amount("1,234円").resolved_by == "minor_units"


@pytest.mark.parametrize("text", ["JPY 1,000.50", "¥ 10.5 JPY", "USD 1.5000"])
def test_a_fraction_the_currency_does_not_have_is_flagged(text):
    a = parse_amount(text)
    assert a.ok and MINOR_UNITS_MISMATCH in a.reasons, a


def test_three_decimal_currencies_are_not_flagged():
    a = parse_amount("KWD 1,234.567")
    assert a.value == Decimal("1234.567") and not a.reasons


@pytest.mark.parametrize("text", ["abc", "Total", "2024-01-05", "01/02/2024",
                                  "1,2,3", "12,34", "1..2", "", None])
def test_not_a_number(text):
    a = parse_amount(text)
    if text == "12,34":          # a two-place comma decimal is a number
        assert a.value == Decimal("12.34")
        return
    assert a.value is None and not a.ambiguous


def test_percent():
    a = parse_amount("8.25%")
    assert a.value == Decimal("8.25") and a.percent
    assert money("8.25%") is None      # a rate is not an amount


def test_document_hint_needs_agreement():
    assert document_hint(["1,234.56", "Invoice 12"]) == "."
    assert document_hint(["1.234,56", "12,5"]) == ","
    assert document_hint(["1,234.56", "1.234,56"]) is None
    assert document_hint(["1,234"]) is None
    assert document_hint(["1,234.56"], locale="de-DE") == ","
    assert document_hint([], locale="en-IN") == "."


@pytest.mark.parametrize("text", ["VND-0041", "****7743", "0041", "EUR/12", "#123"])
def test_identifiers_are_not_amounts(text):
    """Found by the harness: a vendor id read as dong and minus 41, a masked
    account's last four read as 7743."""
    assert parse_amount(text).value is None


@pytest.mark.parametrize("text,value", [("***150.00", "150.00"), ("$***150.00", "150.00"),
                                        ("***1,234.56***", "1234.56"), ("0.50", "0.50"),
                                        ("0", "0"), ("USD-10.00", None)])
def test_protectors_still_work(text, value):
    a = parse_amount(text)
    assert a.value == (Decimal(value) if value else None), (text, a)
