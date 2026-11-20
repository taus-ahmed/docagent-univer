"""Run B, B1 - fillable-form fields as a first-class lane.

Offline: every model answer here is scripted. The five fillable fixtures are
the committed acceptance PDFs, scored against tests/golden.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.contract import run_a_driver as D  # bootstraps sys.path

import form_fields as FF  # noqa: E402
import llm_contract as C  # noqa: E402
from connectors.base import LLMResponse  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "tests" / "fixtures" / "acceptance" / "source_docs"
GOLDEN = ROOT / "tests" / "golden"

FORMS = [
    ("w2/irs_w2_mod11.pdf", "W2_Full", "w2", "irs_w2_mod11"),
    ("w2/irs_w2_2012.pdf", "W2_Full", "w2", "irs_w2_2012"),
    ("1099/irs_1099nec_ellis.pdf", "F1099_NEC_MISC", "form_1099", "irs_1099nec_ellis"),
    ("1099/irs_1099int_mod3.pdf", "F1099_INT_DIV", "form_1099", "irs_1099int_mod3"),
    ("1099/irs_1098_joe_angela.pdf", "F1098", "form_1098", "irs_1098_joe_angela"),
]
# Golden values a form WIDGET holds (the rest are printed text the model reads).
NOT_WIDGETS = {"Tax Year", "Form Type"}


def _run(rel, sheet, doc_type, answer=None, prompts=None):
    from core.preprocessor import preprocess_file
    from slot_extractor import run_slot_extraction

    path = DOCS / rel
    doc = preprocess_file(path)
    parsed = answer if answer is not None else {"fields": {}, "tables": {}}

    def extract(**kw):
        if prompts is not None:
            prompts.append(kw.get("prompt", ""))
        return LLMResponse(raw_text=json.dumps(parsed), parsed_json=json.loads(json.dumps(parsed)),
                           success=True, model_used="offline-scripted")

    n = len(doc.page_texts)
    with C.collect_attempts(fresh=True):
        return run_slot_extraction(
            SimpleNamespace(llm=SimpleNamespace(extract=extract)), path,
            {"layout": D.template_grid(sheet)}, None, page_images=[],
            doc_text=doc.extracted_text, doc_text_pages=doc.page_texts,
            file_type="digital_pdf", default_doc_type=doc_type, start=0.0,
            page_lines=doc.page_lines,
            page_origins={i + 1: o for i, o in enumerate(doc.page_origins)},
            page_numbers=list(range(1, n + 1)), widget_values=doc.widget_values,
            form_fields=doc.form_fields,
            unreadable={"ocr_failed": doc.ocr_failed_pages,
                        "ocr_zero": doc.ocr_zero_word_pages})[0].extracted_data


def _golden(name):
    return json.loads((GOLDEN / f"{name}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("rel,sheet,doc_type,truth", FORMS, ids=[f[3] for f in FORMS])
def test_an_empty_model_answer_is_completed_from_the_form_fields(rel, sheet, doc_type, truth):
    from tests.tools.score_runs import values_equal

    data = _run(rel, sheet, doc_type)
    by_label = {k: v.get("value") for k, v in data["extracted_data"].items()}
    gold = _golden(truth)
    checked = 0
    for label, exp in gold["headers"].items():
        if label in NOT_WIDGETS:
            continue
        assert values_equal(exp["value"], by_label.get(label), exp["type"]), \
            (label, exp["value"], by_label.get(label))
        checked += 1
    assert checked >= 5
    # absent slots stay plainly empty
    for label in gold["absent_slots"]:
        assert not str(by_label.get(label) or "").strip(), label
    prov = data["field_provenance"]
    refs = {v.get("ref"): k for k, v in data["extracted_data"].items()}
    # every widget slot is machine-read from its form field; Form Type, which
    # no widget holds, is read from the printed form title (overnight A5)
    # and must then equal the golden value
    for ref, p in prov.items():
        if refs.get(ref) == "Form Type":
            assert p.get("machine_read") == "form_title", p
            assert values_equal(gold["headers"]["Form Type"]["value"],
                                by_label.get("Form Type"), "identifier")
        else:
            assert p.get("machine_read") == "form_field", (refs.get(ref), p)


def test_the_prompt_carries_label_value_pairs_and_only_for_forms():
    prompts = []
    _run("w2/irs_w2_mod11.pdf", "W2_Full", "w2", prompts=prompts)
    assert "1 Wages, tips, other compensation: 10535" in prompts[0]
    assert "b Employer identification number (EIN): 10-8763214" in prompts[0]
    assert "match each slot to its form field by MEANING" in prompts[0]

    from slot_extractor import build_prompt, enumerate_slots
    slots = enumerate_slots(D.template_grid("W2_Full"))
    assert build_prompt(slots, ["page"], "w2") == build_prompt(slots, ["page"], "w2", "")
    assert "FORM FIELDS" not in build_prompt(slots, ["page"], "w2")


def test_a_strong_match_overrules_a_contradicting_answer_and_says_so():
    from slot_extractor import enumerate_slots
    slots = {f["row_label"]: f["slot_id"]
             for f in enumerate_slots(D.template_grid("W2_Full"))["fields"]}
    answer = {"fields": {
        # what the live run returned in B0: the widget lines with Box 1 in between
        slots["Box c Employer Name"]: {
            "value": "R AND R FARM\n10535\n21 BEECH TREE FARM\nANYTOWN, US 10111",
            "source": "R AND R FARM", "page": 1},
        # same value, other notation: the widget's own form is kept
        slots["Box 1 Wages Tips Other Compensation"]: {
            "value": "$10,535.00", "source": "10535", "page": 1},
    }, "tables": {}}
    data = _run("w2/irs_w2_mod11.pdf", "W2_Full", "w2", answer=answer)
    got = {k: v["value"] for k, v in data["extracted_data"].items()}
    assert got["Box c Employer Name"] == "R AND R FARM"
    assert got["Box 1 Wages Tips Other Compensation"] == "10535"
    assert any("machine-read" in n and "the model read" in n
               for n in data["validation_notes"])
    assert data["validation"]["flagged_fields"] == []


def test_matching_is_by_box_and_meaning_never_by_a_generic_word():
    entries = [
        {"label": "1 Wages, tips, other compensation", "extra": "", "value": "10535",
         "box": "1", "role": "whole", "kind": "text", "page": 1},
        {"label": "RECIPIENT'S federal identification number", "extra": "",
         "value": "36-1234567", "box": None, "role": "whole", "kind": "text", "page": 1},
    ]
    assert FF.match("Box 1 Wages Tips Other Compensation", entries)[0]["value"] == "10535"
    assert FF.match("Box 2 Federal Income Tax Withheld", entries)[0] is None
    assert FF.match("Box 1 Rents", entries)[0] is None
    assert FF.match("Recipient TIN", entries)[0]["value"] == "36-1234567"
    assert FF.match("Account Number", entries)[0] is None      # 'number' alone


def test_a_document_without_widgets_is_asked_exactly_what_it_was_asked():
    from core.preprocessor import preprocess_file
    doc = preprocess_file(DOCS / "purchase_order" / "flowparse_po.pdf")
    assert doc.form_fields == {}


# ── B5: more entries than slots ──────────────────────────────────────────────

def test_pitt_box_14_second_entry_is_never_dropped_silently():
    from slot_extractor import enumerate_slots
    ids = {f["row_label"]: f["slot_id"]
           for f in enumerate_slots(D.template_grid("W2_Full"))["fields"]}
    answer = {"fields": {ids["Box 14 Other"]: {
        "value": "1600.00", "source": "14 Other 1600.00 14H", "page": 1}},
        "tables": {}}
    data = _run("w2/pitt_sample_w2.pdf", "W2_Full", "w2", answer=answer)
    assert data["extracted_data"]["Box 14 Other"]["value"] == "1600.00"
    flags = [f for f in data["validation"]["flagged_fields"] if f["ref"] == "Box 14 Other"]
    assert [f["reason"] for f in flags] == ["Box 14 has a second entry 52.00 X that has no slot"]
    assert data["validation"]["overflow_entries"] == [
        {"slot": "Box 14 Other", "amount": "52.00", "code": "X"}]


def test_stacked_entries_are_read_down_their_own_column():
    import source_inventory as SI
    lines = D.words(1, ["14 Other 1600.00 14H", "52.00 14X"])
    # the stacked entry sits in the same column as the first one
    for w in lines[1]:
        w["x0"] += 6 * len("14 Other ") + 12
        w["x1"] += 6 * len("14 Other ") + 12
    assert [(e["amount"], e["code"]) for e in
            SI.stacked_entries(lines, "Box 14 Other", "1600.00")] == \
        [("1600.00", "H"), ("52.00", "X")]
    assert SI.stacked_entries(lines, "Box 14 Other", "not an amount") == []
