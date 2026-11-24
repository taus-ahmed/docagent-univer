"""Run Q Phase 3, item 2 (Q8 / cause 3): what an OCR reading may and may not keep.

(a) A money or number slot never keeps letters or symbols inside its figure:
    `1O,5S0.00` is flagged with the OCR-confusable reading (`10,550.00`),
    never coerced to it.
(b) An embedded OCR layer is grounded against: a value it holds is checked
    (unverified, not Low); a value it does not hold is Low.
(c) A page with no text layer (text drawn as outlines, ADP W-2) raises ONE
    page-level "verify this page against the image" item instead of an amber
    flag on every cell.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tests import run_q_support as Q
from tests.test_q4_false_low import W2, _outlined_pdf, _w2_answer


def _fr():
    import format_rules as FR
    return FR


# ── (a) letters or symbols inside a figure ───────────────────────────────────

@pytest.mark.parametrize("value,label,reading", [
    ("1O,5S0.00", "Total Amount", "10,550.00"),
    ("12S.00", "Box 1 Wages Tips Other Compensation", "125.00"),
    ("$4l.2O", "Net Pay", "$41.20"),
    ("1O", "Qty", "10"),
    ("3B.5", "Hours", "38.5"),
])
def test_a_figure_holding_ocr_letters_is_flagged_with_the_confusable_reading(value, label, reading):
    ok, norm, why = _fr().check_type(value, label)
    assert not ok and norm is None
    assert reading in why


def test_a_figure_holding_a_stray_symbol_is_flagged():
    ok, _n, why = _fr().check_type("1,2#4.00", "Total Amount")
    assert not ok and "symbol" in why


@pytest.mark.parametrize("value,label", [
    ("$1,234.56", "Total Amount"),
    ("(1,234.56)", "Balance"),
    ("1,234.56 CR", "Balance"),
    ("USD 100.00", "Total"),
    ("-12.50", "Net Pay"),
    ("40", "Qty"),
    ("7.5", "Hours"),
    ("ABC-123", "Invoice Number"),        # not a money or number slot
    ("Net 30", "Payment Terms"),
])
def test_ordinary_figures_and_other_slots_still_pass(value, label):
    ok, _n, why = _fr().check_type(value, label)
    assert ok, why


def test_a_letter_word_beside_the_figure_is_not_ocr_noise():
    # a word on its own (a currency code, CR/DR) is not a misread digit
    assert _fr().check_type("100.00 EUR", "Amount")[0]


def test_the_flag_reaches_the_value_on_a_scan(tmp_path):
    f = Q.make_pdf(tmp_path / "r.pdf", [[(72, 700, "Total 12S.00")]])
    tpl = Q.template(fields=["Total Amount"])

    def ans(prompt):
        ids = Q.slot_ids(prompt)
        return {"fields": {ids["Total Amount"]: {"value": "12S.00",
                                                 "source": "Total 12S.00", "page": 1}},
                "tables": {}}
    (r,) = Q.run(f, tpl, ans)
    ed = r.extracted_data
    assert ed["extracted_data"]["Total Amount"]["confidence"] == "low"
    assert ed["extracted_data"]["Total Amount"]["value"] == "12S.00"     # never coerced
    reasons = [x["reason"] for x in ed["validation"]["flagged_fields"]
               if x.get("ref") == "Total Amount"]
    assert any("125.00" in x for x in reasons), reasons


# ── (b) an embedded OCR layer is grounded against ────────────────────────────

def _pre_ocr_line(f):
    from core.preprocessor import preprocess_file
    doc = preprocess_file(f)
    assert doc.page_origins[0] == "pre_ocr"
    for line in doc.page_texts[0].splitlines():
        if any(c.isdigit() for c in line) and len(line.split()) >= 2:
            return line.strip()
    pytest.skip("no figure line in the embedded layer")


def test_embedded_ocr_layer_is_grounded_against_real():
    f = Q.need_source("utah_paystub_2.pdf")
    line = _pre_ocr_line(f)
    tok = next(t for t in line.split() if any(c.isdigit() for c in t))
    tpl = Q.template(fields=["Reference"])

    def on_page(prompt):
        return {"fields": {Q.slot_ids(prompt)["Reference"]: {
            "value": tok, "source": line, "page": 1}}, "tables": {}}

    def off_page(prompt):
        return {"fields": {Q.slot_ids(prompt)["Reference"]: {
            "value": "98765432", "source": "Reference 98765432", "page": 1}}, "tables": {}}
    (r,) = Q.run(f, tpl, on_page)
    p = next(iter(r.extracted_data["field_provenance"].values()))
    assert r.extracted_data["extracted_data"]["Reference"]["confidence"] == "unverified"
    assert "grounding_failed" not in p["review_reasons"]
    (r,) = Q.run(f, tpl, off_page)
    assert r.extracted_data["extracted_data"]["Reference"]["confidence"] == "low"


# ── (c) one page-level item for a page with no text layer ────────────────────

W2_3 = Q.template(fields=["Wages Tips Other Compensation", "Federal Income Tax Withheld",
                          "Social Security Wages"], doc_type="w2")


def _w2_three(prompt):
    ids = Q.slot_ids(prompt)
    out = {}
    for label, v in (("Wages Tips Other Compensation", "23500.00"),
                     ("Federal Income Tax Withheld", "2100.00"),
                     ("Social Security Wages", "23500.00")):
        out[ids[label]] = {"value": v, "source": f"{label} {v}", "page": 1}
    return {"fields": out, "tables": {}}


def _statuses(ed):
    from app.core import review as R
    return {v["label"]: v for v in R.document_values(ed) if v["kind"] == "field"}


def test_an_outlined_page_raises_one_page_item_not_a_flag_per_cell(tmp_path):
    f = _outlined_pdf(tmp_path / "w2.pdf")
    (r,) = Q.run(f, W2_3, _w2_three)
    ed = r.extracted_data
    flags = ed["validation"]["flagged_fields"]
    page_items = [x for x in flags if "verify this page against the image" in x["reason"].lower()]
    assert len(page_items) == 1 and page_items[0]["ref"] == "page 1"
    assert "3 value" in page_items[0]["reason"]
    labels = {"Wages Tips Other Compensation", "Federal Income Tax Withheld", "Social Security Wages"}
    assert not [x for x in flags if x.get("ref") in labels]
    st = _statuses(ed)
    for label in labels:
        assert ed["extracted_data"][label]["confidence"] == "unverified"   # honest level kept
        assert st[label]["status"] == "page_check"
    assert ed["needs_review"] is True
    assert any("verify this page against the image" in n.lower() for n in ed["validation_notes"])


def test_a_page_check_value_is_not_painted_amber_but_says_why():
    from app.core import review as R
    st = R.value_status("23500.00", "unverified", review_required=True, reasons=["outlined_text"])
    assert st["status"] == "page_check"
    word, fill, note = R.export_mark(st)
    assert fill is None
    assert "verify" in note.lower() and "page" in note.lower()


def test_another_failed_check_on_an_outlined_page_still_stands():
    from app.core import review as R
    st = R.value_status("23500.00", "low", review_required=True,
                        reasons=["outlined_text", "payslip_mismatch"])
    assert st["status"] == "low" and not st["resolved"]
    # a scan's own value (OCR origin alone) still owes its own look
    st = R.value_status("23500.00", "unverified", review_required=True,
                        reasons=["ocr_origin"])
    assert st["status"] == "unverified"
    # an outlined page read by OCR: the page item carries it
    st = R.value_status("23500.00", "unverified", review_required=True,
                        reasons=["ocr_origin", "outlined_text"])
    assert st["status"] == "page_check"


def test_outlined_page_real_has_one_page_item():
    f = Q.need_source("adp_w2_interactive.pdf")
    (r,) = Q.run(f, W2, _w2_answer)
    flags = r.extracted_data["validation"]["flagged_fields"]
    assert sum("verify this page against the image" in x["reason"].lower() for x in flags) == 1
    assert not [x for x in flags if x.get("ref") == "Wages Tips Other Compensation"]
