"""Run Q, Q5 — a blank form is DONE with a plain note; blank boxes are not misses.

Job 81 (irs_w2_2021, a BLANK W-2) came back with 21 grey "empty, flagged"
cells alone, and with 0 inside combined job 83. The cause reproduced here:
the flag depended on whether the model's empty answer QUOTED the label
("the model quoted this label from the page but returned no value") - a
property of one answer, not of the document. A quote holding nothing but
captions is the model showing the box is empty.
"""
from __future__ import annotations

import pytest

from tests import run_q_support as Q

W2 = ["Box 1 Wages, tips, other compensation", "Box 2 Federal income tax withheld",
      "Box 3 Social security wages", "Box 4 Social security tax withheld",
      "Employee's first name and initial"]


def _blank_w2(tmp_path):
    return Q.make_pdf(tmp_path / "w2.pdf", [[
        (72, 750, "Form W-2 Wage and Tax Statement 2021"),
        (72, 720, "1 Wages, tips, other comp."), (300, 720, "2 Federal income tax withheld"),
        (72, 690, "3 Social security wages"), (300, 690, "4 Social security tax withheld"),
        (72, 660, "e Employee's first name and initial"), (300, 660, "Last name"),
        (72, 630, "Copy B - To Be Filed With Employee's FEDERAL Tax Return"),
    ]])


QUOTES = {W2[0]: "1 Wages, tips, other comp. 2 Federal income tax withheld",
          W2[1]: "2 Federal income tax withheld",
          W2[2]: "3 Social security wages 4 Social security tax withheld",
          W2[3]: "4 Social security tax withheld",
          W2[4]: "e Employee's first name and initial Last name"}


def _answer(quoted):
    def fn(prompt):
        ids = Q.slot_ids(prompt)
        return {"fields": {ids[lab]: {"value": "", "source": QUOTES[lab] if quoted else "",
                                      "page": 1, "status": "absent"} for lab in W2},
                "tables": {n: [] for n in Q.table_names(prompt)}}
    return fn


def _greys(ed):
    return sorted(str(f.get("ref")) for f in (ed.get("validation") or {}).get("flagged_fields") or [])


@pytest.mark.parametrize("quoted", [True, False], ids=["answer-quotes-labels", "answer-quotes-nothing"])
def test_a_blank_w2_is_done_with_a_plain_note_reconstructed(tmp_path, quoted):
    (r,) = Q.run(_blank_w2(tmp_path), Q.template(fields=W2, doc_type="w2"), _answer(quoted))
    ed = r.extracted_data
    assert _greys(ed) == [], _greys(ed)
    assert ed["document_state"] == "READY", ed.get("attention")
    assert ed.get("blank_form") is True
    assert "this form is blank" in " ".join(ed["validation_notes"]).casefold()


def test_the_same_blank_form_gives_the_same_result_whatever_the_answer_quoted(tmp_path):
    (a,) = Q.run(_blank_w2(tmp_path), Q.template(fields=W2, doc_type="w2"), _answer(True))
    (b,) = Q.run(_blank_w2(tmp_path), Q.template(fields=W2, doc_type="w2"), _answer(False))
    for k in ("document_state", "blank_form"):
        assert a.extracted_data.get(k) == b.extracted_data.get(k)
    assert _greys(a.extracted_data) == _greys(b.extracted_data)


def test_a_value_printed_beside_its_label_is_still_a_miss(tmp_path):
    pdf = Q.make_pdf(tmp_path / "w2.pdf", [[
        (72, 750, "Form W-2 Wage and Tax Statement 2021"),
        (72, 720, "1 Wages, tips, other comp. 23500.00"), (300, 720, "2 Federal income tax withheld"),
        (72, 690, "3 Social security wages"), (300, 690, "4 Social security tax withheld"),
        (72, 660, "e Employee's first name and initial"), (300, 660, "Last name"),
    ]])
    (r,) = Q.run(pdf, Q.template(fields=W2, doc_type="w2"), _answer(True))
    ed = r.extracted_data
    assert ed.get("blank_form") is not True
    assert W2[0] in _greys(ed)                  # the missed 23500.00 stays visible


def test_a_quote_of_only_captions_is_not_evidence_of_a_value():
    import source_inventory as S
    cw = {"wages", "tips", "other", "compensation", "federal", "income", "tax", "withheld"}
    assert not S._quote_beyond_label("1 Wages, tips, other comp. 2 Federal income tax withheld",
                                     W2[0], cw)
    assert S._quote_beyond_label("1 Wages, tips, other comp. 23500.00", W2[0], cw)
    assert not S._quote_beyond_label("Date: ________", "Date", ())
