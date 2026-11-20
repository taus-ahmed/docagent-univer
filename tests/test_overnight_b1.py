"""B1 — a correct value is never Low for grounding: a value is Low for
grounding only when its quote AND the value itself are not found on the page.

Reproductions of the real exports (quotes copied from the cell comments):
job 40 (flowparse_bank_us: the summary balances quoted as the label row),
jobs 53/54 (the brokerage 1099: dot leaders, "1 Interest Income .....70.00"),
job 42 (flowparse_invoice_tax: the two addresses quoted with their line breaks
glued, "14 Weavers YardShoreditchLondon"), job 50 (McGuire addresses).
A value taken from somewhere else stays Low (test_ocr_page_origin pins it).
"""

from __future__ import annotations

import pytest

from tests import overnight_helpers as H

BANK = "bank_statement/flowparse_bank_us.pdf"
BROKERAGE = "1099/irs6744_brokerage_1099DIV_MISC_INT_B.pdf"
INVOICE = "invoice/flowparse_invoice_tax.pdf"
MCGUIRE = "w2/irs6744_w2_mcguire.pdf"

LABEL_ROW = "Beginning balance Withdrawals Deposits Ending balance"


def _one(path, label, value, quote, doc_type="other", labels=None):
    g = H.column_grid(labels or [label])
    answer = {"fields": {H.field_id(g, label): H.ans(value, quote)}, "tables": {}}
    data, _ = H.run(path, g, answer, doc_type=doc_type)
    return data


@pytest.mark.parametrize("label,value", [
    ("Opening Balance", "$18,240.12"),
    ("Total Withdrawals", "$10,309.62"),
    ("Total Deposits", "$12,445.50"),
    ("Closing Balance", "$20,376.00"),
])
def test_job40_label_row_quote_grounds_the_value_beneath_its_heading(label, value):
    data = _one(BANK, label, value, LABEL_ROW, "bank_statement")
    assert H.value(data, label) == value
    assert H.level(data, label) == "high", H.flags(data)
    assert label not in H.flagged_refs(data)


def test_job40_label_row_does_not_ground_a_value_under_another_heading():
    # $10,309.62 is printed under Withdrawals, not under Beginning balance
    data = _one(BANK, "Opening Balance", "$10,309.62", LABEL_ROW, "bank_statement")
    assert H.level(data, "Opening Balance") == "low"


@pytest.mark.parametrize("label,value,quote", [
    ("Box 1 Interest Income", "70.00",
     "1 Interest Income ...........................................70.00"),
    ("Box 2 Early Withdrawal Penalty", "0.00",
     "2 Early Withdrawal Penalty ....................................0.00"),
    ("Box 1a Total Ordinary Dividends", "300.00",
     "1a Total Ordinary Dividends ....................................300.00"),
    ("Box 5 Section 199A Dividends", "48.00",
     "5 Section 199A Dividends ....................................48.00"),
])
def test_jobs53_54_dot_leaders_do_not_hide_the_number(label, value, quote):
    data = _one(BROKERAGE, label, value, quote, "1099")
    assert H.level(data, label) == "high", H.flags(data)
    assert label not in H.flagged_refs(data)


@pytest.mark.parametrize("label,value,quote", [
    ("Vendor Address", "14 Weavers Yard Shoreditch London E2 7DP United Kingdom",
     "14 Weavers YardShoreditchLondon E2 7DPUnited Kingdom"),
    ("Bill To Address", "Unit 9 Quayside Business Park Bristol BS1 6QS United Kingdom",
     "Unit 9Quayside Business ParkBristol BS1 6QSUnited Kingdom"),
])
def test_job42_glued_line_breaks_in_the_quote(label, value, quote):
    data = _one(INVOICE, label, value, quote, "invoice")
    assert H.value(data, label) == value
    assert H.level(data, label) == "high", H.flags(data)


@pytest.mark.parametrize("label,value,quote", [
    ("Employer Address", "210 Main St. YOUR CITY, YOUR STATE, ZIP",
     "210 Main St.YOUR CITY, YOUR STATE, ZIP"),
    ("Employee Address", "410 Broadway Drive YOUR CITY, YOUR STATE, ZIP",
     "410 Broadway DriveYOUR CITY, YOUR STATE, ZIP"),
])
def test_job50_mcguire_addresses(label, value, quote):
    data = _one(MCGUIRE, label, value, quote, "w2")
    assert H.level(data, label) == "high", H.flags(data)


def test_a_value_the_page_does_not_print_stays_low():
    data = _one(INVOICE, "Vendor Address", "99 Nowhere Road London",
                "99 Nowhere RoadLondon", "invoice")
    assert H.level(data, "Vendor Address") == "low"
