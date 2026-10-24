"""One reason map, and the review status every screen and export uses.

A reason code that exists in docs/OCR-READER-SEAM-DESIGN.md §12 but has no
label would reach a user as a raw identifier — or, worse, not at all.
"""
import re

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

from app.core import review as R  # noqa: E402


def _section_12_codes():
    text = (bs.REPO_DIR / "docs" / "OCR-READER-SEAM-DESIGN.md").read_text(encoding="utf-8")
    start = text.index("## 12. Review reason codes")
    end = text.index("Document-level facts", start)
    return re.findall(r"^\| `([a-z_]+)` \|", text[start:end], flags=re.M)


def test_section_12_is_parsed():
    codes = _section_12_codes()
    assert "ocr_origin" in codes and "thin_text_layer" in codes
    assert len(codes) >= 17


def test_every_section_12_code_has_a_label_and_a_tooltip():
    missing = [c for c in _section_12_codes() if c not in R.REASONS]
    assert not missing, f"add these to app/core/review.py REASONS: {missing}"
    for code, (label, tip) in R.REASONS.items():
        assert label.strip() and tip.strip() and len(label) <= 60, code


def test_an_unknown_code_is_shown_not_hidden():
    label, tip = R.reason_text("brand_new_check")
    assert "brand_new_check" in label and "brand_new_check" in tip


@pytest.mark.parametrize("value,level,kw,status,resolved", [
    ("$10.00", "high", {}, "verified", True),
    ("$10.00", "grounded", {}, "grounded", True),
    ("$10.00", "unverified", {"review_required": True, "reasons": ["ocr_origin"]}, "unverified", False),
    ("$10.00", "low", {"review_required": True, "reasons": ["grounding_failed"]}, "low", False),
    ("$10.00", "edited", {"review_required": True}, "edited", True),
    ("", "low", {"flagged": True}, "empty_flagged", False),
    ("", None, {}, "empty", True),
    ("x", "medium", {}, "unknown", False),
    # a confident level that still owes a review is not resolved
    ("$10.00", "high", {"review_required": True, "reasons": ["amount_unreadable"]}, "verified", False),
    # a person marked it reviewed
    ("$10.00", "low", {"review_required": True, "reviewed": True}, "low", True),
])
def test_value_status(value, level, kw, status, resolved):
    st = R.value_status(value, level, **kw)
    assert (st["status"], st["resolved"]) == (status, resolved)


def _stored():
    return {
        "extracted_fields": {"B2": "$5.00", "B3": "", "B4": "ACME"},
        "slot_map": {"fields": [{"ref": "B2", "row_label": "Total"},
                                {"ref": "B3", "row_label": "Date"},
                                {"ref": "B4", "row_label": "Payee"}],
                     "tables": [{"name": "table"}]},
        "field_provenance": {
            "B2": {"review_required": True, "review_reasons": ["ocr_origin"], "page": 1},
            "B3": {"review_required": False, "review_reasons": [], "page": None},
            "B4": {"review_required": False, "review_reasons": [], "page": 1}},
        "validation": {"confidence_map": {"B2": "unverified", "B3": "low", "B4": "high"},
                       "flagged_fields": [{"ref": "Date", "value": "", "reason": "x"}]},
        "table_rows": [{"Item": "Pens", "Amount": "$5.00", "_confidence": "low",
                        "_review_required": True, "_review_reasons": ["totals_mismatch"],
                        "_page": 1}],
    }


def test_document_values_cover_fields_and_cells():
    vals = R.document_values(_stored())
    by = {v["label"]: v for v in vals}
    assert by["Total"]["status"] == "unverified" and not by["Total"]["resolved"]
    assert by["Date"]["status"] == "empty_flagged"
    assert by["Payee"]["status"] == "verified" and by["Payee"]["resolved"]
    cells = [v for v in vals if v["kind"] == "cell"]
    assert {c["column"] for c in cells} == {"Item", "Amount"}
    assert all(c["reasons"] == ["totals_mismatch"] for c in cells)
    s = R.summarise(vals)
    assert s == {"values": 5, "needs_review": 4, "low": 2, "unverified": 1,
                 "empty_flagged": 1}


def test_a_reviewed_document_resolves_every_value():
    ed = _stored()
    ed["review"] = {"document_reviewed": True}
    assert R.summarise(R.document_values(ed))["needs_review"] == 0


def test_a_row_edit_is_edited_and_resolved():
    ed = _stored()
    ed["table_rows"][0]["_edited"] = ["Amount"]
    amount = next(v for v in R.document_values(ed) if v.get("column") == "Amount")
    assert amount["status"] == "edited" and amount["resolved"]


def test_hostile_input_does_not_raise():
    for ed in (None, {}, {"slot_map": None}, {"table_rows": [None, 3, "x"]},
               {"extracted_data": {"A": None, "B": {"value": None}}}):
        R.summarise(R.document_values(ed))
