"""Run T, 6 — a total the page does not print, computed by the model, is
DERIVED (the sum of a column of its rows, checked by arithmetic), not Low.

A statement that prints its transactions but no total, under a template
asking for "Total Debits": the model adds the column up. Grounding fails (the
figure is not on the page), so it was Low and flagged "not found". The
arithmetic is a check of its own; when it holds the value is `derived`.
Negative twins: a sum that does not hold, and a figure the page DOES print.
"""
from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from tests import run_q_support as Q
from tests.harness import bootstrap as bs

bs.bootstrap()

from app.core.review import field_status  # noqa: E402

VOCABS = [
    ("Total Debits", ["Date", "Description", "Debit"],
     [("07/14/2024", "Water bill", "$40.00"), ("07/15/2024", "Power bill", "$61.25"),
      ("07/18/2024", "Phone", "$19.75")], "$121.00"),
    ("Subtotal", ["Item", "Qty", "Amount"],
     [("Widget A", "2", "10.00"), ("Widget B", "1", "15.50"), ("Service", "3", "4.50")],
     "30.00"),
]


def _run(tmp_path, label, heads, rows, answer_total, extra_line=None):
    import extractor
    grid = Q.template(fields=[label], tables=[("Items", heads)])
    xs = [40, 200, 420]
    items = [(40, 760, "Account Activity"), *[(x, 740, h) for x, h in zip(xs, heads)]]
    for i, r in enumerate(rows):
        items += [(x, 724 - 14 * i, v) for x, v in zip(xs, r)]
    if extra_line:
        items.append((40, 600, extra_line))
    pdf = Q.make_pdf(tmp_path / "d.pdf", [items], size=9)
    lines = [" ".join(r) for r in rows]
    answer = {"fields": {"F1": {"value": answer_total, "source": "", "page": 1,
                                "status": "found"}},
              "tables": {"Items": [dict(zip(heads, r), source=ln, page=1)
                                   for r, ln in zip(rows, lines)]}}

    def extract(prompt="", system_instruction="", **kw):
        return Q._Resp(copy.deepcopy(answer))
    ed = extractor.run_extraction(SimpleNamespace(llm=SimpleNamespace(extract=extract)),
                                  pdf, grid)[0].extracted_data
    ref = next(f["ref"] for f in ed["slot_map"]["fields"] if f.get("row_label") == label) \
        if isinstance(ed.get("slot_map", {}).get("fields"), list) else None
    return ed, ref


@pytest.mark.parametrize("label,heads,rows,total", VOCABS)
def test_a_computed_total_is_derived_not_low(tmp_path, label, heads, rows, total):
    ed, ref = _run(tmp_path, label, heads, rows, total)
    lvl = ed["validation"]["confidence_map"][ref]
    assert lvl == "derived", (lvl, ed["validation"]["flagged_fields"])
    d = ed["field_provenance"][ref]["derived"]
    assert d["rule"] == "sum" and d["rows"] == 3
    assert field_status(ed, ref)["status"] == "derived"
    assert not any(f["ref"] in (ref, label) for f in ed["validation"]["flagged_fields"])


def test_a_sum_that_does_not_hold_stays_low(tmp_path):
    label, heads, rows, _ = VOCABS[0]
    ed, ref = _run(tmp_path, label, heads, rows, "$125.00")
    assert ed["validation"]["confidence_map"][ref] == "low"


def test_a_label_that_is_not_a_total_is_not_derived(tmp_path):
    label, heads, rows, total = VOCABS[0]
    ed, ref = _run(tmp_path, "Account Holder", heads, rows, total)
    assert ed["validation"]["confidence_map"][ref] != "derived"


def test_a_printed_total_is_grounded_not_derived(tmp_path):
    label, heads, rows, total = VOCABS[0]
    ed, ref = _run(tmp_path, label, heads, rows, total,
                   extra_line=f"Total Debits {total}")
    assert ed["validation"]["confidence_map"][ref] != "derived"
