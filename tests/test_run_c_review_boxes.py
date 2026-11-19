"""Run C, C6 — the review highlight on a real multi-page statement.

`tests/test_pdfs/round2/HTR-043235.pdf`, a four-page statement, with ONLY its
two content pages (2 and 3) selected. No model answer for it is recorded, so
the answer is written from the document's own text layer and handed to the
real `run_extraction`; the boxes come from the review route's own
`boxes_for` over the same reading the route makes of the file.

What was checked (C6's order): page numbers — stored pages are FILE pages
(3, not 2) and the route reads the whole file, so they agree; coordinates —
the pages are 792 x 612 pt, rotation 0, cropbox = mediabox, and the box is in
the same points as the rendered page. The cause was the third item: a box was
drawn only when the quote matched exactly ONE printed line, and on this page
the statement's words are interleaved with an overlaid layer, a row can be
printed twice, and a quote can span lines.
"""
from __future__ import annotations

import contextlib
import io
import json
import re
from types import SimpleNamespace

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

PDF = bs.PDF_DIR / "round2" / "HTR-043235.pdf"
NOISE = set("See sample statement below. Product name may vary slightly on "
            "new design. Your checking account".split())


@pytest.fixture(scope="module")
def run():
    from core.preprocessor import preprocess_file
    from extractor import run_extraction
    from slot_extractor import enumerate_slots
    from tests.contract.run_a_driver import model_response
    grid = json.loads((bs.TEMPLATES_DIR / "bank_statement.json").read_text(encoding="utf-8"))
    slots = enumerate_slots(grid)
    with contextlib.redirect_stdout(io.StringIO()):
        d = preprocess_file(PDF)
    t = slots["tables"][0]
    keys = [c.get("key") or c["header"] for c in t["columns"]]
    rows, cleaned = [], []
    for ln in d.page_texts[2].splitlines():
        m = re.match(r"^(\d\d/\d\d/\d\d)\s+(.*?)\s+(-?\s?[\d,]+\.\d\d)$", ln)
        if not m:
            continue
        clean = " ".join(w for w in ln.split() if w not in NOISE)
        cells = {k: "" for k in keys}
        cells[keys[0]], cells["Balance"] = m.group(1), m.group(3)
        # the model's own quote: the CLEAN line where the page interleaves
        # an overlay into it — exactly what no printed line contains
        rows.append({"cells": cells, "source": clean, "page": 2})
        if clean != ln:
            cleaned.append(len(rows) - 1)
    acct = next(ln for ln in d.page_texts[2].splitlines() if "Account #" in ln)
    fields = {f["slot_id"]: {"value": "0000 9999 9999", "source": acct, "page": 2}
              for f in slots["fields"] if f["row_label"] == "Account No"}
    fields.update({f["slot_id"]: {"value": "$1.23", "source": "Fees $1.23", "page": 2}
                   for f in slots["fields"] if f["row_label"] == "Total Debits"})
    answer = {"fields": fields, "tables": {t["name"]: rows}}
    llm = SimpleNamespace(extract=lambda **k: model_response(answer))
    with contextlib.redirect_stdout(io.StringIO()):
        res = run_extraction(SimpleNamespace(llm=llm), PDF,
                             {"layout": grid, "doc_type": "bank_statement"},
                             selected_pages=[2, 3])
    ed = res[0].extracted_data
    return ed, d, t["name"], cleaned


def _boxes(ed, d, page):
    from app.api.routes.review import boxes_for
    return boxes_for(ed, page, d.page_lines[page - 1])


def test_values_carry_file_pages_not_the_renumbered_subset(run):
    from app.core import review as R
    ed, _d, _name, _c = run
    pages = {v.get("page") for v in R.document_values(ed) if v.get("value")}
    assert 3 in pages and 1 not in pages and 2 not in pages, pages


def test_every_located_value_on_the_content_page_gets_a_box(run):
    ed, d, _name, cleaned = run
    assert cleaned, "premise: some quotes are cleaner than the printed line"
    boxes = _boxes(ed, d, 3)
    cells = [b for b in boxes if b["kind"] == "cell" and b["column"] == "Balance"]
    assert cells and all(b["box_pt"] for b in cells), \
        [b["no_box_reason"] for b in cells if not b["box_pt"]]
    for b in cells:
        x0, top, x1, bottom = b["box_pt"]
        assert 0 <= x0 < x1 <= 792 and top < bottom <= 612
    # the interleaved rows: found by their value, not by the quote line
    assert all(cells[i]["box_pt"] for i in cleaned)


def test_a_value_printed_twice_is_boxed_near_its_row_and_said_ambiguous(run):
    ed, d, _name, _c = run
    amb = [b for b in _boxes(ed, d, 3) if b.get("ambiguous")]
    assert amb, "premise: page 3 prints a row's amount more than once"
    assert all(b["box_pt"] and "nearest its label" in b["note"] for b in amb)


def test_a_value_with_no_location_says_so_and_keeps_its_reason(run):
    ed, d, _n, _c = run
    from app.api.routes.review import NOT_FOUND
    missing = [b for b in _boxes(ed, d, 3) if b["ref"] and not b["box_pt"]]
    assert missing, "premise: the $1.23 total is not on the page"
    assert all(b["no_box_reason"].startswith(NOT_FOUND) for b in missing)
    assert all("the quote was not found" in b["no_box_reason"] for b in missing)


def test_find_box_rejoins_a_split_number():
    from app.api.routes.review import find_box
    words = [{"text": t, "x0": x, "x1": x + 20, "top": 10, "bottom": 18}
             for t, x in (("Exxon", 0), ("-", 30), ("46.32", 40))]
    box, how = find_box([words], "Exxon 07/20 Salem - 46.32", "-46.32")
    assert how == "value" and box == [30.0, 10.0, 60.0, 18.0]
