"""Bank statements in every style (Part 1.9): Dr/Cr single amount columns,
either row order, repeated headers, wrapped narrations, page-boundary rows,
and the printed transaction count."""
from __future__ import annotations

from tests.harness import bootstrap as bs

bs.bootstrap()

from validators import FAIL, PASS, CheckContext  # noqa: E402

FIELDS = [{"ref": "B1", "row_label": "Opening Balance"}, {"ref": "B2", "row_label": "Total Credits"},
          {"ref": "B3", "row_label": "Total Debits"}, {"ref": "B4", "row_label": "Closing Balance"},
          {"ref": "B5", "row_label": "Number of Transactions"}]
SPLIT = {"name": "t", "columns": [{"key": k, "header": k} for k in
                                  ("Date", "Description", "Debit", "Credit", "Balance")]}
SINGLE = {"name": "t", "columns": [{"key": k, "header": k} for k in
                                   ("Date", "Particulars", "Amount", "Balance")]}


def _run(table, rows, values):
    from bank_validators import bank_balances
    return bank_balances(CheckContext(fields=FIELDS, values=values, pages=[],
                                      tables=[table], rows={"t": rows}))


def _status(res, check):
    return [r.status for r in res if r.check == check]


def _vals(o, c, d, cl, n):
    return {"B1": o, "B2": c, "B3": d, "B4": cl, "B5": n}


def test_dr_cr_single_amount_column_chains():
    rows = [{"Date": "01-03-2024", "Particulars": "Salary", "Amount": "50,000.00 Cr", "Balance": "1,50,000.00 Cr"},
            {"Date": "05-03-2024", "Particulars": "Rent", "Amount": "20,000.00 Dr", "Balance": "1,30,000.00 Cr"}]
    res = _run(SINGLE, rows, _vals("1,00,000.00", "50,000.00", "20,000.00", "1,30,000.00", "2"))
    assert _status(res, "bank_running_balance") == [PASS]
    assert _status(res, "bank_row_count") == [PASS]
    bad = [dict(r) for r in rows]
    bad[1]["Amount"] = "20,000.00 Cr"                   # swapped direction
    res = _run(SINGLE, bad, _vals("1,00,000.00", "50,000.00", "20,000.00", "1,30,000.00", "2"))
    assert FAIL in _status(res, "bank_running_balance")


def test_unsigned_single_column_is_unreadable_not_guessed():
    rows = [{"Date": "x", "Particulars": "a", "Amount": "50.00", "Balance": "150.00"}]
    res = _run(SINGLE, rows, _vals("100.00", "50.00", "0.00", "150.00", "1"))
    assert "unreadable" in _status(res, "bank_running_balance")


def test_dashes_are_empty_cells_and_either_order_works():
    rows = [{"Date": "1", "Description": "In", "Debit": "-", "Credit": "50.00", "Balance": "150.00"},
            {"Date": "2", "Description": "Out", "Debit": "20.00", "Credit": "—", "Balance": "130.00"}]
    v = _vals("100.00", "50.00", "20.00", "130.00", "2")
    assert _status(_run(SPLIT, rows, v), "bank_running_balance") == [PASS]
    assert _status(_run(SPLIT, rows[::-1], v), "bank_running_balance") == [PASS]   # newest first


def test_repeated_headers_wrapped_narrations_and_forward_rows_are_not_transactions():
    rows = [{"Date": "1", "Description": "Balance brought forward", "Debit": "", "Credit": "", "Balance": "100.00"},
            {"Date": "2", "Description": "Card payment to", "Debit": "20.00", "Credit": "", "Balance": "80.00"},
            {"Date": "", "Description": "ACME FUEL STATION 4", "Debit": "", "Credit": "", "Balance": ""},
            {"Date": "Date", "Description": "Description", "Debit": "Debit", "Credit": "Credit", "Balance": "Balance"},
            {"Date": "9", "Description": "Refund", "Debit": "", "Credit": "5.00", "Balance": "85.00"}]
    res = _run(SPLIT, rows, _vals("100.00", "5.00", "20.00", "85.00", "2"))
    assert _status(res, "bank_row_count") == [PASS]
    assert FAIL not in _status(res, "bank_running_balance")


def test_a_dropped_row_is_caught_by_the_count():
    rows = [{"Date": "1", "Description": "In", "Debit": "", "Credit": "50.00", "Balance": "150.00"}]
    res = _run(SPLIT, rows, _vals("100.00", "50.00", "0.00", "150.00", "2"))
    r = [x for x in res if x.check == "bank_row_count"][0]
    assert (r.status, r.reason, r.slots) == (FAIL, "row_count_mismatch", ["B5"])
