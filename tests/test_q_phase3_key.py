"""Run Q Phase 3, item 8: the replay answer key built from human review.

A value a person corrected is ground truth; so is every value a person left
standing in a document they marked reviewed. Synthetic documents in the
shape `tools/export_raw_responses.py` stores.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from replay_key import key_from_doc, score_doc, norm  # noqa: E402


def _doc(ed, name="a.pdf"):
    return {"original_filename": name, "extraction_json": ed}


REVIEWED = {
    "review": {"document_reviewed": True, "by": "x"},
    "extracted_data": {"Bank Name": {"value": "Carson Bank", "confidence": "edited"},
                       "Account": {"value": "123", "confidence": "high"},
                       "Branch": {"value": "", "confidence": "low"}},
    "table_rows": [{"Date": "07/22", "Amount": "13.17", "_confidence": "high"},
                   {"Date": "07/23", "Amount": "5.00", "_confidence": "low"}],
}


def test_a_reviewed_document_keys_every_value_it_kept():
    k = key_from_doc(_doc(REVIEWED))
    assert k["fields"] == {"bank name": "Carson Bank", "account": "123"}
    assert k["tables"]["table"] == [{"Date": "07/22", "Amount": "13.17"},
                                    {"Date": "07/23", "Amount": "5.00"}]
    assert k["kind"] == "reviewed"


def test_an_unreviewed_document_keys_only_what_a_person_corrected():
    ed = {"extracted_data": {"Bank Name": {"value": "Carson Bank Of So", "confidence": "edited"},
                             "Account": {"value": "123", "confidence": "high"}},
          "table_rows": [{"Memo": "13.17", "Date": "x", "_edited": ["Memo"]},
                         {"Memo": "9", "Date": "y"}]}
    k = key_from_doc(_doc(ed))
    assert k["fields"] == {"bank name": "Carson Bank Of So"}
    assert k["cells"] == [("table", 0, "Memo", "13.17")]
    assert k["tables"] == {}


def test_no_review_and_no_edit_is_no_key():
    assert key_from_doc(_doc({"extracted_data": {"A": {"value": "1"}}})) is None


def test_score_counts_right_wrong_missing_and_extra():
    k = key_from_doc(_doc(REVIEWED))
    replay = {"extracted_data": {"Bank Name": {"value": "Carson  bank"},     # right (spacing, case)
                                 "Account": {"value": ""},                  # missing
                                 "Branch": {"value": "Main"}},              # extra
              "table_rows": [{"Date": "07/22", "Amount": "13.17"},          # right row: 2 right
                             {"Date": "07/23", "Amount": "50.00"},          # 1 right, 1 wrong
                             {"Date": "07/24", "Amount": "1.00"}]}          # extra row
    s = score_doc(k, replay)
    assert (s["right"], s["wrong"], s["missing"], s["extra"]) == (4, 1, 1, 3)


def test_an_edited_cell_is_scored_at_its_row():
    k = key_from_doc(_doc({"table_rows": [{"Memo": "13.17", "_edited": ["Memo"]}]}))
    assert score_doc(k, {"table_rows": [{"Memo": "13.17"}]})["right"] == 1
    assert score_doc(k, {"table_rows": [{"Memo": "Principal 13.17"}]})["wrong"] == 1
    assert score_doc(k, {"table_rows": []})["missing"] == 1


def test_norm_ignores_spacing_and_case_only():
    assert norm(" A  b\n") == norm("a B")
    assert norm("1,000") != norm("1000")
