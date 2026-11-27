"""Run T, 4 — stacked headings in perception, Regular and no-template.

A heading printed in two lines over one column ("Tran Date" over "Post Date",
"Principal" over "Interest") is two sub-fields; a record is two lines tall.
Perception reads the pairs off positions (text_layer.stacked_headings); the
inference prompt names them (only when present: every other prompt is
unchanged); Regular puts a record's two values back under their own heading
when the model swapped them - by which line each is printed on. Organized:
tests/test_t_organized_tables.py.
"""
from __future__ import annotations

import copy
from types import SimpleNamespace

import pdfplumber
import pytest

from tests import run_q_support as Q
from tests.harness import bootstrap as bs

bs.bootstrap()

from text_layer import stacked_headings  # noqa: E402


def _page_lines(pdf):
    from text_layer import read_page
    with pdfplumber.open(str(pdf)) as doc:
        got = read_page(doc.pages[0])
    for x in (got if isinstance(got, tuple) else (got,)):
        if isinstance(x, list) and x and isinstance(x[0], list):
            return x
    raise AssertionError("read_page returned no lines")


CARD = [(40, 760, "Card Statement"),
        (40, 730, "Tran Date"), (130, 730, "Description"), (400, 730, "Amount"),
        (40, 721, "Post Date"),
        (40, 705, "01/13/2024"), (130, 705, "FUEL STOP"), (400, 705, "41.00"),
        (40, 696, "01/14/2024"),
        (40, 681, "01/15/2024"), (130, 681, "GROCERY MART"), (400, 681, "88.15"),
        (40, 672, "01/17/2024")]
LOAN = [(40, 760, "Historial"),
        (40, 730, "Fecha"), (150, 730, "Principal"), (260, 730, "Cargos"),
        (150, 721, "Interes"), (260, 721, "Mora"),
        (40, 705, "02/15/2024"), (150, 705, "300.00"), (260, 705, "0.00"),
        (150, 696, "45.10"), (260, 696, "15.00")]


@pytest.mark.parametrize("items,pairs", [
    (CARD, [("Tran Date", "Post Date")]),
    (LOAN, [("Principal", "Interes"), ("Cargos", "Mora")]),
])
def test_perception_reads_the_pairs(tmp_path, items, pairs):
    pdf = Q.make_pdf(tmp_path / "s.pdf", [items], size=9)
    got = stacked_headings(_page_lines(pdf))
    assert [(s["top"], s["bottom"]) for s in got] == pairs


def test_a_plain_heading_line_has_no_pairs(tmp_path):
    items = [(40, 760, "Statement"), (40, 730, "Date"), (130, 730, "Description"),
             (400, 730, "Amount"), (40, 714, "01/13/2024"), (130, 714, "FUEL"),
             (400, 714, "41.00")]
    pdf = Q.make_pdf(tmp_path / "s.pdf", [items], size=9)
    assert stacked_headings(_page_lines(pdf)) == []


def test_the_inference_prompt_names_them_only_when_present():
    from shape_inference import _stacked_block
    assert _stacked_block(None) == "" and _stacked_block([]) == ""
    b = _stacked_block([{"top": "Tran Date", "bottom": "Post Date"}])
    assert '"Tran Date" over "Post Date"' in b and "TWO columns" in b


def test_regular_puts_swapped_values_back(tmp_path):
    import extractor
    pdf = Q.make_pdf(tmp_path / "c.pdf", [CARD], size=9)
    heads = ["Tran Date", "Post Date", "Description", "Amount"]
    grid = Q.template(tables=[("Card", heads)])
    rows = [{"Tran Date": "01/13/2024", "Post Date": "01/14/2024", "Description": "FUEL STOP",
             "Amount": "41.00", "source": "01/13/2024 FUEL STOP 41.00", "page": 1},
            # the model swapped this record's two dates
            {"Tran Date": "01/17/2024", "Post Date": "01/15/2024", "Description": "GROCERY MART",
             "Amount": "88.15", "source": "01/15/2024 GROCERY MART 88.15", "page": 1}]
    answer = {"fields": {}, "tables": {"Card": rows}}
    ed = extractor.run_extraction(
        SimpleNamespace(llm=SimpleNamespace(extract=lambda **k: Q._Resp(copy.deepcopy(answer)))),
        pdf, grid)[0].extracted_data
    out = ed["Card_rows"]
    assert (out[0]["Tran Date"], out[0]["Post Date"]) == ("01/13/2024", "01/14/2024")
    assert (out[1]["Tran Date"], out[1]["Post Date"]) == ("01/15/2024", "01/17/2024")
    assert ed["validation"]["stacked_swaps"] == 1
