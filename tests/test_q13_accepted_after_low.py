"""Run Q, Q13 — values accepted after a Low flag are counted, never invisible.

Jobs 57, 64 and 66 exported "Nothing needs review" after a whole-document
review mark accepted values the machine had flagged Low; nothing in the
Legend or the job said so. Reconstructed: a record with one Low value and
one clean value, then the whole-document mark.
"""
from __future__ import annotations

from types import SimpleNamespace

from tests.harness import bootstrap as bs

bs.bootstrap()


def _ed(reviewed: bool):
    return {
        "extraction_method": "slot_directed", "template_type": "slot",
        "extracted_fields": {"B1": "INV-1", "B2": "230.25"},
        "extracted_data": {"Invoice": {"value": "INV-1", "confidence": "high", "ref": "B1"},
                           "Subtotal": {"value": "230.25", "confidence": "low", "ref": "B2"}},
        "slot_map": {"fields": [{"ref": "B1", "row_label": "Invoice", "row": 0, "col": 1},
                                {"ref": "B2", "row_label": "Subtotal", "row": 1, "col": 1}],
                     "tables": []},
        "field_provenance": {"B1": {"source": "Invoice INV-1", "page": 1, "grounded": True},
                             "B2": {"source": "Subtotal 230.25", "page": 1, "grounded": True}},
        "validation": {"confidence_map": {"B1": "high", "B2": "low"},
                       "flagged_fields": [{"ref": "Subtotal", "value": "230.25",
                                           "reason": "the 17 line item(s) sum to 230.55, not the subtotal 230.25"}]},
        "review": {"document_reviewed": reviewed},
        "attention": [],
    }


def test_summary_counts_low_values_accepted_as_they_stood_reconstructed():
    from app.core import review as R
    before = R.summarise(R.export_values(_ed(False)))
    after = R.summarise(R.export_values(_ed(True)))
    assert before["low"] == 1 and before["accepted_after_low"] == 0
    assert after["needs_review"] == 0 and after["accepted_after_low"] == 1


def test_legend_says_how_many_were_accepted_after_low():
    import openpyxl
    from app.services.excel_cells import _add_review_legend
    wb = openpyxl.Workbook()
    ed = _ed(True)
    _add_review_legend(wb, [SimpleNamespace(filename="calif_restaurant_2006.jpg", id=1,
                                            model_used="m", get_extracted_data=lambda: ed)])
    rows = [r for r in wb["Legend"].iter_rows(values_only=True)]
    text = " ".join(str(v) for r in rows for v in r if v is not None)
    assert "1 value accepted after being flagged Low" in text
    head = next(r for r in rows if r and r[0] == "Document")
    assert "Accepted after Low" in head
    doc = next(r for r in rows if r and r[0] == "calif_restaurant_2006.jpg")
    assert doc[list(head).index("Accepted after Low")] == 1
