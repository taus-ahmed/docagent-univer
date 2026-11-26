"""Run Q Phase 3, item 6: Q4 (e)-(g), false Low on the replayed real answers.

(e) a FORM BOX prints its label on one line and its value on the line below,
    inside the label's box. The model quotes the two as one span
    ("PAYER'S name Livewell Inc.", job 79; "1 Nonemployee compensation
    $ 1,000", job 78). The quote names the label's line, which does not print
    the value, so re-anchoring found no candidate and a value printed
    verbatim was Low. The line directly below, under the label, is the box.
(f) a money box prints `$` at its left edge and the amount at its right
    ("$ 21,000", job 79, x3). The gap after a lone currency symbol is the
    box's width, not a column gutter: it was flagged "two side-by-side
    blocks were merged".
(g) an embedded OCR layer reads `0831/2018` where the page shows 08/31/2018
    (job 62). A value whose digits equal the layer's token, differing only
    in separators, is grounded against the layer (and stays unverified, as
    every value on such a page does).
Each keeps its twin: a value under another box, an amount really across a
gutter, a date whose digits differ, all stay Low.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tests import run_q_support as Q

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))


def _replay(job, name):
    import replay_raw
    replay_raw._setup()
    Q.need_answer(job, name)
    rep = replay_raw.load_job(job)
    doc = next(d for d in rep["docs"] if d["original_filename"] == name)
    td = replay_raw.template_data_of(rep["template"])
    (ed, _m, _r), = replay_raw.replay_doc(doc, td, Q.need_source(name))
    return ed


def _conf(ed, label):
    return ed["extracted_data"][label]["confidence"]


@pytest.fixture(scope="module")
def j79():
    return _replay(79, "irs6744_1099R_ssa1099.pdf")


def test_e_real_form_box_label_above_value(j79):
    assert _conf(j79, "PAYER’S name") != "low"
    assert _conf(j79, "Street address") != "low"


def test_e_real_job78_box1(tmp_path):
    ed = _replay(78, "irs6744_1099NEC_1099K_garcia.pdf")
    assert _conf(ed, "Box 1 Nonemployee Compensation") != "low"


def test_f_real_currency_symbol_at_the_box_edge_is_not_a_gutter(j79):
    for label in ("1 Gross distribution", "2a Taxable amount"):
        assert _conf(j79, label) != "low", label
    reasons = [f["reason"] for f in j79["validation"]["flagged_fields"]]
    assert not any("column gutter" in r for r in reasons), reasons


def test_f_real_box4_quote_interleaving_two_boxes(j79):
    # Run S, 3d: was a strict xfail ("the quote interleaves the labels of
    # boxes 3 AND 4 over three lines; no single line names the row"). A label
    # wrapping over a window of lines now also owns the box below its last
    # line (quote_row_lines), as a one-line label already did (Q4 e).
    assert _conf(j79, "4 Federal income tax withheld") != "low"


def test_g_real_ocr_layer_separator_misread():
    ed = _replay(62, "utah_paystub_1.pdf")
    assert _conf(ed, "Pay End Date") == "unverified"


# ── twins ────────────────────────────────────────────────────────────────────

def _w(t, x0, top):
    return {"text": t, "x0": float(x0), "x1": float(x0) + 6.0 * len(t), "top": float(top)}


def test_e_twin_a_value_under_another_box_is_not_this_label():
    import slot_extractor as S
    lines = [[_w("PAYER'S", 40, 100), _w("name", 90, 100), _w("1", 330, 100), _w("Gross", 340, 100)],
             [_w("Acme", 330, 112), _w("Corp", 360, 112)]]          # under box 1, not the payer box
    rows = S.quote_row_lines("Acme Corp", "PAYER'S name Acme Corp", lines)
    assert rows is not None and 1 not in rows


def test_e_the_box_below_is_part_of_the_quoted_row():
    import slot_extractor as S
    lines = [[_w("PAYER'S", 40, 100), _w("name", 90, 100), _w("1", 330, 100), _w("Gross", 340, 100)],
             [_w("Livewell", 42, 112), _w("Inc.", 95, 112)]]
    assert 1 in S.quote_row_lines("Livewell Inc.", "PAYER'S name Livewell Inc.", lines)


def test_f_twin_an_amount_across_a_real_gutter_still_crosses():
    import text_layer as T
    flat = [(_w("Total", 40, 100), 0), (_w("21,000", 400, 100), 0)]
    joined, crossed = T._walk(flat, "total21,000", True, 20.0)
    assert crossed
    flat = [(_w("$", 330, 100), 0), (_w("21,000", 400, 100), 0)]
    joined, crossed = T._walk(flat, "$21,000", True, 20.0)
    assert not crossed


def test_g_twin_digits_that_differ_do_not_ground():
    import slot_extractor as S
    assert S.ocr_separator_match("08/31/2018", "Pay End Date: 0831/2018")
    assert not S.ocr_separator_match("08/13/2018", "Pay End Date: 0831/2018")
    assert not S.ocr_separator_match("1,000", "Total 10.00")


def test_e_a_figure_printed_once_per_slot_is_kept_in_each_real():
    """job 48 mcguire W-2 prints $28,000 in boxes 1, 3 and 5. Once box 5's
    quote is witnessed by its box label, the same-value rule must not clear
    boxes 1 and 3: each is the page's own printed copy."""
    import replay_raw
    replay_raw._setup()
    Q.need_answer(48, "irs6744_w2_mcguire.pdf")
    rep = replay_raw.load_job(48)
    doc = next(d for d in rep["docs"] if d["original_filename"] == "irs6744_w2_mcguire.pdf")
    td = replay_raw.template_data_of(rep["template"])
    (ed, _m, _r), = replay_raw.replay_doc(doc, td, Q.need_source("irs6744_w2_mcguire.pdf"))
    for label in ("Box 1 Wages Tips Other Compensation", "Box 3 Social Security Wages",
                  "Box 5 Medicare Wages and Tips"):
        assert ed["extracted_data"][label]["value"] == "$28,000", label


def test_e_twin_a_value_printed_once_is_still_one_slots():
    import ownership as O
    lines = [[{"text": "Remit", "x0": 0, "x1": 20}, {"text": "4107.00", "x0": 30, "x1": 60}]]
    assert O._printed_figure_count("4107.00", lines) == 1
    assert O._printed_figure_count("Harwood Design", lines) == 0
