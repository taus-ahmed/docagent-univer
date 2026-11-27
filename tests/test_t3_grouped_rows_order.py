"""Run T, 3 in Regular extraction: records printed in side-by-side column
groups (a check list printed `Number Date Amount` three times across) are
output in the PAGE's order - each group top to bottom, then left to right -
and sorted by their first column where the page prints them sorted. The
model answers them line by line, interleaving the groups.
"""
from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from tests import run_q_support as Q
from tests.harness import bootstrap as bs

bs.bootstrap()

CHECKS = {
    "en": ("Number", "Date", "Amount"),
    "es": ("Cheque", "Fecha", "Importe"),
}
BANDS = [[("4421", "07/22/24", "$12.53"), ("4422", "07/22/24", "$25.00")],
         [("4423", "07/19/24", "$114.00"), ("4424", "07/16/24", "$1,046.66")],
         [("4451", "07/25/24", "$150.00")]]
XS = [[40, 110, 170], [230, 300, 360], [420, 490, 550]]


def _run(tmp_path, heads):
    import extractor
    items = [(40, 760, "CHECKS")]
    for b in range(3):
        items += [(XS[b][k], 740, h) for k, h in enumerate(heads)]
    for b, band in enumerate(BANDS):
        for i, rec in enumerate(band):
            items += [(XS[b][k], 724 - 12 * i, v) for k, v in enumerate(rec)]
    items.append((40, 680, "End of checks"))
    pdf = Q.make_pdf(tmp_path / "g.pdf", [items], size=9)
    grid = Q.template(tables=[("Checks", list(heads))])
    lines = [" ".join(v for b in range(3) if i < len(BANDS[b]) for v in BANDS[b][i])
             for i in range(2)]
    # line by line, interleaving the groups: what the model does
    answer_rows = []
    for i in range(2):
        for b in range(3):
            if i < len(BANDS[b]):
                answer_rows.append(dict(zip(heads, BANDS[b][i]), source=lines[i], page=1))
    answer = {"fields": {}, "tables": {"Checks": answer_rows}}
    ed = extractor.run_extraction(
        SimpleNamespace(llm=SimpleNamespace(extract=lambda **k: Q._Resp(copy.deepcopy(answer)))),
        pdf, grid)[0].extracted_data
    return ed


@pytest.mark.parametrize("lang", ["en", "es"])
def test_groups_are_read_top_to_bottom_then_left_to_right(tmp_path, lang):
    heads = CHECKS[lang]
    ed = _run(tmp_path, heads)
    got = [r[heads[0]] for r in ed["Checks_rows"]]
    assert got == ["4421", "4422", "4423", "4424", "4451"]


def test_rows_outside_a_grouped_block_keep_their_order():
    from slot_extractor import order_grouped_rows
    rows = [{"A": "3"}, {"A": "1"}, {"A": "2"}]
    lines = [[{"text": "x", "x0": 0, "x1": 5}]] * 3
    out, moved = order_grouped_rows(rows, ["A"], lines, {id(r): i for i, r in enumerate(rows)})
    assert out == rows and moved == 0
