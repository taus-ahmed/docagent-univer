"""B3 — no false completeness reasons on forms with blank boxes.

Job 49 (irs_w2_2012, fillable, 11 widgets filled): "The page has about 2 line
items but 0 were extracted (table 'Box 12 Codes', 'State and Local')" and two
"did not include the rows of table" reasons. Job 52 (irs_1099int_mod3,
fillable): "11 of 18 field slots are empty while the labels of 7 of them are
printed". mammoth_2pg (text layer): "8 of 13 field slots are empty ...". All
false — the boxes are blank in the document. On a fillable form an empty
widget confirms the slot empty: no reason and no second request.
"""

from __future__ import annotations

import pytest

from tests import overnight_helpers as H
from tests.contract import run_a_driver as D
from tests.test_overnight_a4 import MAMMOTH, mammoth_fields, mammoth_grid, mammoth_rows


def _blank_answer(g):
    return {"fields": {}, "tables": {t["name"]: [] for t in H.slots(g)["tables"]}}


@pytest.mark.parametrize("rel,sheet,doc_type", [
    ("w2/irs_w2_2012.pdf", "W2_Full", "w2"),
    ("1099/irs_1099int_mod3.pdf", "F1099_INT_DIV", "1099"),
])
def test_fillable_form_blank_boxes_raise_no_reason_and_no_second_request(rel, sheet, doc_type):
    g = D.template_grid(sheet)
    data, calls = H.run(rel, g, _blank_answer(g), doc_type=doc_type)
    assert H.reasons(data) == [], H.reasons(data)
    assert data["document_state"] == "READY"
    assert len(calls) == 1, "an empty box needs no second request"
    # every filled widget still reaches a cell
    assert len([v for v in data["extracted_fields"].values() if str(v).strip()]) >= 5


def test_mammoth_has_no_false_field_count_reason():
    g = mammoth_grid()
    name = H.table_name(g, "Transactions")
    answer = {"fields": mammoth_fields(g),
              "tables": {name: mammoth_rows(1) + mammoth_rows(2)}}
    data, _ = H.run(MAMMOTH, g, answer, doc_type="bank_statement")
    assert not any("field slots are empty" in r for r in H.reasons(data)), H.reasons(data)


def test_a_text_layer_label_with_its_value_beside_it_still_counts():
    """The field-count reason still fires where labels print values beside
    them and the extraction left them out (job 25's shape)."""
    g = mammoth_grid()
    data, _ = H.run(MAMMOTH, g, {"fields": {}, "tables": {}}, doc_type="bank_statement")
    assert data["document_state"] != "READY"
