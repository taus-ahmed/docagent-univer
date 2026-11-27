"""Run T, 2 in Regular extraction: a reference tail ("NBR 131") printed on
the line under a transaction was answered by the model as a row of its own,
so the sheet held one row more than the page. A row with no date and no
amount, read from the line DIRECTLY below the previous row, now continues
that row; row count matches the page. Two vocabularies, two negative twins.
"""
from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from tests import run_q_support as Q
from tests.harness import bootstrap as bs

bs.bootstrap()

CASES = {
    "en": {"heads": ["Date", "Description", "Debits", "Credits", "Balance"],
           "lines": ["Sample Bank", "Date Description Debits Credits Balance",
                     "07/14/2019 DEPOSIT 131 $86.96 $2,395.78",
                     "07/15/2019 SHOE RETAIL WIREXFER $1,845.80 $549.98",
                     "REF 131",
                     "07/16/2019 DEPOSIT 131 $94.48 $644.46"],
           "rows": [("07/14/2019", "DEPOSIT 131", "", "$86.96", "$2,395.78", 2),
                    ("07/15/2019", "SHOE RETAIL WIREXFER", "$1,845.80", "", "$549.98", 3),
                    ("", "REF 131", "", "", "", 4),
                    ("07/16/2019", "DEPOSIT 131", "", "$94.48", "$644.46", 5)]},
    "es": {"heads": ["Fecha", "Concepto", "Cargo", "Abono", "Saldo"],
           "lines": ["Banco Ejemplo", "Fecha Concepto Cargo Abono Saldo",
                     "03/22/2024 TRANSFERENCIA $1,000.00 $5,000.00",
                     "03/24/2024 PAGO TARJETA $250.00 $4,750.00",
                     "OPER 99812",
                     "03/29/2024 COMISION $3.00 $4,747.00"],
           "rows": [("03/22/2024", "TRANSFERENCIA", "", "$1,000.00", "$5,000.00", 2),
                    ("03/24/2024", "PAGO TARJETA", "$250.00", "", "$4,750.00", 3),
                    ("", "OPER 99812", "", "", "", 4),
                    ("03/29/2024", "COMISION", "$3.00", "", "$4,747.00", 5)]},
}


def _run(tmp_path, case, rows=None):
    import extractor
    c = CASES[case]
    heads = c["heads"]
    inferred = {"document_type": "bank_statement", "title": "Statement", "fields": [],
                "totals": [], "tables": [{"name": "Transactions", "row_count": 4,
                                          "columns": heads}]}
    answer = [dict(zip(heads, r[:5]), source=c["lines"][r[5]], page=1)
              for r in (rows or c["rows"])]
    xs = [40, 110, 330, 410, 490]
    items = [(40, 760, c["lines"][0])] + [(x, 746, h) for x, h in zip(xs, heads)]
    by_line = {r[5]: r for r in (rows or c["rows"])}
    for i, t in enumerate(c["lines"][2:], 2):
        y = 760 - 14 * i
        r = by_line.get(i)
        if r is None or not r[0]:
            items.append((110, y, t))           # a tail / a note: one phrase
            continue
        items += [(x, y, v) for x, v in zip(xs, r[:5]) if v]
    pdf = Q.make_pdf(tmp_path / "b.pdf", [items], size=9)
    calls = []

    def extract(prompt="", system_instruction="", **kw):
        calls.append(prompt)
        if (system_instruction or "").startswith("You are a document analyst"):
            return Q._Resp(copy.deepcopy(inferred))
        if len(calls) <= 2:
            return Q._Resp({"fields": {}, "tables": {"Transactions": copy.deepcopy(answer)}})
        r = Q._Resp(None, "")
        r.error = "scripted: no further answer"
        return r
    ed = extractor.run_extraction(SimpleNamespace(llm=SimpleNamespace(extract=extract)),
                                  pdf, None)[0].extracted_data
    return ed, heads


@pytest.mark.parametrize("case", ["en", "es"])
def test_a_tail_joins_the_row_above(tmp_path, case):
    ed, heads = _run(tmp_path, case)
    rows = ed["Transactions_rows"]
    assert len(rows) == 3                                    # as many rows as the page
    tail = CASES[case]["rows"][2][1]
    assert rows[1][heads[1]].endswith(" " + tail)
    assert not any(r.get(heads[1]) == tail for r in rows)
    assert ed["validation"]["attached_tail_count"] == 1
    assert rows[1]["_confidence"] in ("high", "grounded")


def test_a_dateless_row_that_is_not_the_next_line_stays(tmp_path):
    c = CASES["en"]
    rows = list(c["rows"])
    rows[2] = ("", "REF 131", "", "", "", 4)
    # move the dateless row to after the LAST row's line: not adjacent to row 2
    lines = c["lines"][:4] + c["lines"][5:] + ["Note line", "REF 131"]
    CASES["en_far"] = {"heads": c["heads"], "lines": lines,
                       "rows": [rows[0], rows[1], (*rows[3][:5], 4), ("", "REF 131", "", "", "", 6)]}
    try:
        ed, heads = _run(tmp_path, "en_far")
    finally:
        CASES.pop("en_far")
    assert len(ed["Transactions_rows"]) == 4
    assert ed["validation"]["attached_tail_count"] == 0


def test_a_table_without_dates_or_amounts_is_untouched():
    from slot_extractor import attach_tail_rows
    rows = [{"Name": "Ann", "Role": "Chair"}, {"Name": "Bo", "Role": ""},
            {"Name": "Cy", "Role": "Member"}]
    lines = {id(r): i for i, r in enumerate(rows)}
    out, att = attach_tail_rows(rows, ["Name", "Role"], lines)
    assert out == rows and att == []
