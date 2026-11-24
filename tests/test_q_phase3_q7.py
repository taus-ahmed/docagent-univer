"""Run Q Phase 3, item 3 (Q7): wrong slot, row mix and invented values on a
form whose table is drawn as outlines (virtus 1099-B, jobs 59 and 64).

The table's text is vector outlines: nothing in the text layer to ground
against, and OCR reads it as noise ("SOOO of SSC.C000") even at 600 dpi.
What the page does carry reliably is GEOMETRY:

  * each record's check boxes, and whether each is marked (an `X` character
    or a drawn mark inside the box) - read by x under its column heading;
  * where the page prints anything at all on each record (outline glyphs or
    characters), per column.

The stored model answer shifts the withholding columns down one record,
drops the 500.00 record, invents `16 Jul 2012` as an acquired date and
ticks both boxes on every record. Each of those is now Low with its reason;
a correct answer on the same page raises none of them.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from tests import run_q_support as Q

VIRTUS = "virtus_1099b.pdf"
TABLE = "Form 1099-B - Proceeds From Broker and Barter Exchange Transactions"
NONCOV = "eck if 12 Noncovered security"
BASIS = "Check if 14 Basis reported to IRS"

# what the page prints, record by record (read off the rendered page)
TRUE_ROWS = [
    {"Description 1b of property": "50.0000 of 350.0000 Shares sold", "Date 1d sold or disposed": "25 May 2012",
     "Proeeds 1e ($)": "500.00", "FEDERAL 5 INCOME TAX WITHHELD ($)": "140.00", NONCOV: "X", BASIS: "",
     "State 15 name": "CA", "Ste tax 16 identification no": "8036173CI3", "State tax withheld ($)": "35.00"},
    {"Description 1b of property": "50.0000 of 350.0000 Shares sold", "Date 1c acquired": "15 April 2011",
     "Date 1d sold or disposed": "25 May 2012", "Proeeds 1e ($)": "1000.00", "Cost 1g or other basis ($)": "800.00",
     "Type of 4 gain or loss": "Long Term / Ordinary", "FEDERAL 5 INCOME TAX WITHHELD ($)": "280.00",
     NONCOV: "", BASIS: "X", "State 15 name": "CA", "Ste tax 16 identification no": "8036173CI3", "State tax withheld ($)": "70.00"},
    {"Description 1b of property": "250.0000 of 350.0000 Shares sold", "Date 1d sold or disposed": "25 May 2012",
     "Proeeds 1e ($)": "2000.00", "Cost 1g or other basis ($)": "2300.00",
     "Type of 4 gain or loss": "Short Term / Ordinary", "FEDERAL 5 INCOME TAX WITHHELD ($)": "560.00",
     NONCOV: "", BASIS: "X", "State 15 name": "CA", "Ste tax 16 identification no": "8036173CI3", "State tax withheld ($)": "140.00"},
    {"Description 1b of property": "100.0000 of 433.3333 Shares sold", "Date 1d sold or disposed": "15 Jul 2012",
     "Proeeds 1e ($)": "1500.00", "FEDERAL 5 INCOME TAX WITHHELD ($)": "420.00", NONCOV: "X", BASIS: "",
     "State 15 name": "CA", "Ste tax 16 identification no": "8036173CI3", "State tax withheld ($)": "105.00"},
    {"Description 1b of property": "333.3333 of 433.3333 Shares sold", "Date 1d sold or disposed": "15 Jul 2012",
     "Proeeds 1e ($)": "5000.00", "Cost 1g or other basis ($)": "3833.33",
     "Type of 4 gain or loss": "Short Term / Ordinary", "FEDERAL 5 INCOME TAX WITHHELD ($)": "1400.00",
     NONCOV: "", BASIS: "X", "State 15 name": "CA", "Ste tax 16 identification no": "8036173CI3", "State tax withheld ($)": "350.00"},
]


def test_check_boxes_are_read_by_x_and_y():
    import outline_check as O
    f = Q.need_source(VIRTUS)
    grid = O.box_grid(f, 1)
    assert len(grid["rows"]) == 5 and len(grid["columns"]) == 2
    states = [tuple(r["marked"]) for r in grid["rows"]]
    assert states == [(True, False), (False, True), (False, True), (True, False), (False, True)]


def test_the_partly_outlined_page_is_found():
    import outline_check as O
    assert O.outline_pages(Q.need_source(VIRTUS)) == {1}
    assert O.outline_pages(Q.need_source("adp_w2_interactive.pdf")) == {1}


def _job_template(job):
    import replay_raw
    replay_raw._setup()
    return replay_raw.template_data_of(replay_raw.load_job(job)["template"])


def _rows(ed):
    if f"{TABLE}_rows" in ed:
        return ed[f"{TABLE}_rows"]
    return next(v for k, v in ed.items() if k.endswith("_rows") and isinstance(v, list) and v)


def _flags(ed):
    return ed["validation"]["flagged_fields"]


def _stored(job):
    import replay_raw
    doc = replay_raw.load_job(job)["docs"][0]
    return json.loads(doc["raw_llm_response"])


@pytest.fixture(scope="module")
def stored_run():
    Q.need_answer(64, VIRTUS)
    import replay_raw
    doc = replay_raw.load_job(64)["docs"][0]
    (ed, _m, _r), = replay_raw.replay_doc(doc, _job_template(64), Q.need_source(VIRTUS))
    return ed


def test_real_answer_every_checkbox_agrees_with_its_box_or_is_flagged(stored_run):
    import outline_check as O
    rows = _rows(stored_run)
    grid = O.box_grid(Q.need_source(VIRTUS), 1)
    reasons = {f["ref"]: f["reason"] for f in _flags(stored_run)}
    disagree = 0
    for i, (row, rec) in enumerate(zip(rows, grid["rows"])):
        for col, marked in zip((NONCOV, BASIS), rec["marked"]):
            said = bool(str(row.get(col, "")).strip())
            if said != marked:
                disagree += 1
                why = reasons.get(f"{TABLE}[{i}].{col}", "")
                assert "box" in why and ("not checked" in why or "is checked" in why), (i, col, why)
                assert row["_confidence"] == "low"
    assert disagree >= 1          # the stored answer does get boxes wrong


def test_real_answer_value_where_the_page_prints_nothing_is_low(stored_run):
    rows = _rows(stored_run)
    # shifted up: the first printed record has no acquired date, cost or type
    reasons = {f["ref"]: f["reason"] for f in _flags(stored_run)}
    for col in ("Date 1c acquired", "Cost 1g or other basis ($)", "Type of 4 gain or loss"):
        r = reasons.get(f"{TABLE}[0].{col}", "")
        assert "prints nothing" in r, (col, r)
    # invented: the last record's acquired date
    assert rows[4]["Date 1c acquired"] == "16 Jul 2012"
    assert "prints nothing" in reasons.get(f"{TABLE}[4].Date 1c acquired", "")
    assert all(r["_confidence"] == "low" for r in rows)
    assert "row_mismatch" in rows[0]["_review_reasons"]


def test_a_correct_answer_on_the_same_page_raises_none_of_it():
    import replay_raw
    from types import SimpleNamespace
    replay_raw._setup()
    from extractor import run_extraction
    doc = replay_raw.load_job(64)["docs"][0]
    stored = json.loads(doc["raw_llm_response"])
    tname = next(iter(stored["tables"]))
    keys = list(stored["tables"][tname][0]["cells"].keys())
    rows = []
    for t in TRUE_ROWS:
        cells = {k: t.get(k, "") for k in keys}
        rows.append({"cells": cells, "source": " ".join(v for v in cells.values() if v), "page": 1})
    stored["tables"][tname] = rows
    ed0 = doc["extraction_json"]
    ed0 = json.loads(ed0) if isinstance(ed0, str) else ed0
    llm = replay_raw.ReplayLLM(json.dumps(stored), ed0.get("inferred_template"))
    (r,) = run_extraction(SimpleNamespace(llm=llm), Q.need_source(VIRTUS), None)
    ed = r.extracted_data
    out = _rows(ed)
    assert len(out) == 5
    bad = [x for x in _flags(ed) if "prints nothing" in x["reason"] or "not checked" in x["reason"]
           or "is checked" in x["reason"] or "prints a value" in x["reason"]]
    assert bad == []
    assert all(row["_confidence"] != "low" for row in out), [row["_review_reasons"] for row in out]


def test_a_computed_number_is_named_as_computed():
    import outline_check as O
    row = {"Proceeds": "1000.00", "Cost": "800.00", "Gain": "200.00"}
    assert O.computed_from(row, "Gain") == "1000.00 - 800.00"
    assert O.computed_from(row, "Cost") is None or "1000.00" in O.computed_from(row, "Cost")
    assert O.computed_from({"A": "5.00", "B": "7.00"}, "A") is None
