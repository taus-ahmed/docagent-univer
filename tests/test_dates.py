"""engine/dates.py and the date_notation check (Part 1.3)."""
from __future__ import annotations

from datetime import date

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

from dates import (DATE_AMBIGUOUS, DATE_UNREADABLE, document_order,  # noqa: E402
                   looks_like_a_date, order_for_locale, parse_date)


@pytest.mark.parametrize("text,want,order", [
    ("2024-03-05", date(2024, 3, 5), "ISO"), ("2024/03/05", date(2024, 3, 5), "YMD"),
    ("25/03/2024", date(2024, 3, 25), "DMY"), ("03/25/2024", date(2024, 3, 25), "MDY"),
    ("25.03.24", date(2024, 3, 25), "DMY"), ("05/05/2024", date(2024, 5, 5), "DMY"),
    ("5 Mar 2024", date(2024, 3, 5), "named"), ("March 5, 2024", date(2024, 3, 5), "named"),
    ("05-Mar-24", date(2024, 3, 5), "named"), ("1st January 2025", date(2025, 1, 1), "named"),
    ("Sept 30 2023", date(2023, 9, 30), "named"), ("31-12-1999", date(1999, 12, 31), "DMY"),
])
def test_unambiguous(text, want, order):
    d = parse_date(text)
    assert (d.value, d.order) == (want, order), d


@pytest.mark.parametrize("text", ["03/05/2024", "01.02.24", "12-11-2023"])
def test_swappable_day_month_is_ambiguous(text):
    d = parse_date(text)
    assert d.value is None and d.ambiguous and DATE_AMBIGUOUS in d.reasons


def test_a_hint_resolves_and_is_recorded():
    assert parse_date("03/05/2024", "DMY").value == date(2024, 5, 3)
    assert parse_date("03/05/2024", "MDY").value == date(2024, 3, 5)
    assert parse_date("03/05/2024", "DMY").resolved_by == "hint"


def test_two_digit_years_are_marked():
    assert parse_date("25/03/24").two_digit_year
    assert parse_date("25/03/71").value == date(1971, 3, 25)


@pytest.mark.parametrize("text", ["२५/०३/२०२४", "٢٥/٠٣/٢٠٢٤", "２５/０３/２０２４"])
def test_other_script_digits_are_unreadable(text):
    d = parse_date(text)
    assert d.value is None and DATE_UNREADABLE in d.reasons
    assert looks_like_a_date(text)


@pytest.mark.parametrize("text", ["31/02/2024", "13/13/2024", "INV-2024-03", "1,234.56", ""])
def test_not_dates(text):
    assert parse_date(text).value is None and not parse_date(text).ambiguous


def test_locale_and_document_evidence():
    assert order_for_locale("en-US") == "MDY" and order_for_locale("en-GB") == "DMY"
    assert order_for_locale("en-IN") == "DMY" and order_for_locale("ja-JP") == "YMD"
    assert order_for_locale("en") is None
    assert document_order(["25/03/2024", "03/05/2024"]) == ("DMY", "document")
    assert document_order(["03/25/2024", "03/05/2024"]) == ("MDY", "document")
    assert document_order(["25/03/2024", "03/25/2024"]) == (None, "")
    assert document_order(["03/05/2024"], "en-US") == ("MDY", "locale")


def _ctx(values, locale=None):
    from validators import CheckContext
    return CheckContext(fields=[], values=values, pages=[], locale=locale)


def test_the_check_flags_only_what_nothing_resolves():
    from date_validators import date_notation
    res = date_notation(_ctx({"B1": "03/05/2024", "B2": "Net 30"}))
    assert [(r.status, r.slots, r.reason) for r in res] == \
        [("unreadable", ["B1"], DATE_AMBIGUOUS)]
    res = date_notation(_ctx({"B1": "03/05/2024", "B2": "25/03/2024"}))
    assert not [r for r in res if r.status == "unreadable"]
    ev = next(r for r in res if r.evidence).evidence
    assert ev["B1"] == {"date_order": "DMY", "date_order_resolved_by": "document"}
    res = date_notation(_ctx({"B1": "03/05/2024"}, locale="en-US"))
    assert next(r for r in res if r.evidence).evidence["B1"]["date_order_resolved_by"] == "locale"
