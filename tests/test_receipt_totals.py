"""The receipt-totals validator (family receipt).

Two checks, the invoice's sums with a receipt's roles:
  lines  the items' amounts sum to the subtotal, within one cent per line
  total  subtotal + tax + tip / fees - discount = total, within one cent
What was tendered (cash, card, change) is never part of the sum. FAIL: every
value in the failed sum exactly low, review_required, "receipt_mismatch".
UNREADABLE: "receipt_unreadable", no level moves. PASS: evidence only.
Synthetic native receipts; the stub model quotes the page.
"""
from __future__ import annotations

import json

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

from app.core.confidence import HIGH, LOW  # noqa: E402
from tests.test_invoice_totals import _invoice, _run, _template  # noqa: E402

GOOD = [("Subtotal", "$250.00"), ("Sales Tax", "$20.00"), ("Tip", "$15.00"),
        ("Coupon", "($10.00)"), ("Total", "$275.00"),
        ("Cash Tendered", "$300.00"), ("Change", "$25.00")]


def _summary(**over):
    return [(lab, over.get(lab, val)) for lab, val in GOOD]


def _receipt(tmp_path, summary, doc_type="receipt"):
    template = _template(doc_type, [lab for lab, _ in summary])
    return _run(_invoice(tmp_path, summary), summary, template)


def _lvl(ed, ref):
    return ed["validation"]["confidence_map"][ref]


def _reasons(ed, ref):
    return ed["field_provenance"][ref]["review_reasons"]


def test_the_fixture_is_clean_under_another_family(tmp_path):
    ed, refs, rows = _receipt(tmp_path, GOOD, "other")
    assert all(_lvl(ed, refs[lab]) == HIGH for lab, _ in GOOD)
    assert "totals_check" not in json.dumps(ed["field_provenance"])


def test_consistent_totals_pass_and_tendered_lines_are_not_summed(tmp_path):
    ed, refs, rows = _receipt(tmp_path, GOOD)
    for lab, _v in GOOD:
        assert _lvl(ed, refs[lab]) == HIGH, lab
    for lab in ("Subtotal", "Sales Tax", "Tip", "Coupon", "Total"):
        assert ed["field_provenance"][refs[lab]]["totals_check"] == "pass", lab
    for lab in ("Cash Tendered", "Change"):
        assert "totals_check" not in ed["field_provenance"][refs[lab]], lab
    assert ed["field_provenance"][refs["Subtotal"]]["lines_check"] == "pass"
    assert ed["needs_review"] is False


def test_a_total_that_does_not_add_up(tmp_path):
    s = _summary(Total="$285.00")
    ed, refs, rows = _receipt(tmp_path, s)
    for lab in ("Subtotal", "Sales Tax", "Tip", "Coupon", "Total"):
        assert _lvl(ed, refs[lab]) == LOW, lab
        assert "receipt_mismatch" in _reasons(ed, refs[lab]), lab
    assert _lvl(ed, refs["Cash Tendered"]) == HIGH
    assert ed["needs_review"] is True
    assert any("receipt" in f["reason"] or "total" in f["reason"]
               for f in ed["validation"]["flagged_fields"])


def test_items_that_do_not_sum_to_the_subtotal(tmp_path):
    s = _summary(Subtotal="$260.00", Total="$285.00")
    ed, refs, rows = _receipt(tmp_path, s)
    assert _lvl(ed, refs["Subtotal"]) == LOW
    assert all(r["_confidence"] == LOW and "receipt_mismatch" in r["_review_reasons"]
               for r in rows)


def test_an_unreadable_amount_moves_no_level(tmp_path):
    s = _summary(Tip="TBD")
    ed, refs, rows = _receipt(tmp_path, s)
    assert _lvl(ed, refs["Total"]) == HIGH
    assert "receipt_unreadable" in _reasons(ed, refs["Total"])
    assert ed["field_provenance"][refs["Total"]]["totals_check"] == "unreadable"


@pytest.mark.parametrize("name", ["receipt", "receipts", "till_receipt",
                                  "expense_receipt", "sales_receipt"])
def test_receipt_aliases(name):
    from validators import family_of
    assert family_of(name) == "receipt"


@pytest.mark.parametrize("label,want", [
    ("Subtotal", "subtotal"), ("Sales Tax", "tax"), ("Tip", "charge"),
    ("Gratuity", "charge"), ("Service Charge", "charge"), ("Coupon", "discount"),
    ("Total", "total"), ("Amount Due", "total"), ("Cash Tendered", ""),
    ("Change", ""), ("Total Paid", ""), ("Card Payment", ""), ("Store Number", "")])
def test_receipt_roles(label, want):
    from receipt_validators import role
    assert role(label) == want
