"""Run D, D4 + D5 — signed row sums, and per-page subtotals."""
from __future__ import annotations

from tests.contract import run_a_driver as D  # bootstraps backend imports

import source_inventory as SI  # noqa: E402

SLOTS = {"fields": [], "tables": [{"name": "table", "columns": [
    {"header": "Description"}, {"header": "Amount"}]}]}


def test_a_trailing_minus_is_negative():
    rows = {"table": [{"Description": "Services", "Amount": "100.00"},
                      {"Description": "Refund", "Amount": "20.00-"}]}
    page = [D.words(1, ["Services 100.00", "Refund 20.00-", "Total 80.00"])]
    assert SI.row_sum_checks(SLOTS, rows, page, [1]) == []


def test_a_less_line_printed_without_a_sign_is_still_a_deduction():
    rows = {"table": [{"Description": "Services", "Amount": "100.00"},
                      {"Description": "Less discount", "Amount": "20.00"}]}
    page = [D.words(1, ["Services 100.00", "Less discount 20.00", "Total 80.00"])]
    assert SI.row_sum_checks(SLOTS, rows, page, [1]) == []


def test_a_wrong_signed_total_is_still_flagged():
    rows = {"table": [{"Description": "Services", "Amount": "100.00"},
                      {"Description": "Less discount", "Amount": "(20.00)"}]}
    page = [D.words(1, ["Services 100.00", "Less discount (20.00)", "Total 90.00"])]
    out = SI.row_sum_checks(SLOTS, rows, page, [1])
    assert len(out) == 1 and out[0]["row_sum"] == "80.00"


def _two_pages(second_subtotal, extra=()):
    rows = {"table": [
        {"Description": "A", "Amount": "40.00", "_page": 1},
        {"Description": "B", "Amount": "60.00", "_page": 1},
        {"Description": "C", "Amount": "30.00", "_page": 2},
        {"Description": "D", "Amount": "70.00", "_page": 2}]}
    pages = [D.words(1, ["A 40.00", "B 60.00", "Subtotal 100.00"]),
             D.words(2, ["C 30.00", "D 70.00", f"Subtotal {second_subtotal}", *extra])]
    return SI.row_sum_checks(SLOTS, rows, pages, [1, 2])


def test_a_page_whose_rows_do_not_add_up_is_reported_with_its_page():
    out = _two_pages("110.00")
    assert [(m["page"], m["row_sum"], m["printed"]) for m in out] == \
        [(2, "100.00", ["110.00"])]


def test_the_grand_total_must_equal_all_the_rows():
    assert _two_pages("100.00", ["Grand Total 200.00"]) == []
    out = _two_pages("100.00", ["Grand Total 210.00"])
    assert len(out) == 1 and out[0]["row_sum"] == "200.00"
