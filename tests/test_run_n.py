"""Run N — regressions found while fixing the review/run-h defects.

N2 (review B1) made a value ground only on the row its quote names. The
replay harness then showed one correct value demoted: EXP-2024-0081 prints
its Purpose wrapped ABOVE its label (`... Pacific Steel, Los` over
`Purpose: Angeles`). A line whose every word is the quote's own is part of
that row, above or below it.
"""
from __future__ import annotations

from tests import overnight_helpers as H
from tests.contract import run_a_driver as D
from tests.test_overnight_ae_adversarial_review import _field_answer, _run_geometry


def test_n2_a_value_wrapped_above_its_label_stays_grounded():
    grid = H.column_grid(["Purpose"])
    lines = D.words(1, [
        "EXPENSE REPORT PLEASE ATTACH ALL RECEIPTS AND RETAIN A COPY FOR YOUR RECORDS",
        "Supplier site visit Pacific Steel, Los",
        "Purpose: Angeles",
        "Date Type Description Category Amount",
    ])
    answer = _field_answer(grid, [
        ("Purpose", "Supplier site visit Pacific Steel, Los Angeles",
         "Purpose: Supplier site visit Pacific Steel, Los Angeles", 1),
    ])
    data, _calls = _run_geometry([lines], grid, answer, doc_type="expense_report")
    assert H.level(data, "Purpose") == "high"
    assert "Purpose" not in H.flagged_refs(data)


def test_n2_a_neighbouring_row_with_its_own_label_is_not_the_quote_row():
    import slot_extractor as S
    lines = D.words(1, ["Opening Balance 100.00", "Closing Balance 170.00"])
    lines = lines if isinstance(lines[0], list) else [lines]
    assert S.value_off_its_row("170.00", "Opening Balance 170.00", lines)
    assert not S.value_off_its_row("100.00", "Opening Balance 100.00", lines)
