"""A3 — identifiers are text; the control number keeps its printed spacing and
its own box; money always shows two decimals; counts and years are not money.

Values are the real ones from the staging exports (job 51 pitt_sample_w2:
Locality 700102 displayed as 700,102; job 48: Control Number
"0000005712UUQ CKR5 16260").
"""

from __future__ import annotations

import pytest

from tests import overnight_helpers as H
from tests.test_overnight_a1_a2 import PITT, pitt_answer, pitt_grid


def _cells():
    from app.services.excel_cells import cell_format, coerce_cell_value
    return coerce_cell_value, cell_format


@pytest.mark.parametrize("label,value", [
    ("Locality Name", "700102"),
    ("Employer State ID", "XXXX5369"),
    ("Employer State ID", "5369001"),
    ("Box d Control Number", "0000005712 UUQ"),
    ("Remit To Account Number", "83319204"),
    ("Payer TIN", "12-3456789"),
    ("Box b Employer EIN", "123456789"),
    ("ZIP", "15260"),
    ("Recipient Account Number", "7351"),
])
def test_identifiers_are_text(label, value):
    coerce, fmt = _cells()
    assert coerce(value, label) == value
    assert fmt(value, label) is None


@pytest.mark.parametrize("label,value,shown", [
    ("Shipping or Handling", "43", "#,##0.00"),
    ("Box 1 Wages Tips Other Compensation", "15250", "#,##0.00"),
    ("Tax Total", "£656", '"£"#,##0.00'),
    ("Box 12 Amount", "4107.00", "#,##0.00"),
    ("Unit Price", "0.04116", "#,##0.00000"),
])
def test_money_always_shows_two_decimals(label, value, shown):
    _coerce, fmt = _cells()
    assert fmt(value, label) == shown


@pytest.mark.parametrize("label,value,shown", [
    ("Quantity", "40", "#,##0"),
    ("Hours", "12", "#,##0"),
    ("Tax Year", "2026", "0"),
])
def test_counts_and_years_are_not_money(label, value, shown):
    coerce, fmt = _cells()
    assert isinstance(coerce(value, label), (int, float))
    assert fmt(value, label) == shown


def test_control_number_keeps_spacing_and_its_own_box():
    g = pitt_grid()
    answer = pitt_answer(g)
    ref = H.field_id(g, "Box d Control Number")
    # job 48: the model returned the whole line under four column headings
    answer["fields"][ref] = H.ans("0000005712UUQ CKR5 16260",
                                  "0000005712UUQ CKR5 16260")
    data, _ = H.run(PITT, g, answer, doc_type="w2")
    assert H.value(data, "Box d Control Number") == "0000005712 UUQ"
    assert "Box d Control Number" not in H.flagged_refs(data)


def test_control_number_answered_correctly_gets_its_printed_space():
    g = pitt_grid()
    data, _ = H.run(PITT, g, pitt_answer(g), doc_type="w2")
    assert H.value(data, "Box d Control Number") == "0000005712 UUQ"
    assert "Box d Control Number" not in H.flagged_refs(data)
