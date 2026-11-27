"""Run T, 1 — false Lows from SPACING.

The text layer glues two printed words ("ACHDEBIT") and the model writes
them apart ("ACH DEBIT"), or it splits what the page prints as one token; the
"found on the page as quoted" check failed, and the failed DESCRIPTION
marked the row's right date, amount and balance Low too.

Rules: a value that differs from its span only in spacing grounds; a cell
that fails grounding is Low on its own and never makes its row's other
cells Low. A different word still fails (negative twins).
"""
from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from tests import run_q_support as Q
from tests.harness import bootstrap as bs

bs.bootstrap()

from slot_extractor import verify_span  # noqa: E402


# printed line, the model's description, should it ground
CASES = [
    # bank: glued transaction codes
    ("07/15/2019 C&J SHOE RETAIL ACHDEBIT SETTLEMENT $1,845.80 $2,041.01",
     "C&J SHOE RETAIL ACH DEBIT SETTLEMENT", True),
    ("03/02/2024 POSDEBIT GROCERYMART #12 $54.10 $900.00",
     "POS DEBIT GROCERY MART #12", True),
    # the other direction: the page spaces, the model glues
    ("11/04/2023 CHECK CARD PURCHASE FUELSTOP 41.00 1,200.10",
     "CHECKCARD PURCHASE FUELSTOP", True),
    # another vocabulary and layout: a card statement, a utility bill
    ("Jan 03 Jan 04 ONLINETRANSFER TO SAVINGS 250.00",
     "ONLINE TRANSFER TO SAVINGS", True),
    ("Lastschrift SEPA-Einzug STADTWERKE 89,90",
     "SEPA - Einzug STADTWERKE", True),
    # negative twins: same shape, different word -> still not grounded
    ("07/15/2019 C&J SHOE RETAIL ACHDEBIT SETTLEMENT $1,845.80 $2,041.01",
     "C&J SHOE RETAIL ACH CREDIT SETTLEMENT", False),
    ("03/02/2024 POSDEBIT GROCERYMART #12 $54.10 $900.00",
     "POS DEBIT GROCERY MARTS #12", False),
    # too short to trust a spacing-free match
    ("AB CD 12.00", "ABC", False),
]


@pytest.mark.parametrize("line,value,ok", CASES)
def test_spacing_is_not_content(line, value, ok):
    got, _why = verify_span(value, line, 1, [line])
    assert got is ok, (line, value)


def test_quote_with_the_models_spacing_still_finds_its_line():
    line = "07/15/2019 C&J SHOE RETAIL ACHDEBIT SETTLEMENT $1,845.80 $2,041.01"
    quote = "07/15/2019 C&J SHOE RETAIL ACH DEBIT SETTLEMENT $1,845.80 $2,041.01"
    for v in ("C&J SHOE RETAIL ACH DEBIT SETTLEMENT", "$1,845.80", "07/15/2019"):
        assert verify_span(v, quote, 1, ["Statement", line])[0], v


# ── end to end: the row's other cells stay confident ─────────────────────────

LINES = ["Sample Bank", "Date Description Debits Credits Balance",
         "07/12/2019 DEPOSIT 131 $86.96 $2,395.78",
         "07/15/2019 C&J SHOE RETAIL ACHDEBIT SETTLEMENT $1,845.80 $549.98",
         "07/16/2019 DEPOSIT 131 $94.48 $644.46"]
INFERRED = {"document_type": "bank_statement", "title": "Statement", "fields": [],
            "totals": [], "tables": [{"name": "Transactions", "row_count": 3,
                                      "columns": ["Date", "Description", "Debits",
                                                  "Credits", "Balance"]}]}


def _run(pdf, rows):
    import extractor
    calls = []

    def extract(prompt="", system_instruction="", **kw):
        calls.append(prompt)
        if (system_instruction or "").startswith("You are a document analyst"):
            return Q._Resp(copy.deepcopy(INFERRED))
        if len(calls) <= 2:
            return Q._Resp({"fields": {}, "tables": {"Transactions": copy.deepcopy(rows)}})
        r = Q._Resp(None, "")
        r.error = "scripted: no further answer"
        return r
    return extractor.run_extraction(SimpleNamespace(llm=SimpleNamespace(extract=extract)),
                                    pdf, None)[0].extracted_data


def _rows(desc):
    return [
        {"Date": "07/12/2019", "Description": "DEPOSIT 131", "Debits": "",
         "Credits": "$86.96", "Balance": "$2,395.78", "source": LINES[2], "page": 1},
        {"Date": "07/15/2019", "Description": desc, "Debits": "$1,845.80",
         "Credits": "", "Balance": "$549.98",
         "source": LINES[3].replace("ACHDEBIT", "ACH DEBIT"), "page": 1},
        {"Date": "07/16/2019", "Description": "DEPOSIT 131", "Debits": "",
         "Credits": "$94.48", "Balance": "$644.46", "source": LINES[4], "page": 1},
    ]


def _pdf(tmp_path):
    return Q.make_pdf(tmp_path / "b.pdf", [[(40, 760 - 16 * i, t)
                                           for i, t in enumerate(LINES)]], size=9)


def test_a_spacing_difference_marks_nothing(tmp_path):
    from app.core.review import row_cell_status
    ed = _run(_pdf(tmp_path), _rows("C&J SHOE RETAIL ACH DEBIT SETTLEMENT"))
    row = ed["Transactions_rows"][1]
    assert row["_confidence"] in ("high", "grounded"), row
    assert not row.get("_ungrounded")
    for col in ("Date", "Description", "Debits", "Balance"):
        assert row_cell_status(ed, row, col)["status"] not in ("low",), col


def test_a_wrong_description_is_low_alone(tmp_path):
    from app.core.review import row_cell_status
    ed = _run(_pdf(tmp_path), _rows("C&J SHOE RETAIL WIRE TRANSFER"))
    row = ed["Transactions_rows"][1]
    assert row.get("_ungrounded") == ["Description"]
    assert row_cell_status(ed, row, "Description")["status"] == "low"
    for col in ("Date", "Debits", "Balance"):
        st = row_cell_status(ed, row, col)
        assert st["status"] != "low" and "grounding_failed" not in st["reasons"], col


def test_a_row_nothing_of_which_is_printed_is_still_low(tmp_path):
    rows = _rows("C&J SHOE RETAIL ACH DEBIT SETTLEMENT")
    rows[1].update({"Date": "08/30/2019", "Description": "INVENTED PAYEE",
                    "Debits": "$9,999.00", "Balance": "$1.00"})
    ed = _run(_pdf(tmp_path), rows)
    bad = [r for r in ed["Transactions_rows"] if r.get("Debits") == "$9,999.00"]
    assert bad and all(r["_confidence"] == "low" for r in bad)
