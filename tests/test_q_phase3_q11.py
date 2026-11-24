"""Run Q Phase 3, item 4 (Q11): an ignored form and a wrong template are SAID.

(a) job 53: a composite brokerage statement prints Forms 1099-DIV, -MISC,
    -INT and -B; the template ("1099-INT and DIV Organizer") covers two. The
    other two were silently not extracted; now a visible note names them.
(b) job 59: virtus_1099b.pdf run with the "PO - Purchase Order Full"
    template. Every slot came back empty or wrong with no word that the
    template does not fit; now: "This does not look like a Purchase Order".
Each has its twin: a Purchase Order under the PO template, and a document
whose forms the template names, raise nothing.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from tests import run_q_support as Q

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))


def _text(name):
    import pdfplumber
    with pdfplumber.open(str(Q.need_source(name))) as pdf:
        return "\n".join(p.extract_text() or "" for p in pdf.pages)


def test_forms_printed_on_a_composite_statement():
    import template_fit as F
    forms = F.printed_forms(_text("irs6744_brokerage_1099DIV_MISC_INT_B.pdf"))
    assert {"1099-DIV", "1099-MISC", "1099-INT", "1099-B"} <= set(forms)


def test_forms_the_template_does_not_cover_are_named():
    import template_fit as F
    tpl = {"name": "Tax - 1099-INT and DIV Organizer", "cells_text": ["Payer Name", "Form Type"]}
    ignored = F.ignored_forms(_text("irs6744_brokerage_1099DIV_MISC_INT_B.pdf"), tpl)
    assert ignored == ["1099-MISC", "1099-B"]


def test_a_template_naming_no_form_says_nothing():
    import template_fit as F
    assert F.ignored_forms(_text("irs6744_brokerage_1099DIV_MISC_INT_B.pdf"),
                           {"name": "Brokerage", "cells_text": ["Payer Name"]}) == []


def test_a_wrong_template_type_is_named():
    import template_fit as F
    msg = F.type_mismatch(_text("virtus_1099b.pdf"), "purchase_order")
    assert msg and "does not look like a Purchase Order" in msg


def test_the_right_template_type_is_quiet():
    import template_fit as F
    assert F.type_mismatch(_text("portland_po_distributed.pdf"), "purchase_order") is None
    assert F.type_mismatch(_text("virtus_1099b.pdf"), "other") is None


def _replay(job, name):
    import replay_raw
    replay_raw._setup()
    rep = replay_raw.load_job(job)
    doc = next(d for d in rep["docs"] if d["original_filename"] == name)
    td = replay_raw.template_data_of(rep["template"])
    return [ed for ed, _m, _r in replay_raw.replay_doc(doc, td, Q.need_source(name))]


def _attention(ed):
    return [a["text"] for a in ed.get("attention") or []]


def test_real_job59_po_template_on_a_1099b_is_warned():
    Q.need_answer(59, "virtus_1099b.pdf")
    (ed,) = _replay(59, "virtus_1099b.pdf")
    assert any("does not look like a Purchase Order" in t for t in _attention(ed))
    assert ed["document_state"] == "NEEDS_ATTENTION" and ed["needs_review"]


def test_real_job57_po_template_on_a_po_is_quiet():
    Q.need_answer(57, "portland_po_distributed.pdf")
    for ed in _replay(57, "portland_po_distributed.pdf"):
        assert not any("does not look like" in t for t in _attention(ed))


def test_real_job53_ignored_forms_are_named_in_a_visible_note():
    Q.need_answer(53, "irs6744_brokerage_1099DIV_MISC_INT_B.pdf")
    (ed,) = _replay(53, "irs6744_brokerage_1099DIV_MISC_INT_B.pdf")
    notes = [n for n in ed["validation_notes"] if "1099-MISC" in n and "1099-B" in n]
    assert notes and "not cover" in notes[0]
    flags = [f for f in ed["validation"]["flagged_fields"] if f["ref"] == "document"]
    assert flags and "1099-MISC" in flags[0]["reason"]
    assert ed["needs_review"]
