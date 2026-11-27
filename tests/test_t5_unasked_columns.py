"""Run T, 5 — a template with fewer columns than the page: the printed
AMOUNT columns it does not ask for are named in a visible reason, never
dropped in silence. A non-money column it does not ask for (a quantity) is
the template's choice and is not named.
"""
from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from tests import run_q_support as Q
from tests.harness import bootstrap as bs

bs.bootstrap()

PAGES = {
    "bank": (["Date", "Description", "Debits", "Credits", "Balance"],
             [("07/14/2024", "Water bill", "$40.00", "", "$960.00"),
              ("07/15/2024", "Payroll", "", "$1,200.00", "$2,160.00"),
              ("07/18/2024", "Phone", "$19.75", "", "$2,140.25")]),
    "invoice": (["Item", "Qty", "Unit Price", "Amount"],
                [("Widget A", "2", "5.00", "10.00"), ("Widget B", "1", "15.50", "15.50"),
                 ("Service", "3", "1.50", "4.50")]),
}


def _run(tmp_path, page, template_cols):
    import extractor
    heads, rows = PAGES[page]
    xs = [40, 150, 300, 400, 500][:len(heads)]
    items = [(40, 760, "Document")] + [(x, 740, h) for x, h in zip(xs, heads)]
    for i, r in enumerate(rows):
        items += [(x, 724 - 14 * i, v) for x, v in zip(xs, r) if v]
    pdf = Q.make_pdf(tmp_path / "u.pdf", [items], size=9)
    grid = Q.template(tables=[("Lines", template_cols)])
    answer = {"fields": {}, "tables": {"Lines": [
        dict({h: v for h, v in zip(heads, r) if h in template_cols},
             source=" ".join(v for v in r if v), page=1) for r in rows]}}
    ed = extractor.run_extraction(
        SimpleNamespace(llm=SimpleNamespace(extract=lambda **k: Q._Resp(copy.deepcopy(answer)))),
        pdf, grid)[0].extracted_data
    return ed


def _flag(ed):
    return [f for f in ed["validation"]["flagged_fields"]
            if f["ref"].endswith("[columns not in template]")]


def test_bank_columns_the_template_lacks_are_named(tmp_path):
    ed = _run(tmp_path, "bank", ["Date", "Description", "Balance"])
    f = _flag(ed)
    assert f and "Debits" in f[0]["reason"] and "Credits" in f[0]["reason"]
    assert ed["validation"]["unasked_columns"]["Lines"] == ["Debits", "Credits"]


def test_an_invoice_price_column_is_named_and_a_quantity_is_not(tmp_path):
    ed = _run(tmp_path, "invoice", ["Item", "Amount"])
    assert ed["validation"]["unasked_columns"].get("Lines") == ["Unit Price"]


@pytest.mark.parametrize("page", ["bank", "invoice"])
def test_a_template_with_every_column_names_nothing(tmp_path, page):
    ed = _run(tmp_path, page, PAGES[page][0])
    assert not _flag(ed) and not ed["validation"]["unasked_columns"]
