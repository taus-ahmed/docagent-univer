"""Run Q, Q12 — a failure always says why; a blank fillable form needs no model.

Jobs 68 and 70 (smartsheet_mileage, a blank expense-report template: two
1885 x 1457 pt pages, 268 AcroForm widgets, none filled) failed on staging
after ~42 s showing only "1 of 1 document(s) failed." The live cause cannot
be recovered (no stored reason). Offline the shape extracts fine; what is
fixed here: (a) a failed document or job always carries a reason - the error
CLASS and a plain sentence, never document content; (b) a blank fillable form
of that shape is answered without a model call and finishes READY as a
blank form; (c) an unparseable answer is retried, then a clear failure.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from tests import run_q_support as Q


def _blank_form(path, pages=2, w=1885.0, h=1457.0, widgets=268):
    from pypdf import PdfWriter
    from pypdf.generic import (ArrayObject, BooleanObject, DecodedStreamObject,
                               DictionaryObject, FloatObject, NameObject,
                               NumberObject, TextStringObject)
    writer = PdfWriter()
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                             NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    font_ref = writer._add_object(font)
    labels = ["Employee Name", "Department", "Date", "Start Location", "Destination",
              "Purpose", "Miles", "Rate", "Amount", "Approved By"]
    annots_all, fields = [], ArrayObject()
    per_page = widgets // pages
    for p in range(pages):
        page = writer.add_blank_page(w, h)
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})})
        ops = [f"BT /F1 18 Tf 60 {h - 60} Td (MILEAGE EXPENSE REPORT) Tj ET"]
        annots = ArrayObject()
        for k in range(per_page + (widgets % pages if p == pages - 1 else 0)):
            col, row = k % 10, k // 10
            x, y = 60 + col * 180, h - 120 - row * 40
            ops.append(f"BT /F1 9 Tf {x} {y + 14} Td ({labels[col]}) Tj ET")
            a = DictionaryObject({
                NameObject("/Type"): NameObject("/Annot"),
                NameObject("/Subtype"): NameObject("/Widget"),
                NameObject("/FT"): NameObject("/Tx"),
                NameObject("/T"): TextStringObject(f"f{p}_{k}"),
                NameObject("/F"): NumberObject(4),
                NameObject("/Rect"): ArrayObject([FloatObject(v) for v in
                                                  (x, y, x + 160, y + 12)]),
                NameObject("/P"): page.indirect_reference})
            ref = writer._add_object(a)
            annots.append(ref)
            fields.append(ref)
        s = DecodedStreamObject()
        s.set_data("\n".join(ops).encode("latin-1"))
        page[NameObject("/Contents")] = writer._add_object(s)
        page[NameObject("/Annots")] = annots
        annots_all.append(annots)
    writer._root_object[NameObject("/AcroForm")] = writer._add_object(DictionaryObject({
        NameObject("/Fields"): fields, NameObject("/NeedAppearances"): BooleanObject(True)}))
    with open(path, "wb") as fh:
        writer.write(fh)
    return path


TPL = Q.template(fields=["Employee Name", "Department", "Total Amount"],
                 tables=[(None, ["Date", "Start Location", "Destination", "Miles", "Amount"])],
                 doc_type="expense_report")


def test_the_synthetic_fixture_has_the_shape_of_smartsheet_mileage(tmp_path):
    import text_layer as TL
    import pdfplumber
    p = _blank_form(tmp_path / "mileage.pdf")
    assert TL.widget_census(p) == (268, 0)
    with pdfplumber.open(p) as pdf:
        assert len(pdf.pages) == 2 and round(pdf.pages[0].width) == 1885


def test_a_blank_fillable_form_finishes_done_without_a_model_call_reconstructed(tmp_path):
    p = _blank_form(tmp_path / "mileage.pdf")
    calls = []

    def fn(prompt):
        calls.append(prompt)
        return {"fields": {}, "tables": {}}
    (r,) = Q.run(p, TPL, fn)
    ed = r.extracted_data
    assert r.success, r.error
    assert calls == [], "the model was asked about a form with nothing filled"
    assert ed["document_state"] == "READY", ed.get("attention")
    assert ed.get("blank_form") is True
    assert not any(str(v).strip() for v in ed["extracted_fields"].values())
    assert "the model was not asked" in " ".join(ed["validation_notes"])


def test_the_real_smartsheet_mileage_needs_no_slot_call_real(tmp_path):
    f = Q.need_source("smartsheet_mileage.pdf")
    calls = []
    (r,) = Q.run(f, TPL, lambda p: calls.append(p) or {"fields": {}, "tables": {}})
    assert r.success and calls == []
    assert r.extracted_data["document_state"] == "READY"


def test_one_filled_widget_still_asks_the_model(tmp_path):
    import text_layer as TL
    p = _blank_form(tmp_path / "m.pdf")
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import NameObject, TextStringObject
    rd = PdfReader(str(p))
    wr = PdfWriter(clone_from=rd)
    a = wr.pages[0]["/Annots"][0].get_object()
    a[NameObject("/V")] = TextStringObject("Alice Rivera")
    with open(tmp_path / "filled.pdf", "wb") as fh:
        wr.write(fh)
    assert TL.widget_census(tmp_path / "filled.pdf") == (268, 1)


# ── (c) an unreadable answer: retried once, then a clear, reasoned failure ──

def test_an_unparseable_answer_is_retried_then_a_clear_failure(tmp_path):
    from tests.harness import bootstrap as bs
    bs.bootstrap()
    import extractor
    pdf = Q.make_pdf(tmp_path / "inv.pdf", [[(72, 700, "Invoice Number INV-1")]])
    seen = []

    def extract(prompt="", system_instruction="", **kw):
        seen.append(1)
        return SimpleNamespace(success=True, parsed_json=None, raw_text='{"fields": {"F1": ',
                               tokens_used=0, model_used="m", error="", error_kind=None,
                               finish_reason="MAX_TOKENS", attempts=[])
    (r,) = extractor.run_extraction(SimpleNamespace(llm=SimpleNamespace(extract=extract)),
                                    pdf, Q.template(fields=["Invoice Number"], doc_type="invoice"))
    assert len(seen) >= 2                          # retried as designed
    assert not r.success
    assert r.extracted_data["document_state"] == "FAILED"
    assert r.error and "no usable JSON" in r.error


def test_a_failed_document_with_no_error_text_still_gets_a_reason():
    from app.services.job_worker import failure_reason_text
    res = SimpleNamespace(success=False, error="", validation=None,
                          extracted_data={"document_state": "FAILED", "failure_kind": "max_tokens"},
                          extraction_response=None)
    txt = failure_reason_text(res)
    assert "cut off" in txt and txt.startswith("Extraction failed")
    blank = SimpleNamespace(success=False, error="", validation=None, extracted_data={},
                            extraction_response=None)
    assert failure_reason_text(blank).strip()


def test_a_crashed_job_stores_the_error_class_not_its_message(monkeypatch, tmp_path):
    """The thread-level handler stored str(e): empty for an exception with
    no args, and a document's text for one that quotes it."""
    import app.services.job_worker as JW
    src = open(JW.__file__, encoding="utf-8").read()
    assert "job.error_message = str(e)" not in src
    assert "The job stopped on an internal error" in src and "exc_brief(e)" in src
