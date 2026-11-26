"""Run S, Stage 1c — a dense page whose answer left rows out is asked again,
for exactly those rows, BEFORE conservation names them.

Recovery (overnight A4) asked a page again only when the answer held fewer
than HALF of its candidate rows, so a dense page read 40 of 52 was never
retried and its 12 rows went straight to a completeness reason. Now a page
printing a table qualifies as well when it has two or more ROW LINES none of
whose figures is in the answer (conservation's own reading), and the
request names those lines. A page whose rows are all held is never asked.
"""
from __future__ import annotations

from tests import run_q_support as Q

HEADS = ["Date", "Description", "Amount", "Balance"]
TPL = Q.template(fields=["Account Holder"], tables=[(None, HEADS)],
                 doc_type="bank_statement")


def _rows():
    out, bal = [], 1000.0
    for d in range(1, 31):
        amt = 10.0 + d
        bal += amt
        out.append((f"07/{d:02d}/2019", f"DEPOSIT REF{d:03d}", f"{amt:,.2f}", f"{bal:,.2f}"))
    return out


def _pdf(tmp_path):
    rows = _rows()
    items = [(56, 770, "ACME CHECKING STATEMENT"), (56, 755, "Account Holder: Pat Lee"),
             (56, 735, "Date Description Amount Balance")]
    items += [(56, 720 - 16 * i, " ".join(r)) for i, r in enumerate(rows)]
    return Q.make_pdf(tmp_path / "dense.pdf", [items], size=8), rows


def _row(r):
    return {"Date": r[0], "Description": r[1], "Amount": r[2], "Balance": r[3],
            "source": " ".join(r), "page": 1}


def _first(rows, skip):
    def answer(prompt):
        ids = Q.slot_ids(prompt)
        name = Q.table_names(prompt)[0]
        return {"fields": {ids["Account Holder"]: {"value": "Pat Lee",
                                                  "source": "Account Holder: Pat Lee",
                                                  "page": 1}},
                "tables": {name: [_row(r) for i, r in enumerate(rows) if i not in skip]}}
    return answer


def test_a_dense_page_missing_a_quarter_of_its_rows_is_asked_again(tmp_path):
    pdf, rows = _pdf(tmp_path)
    skip = {5, 6, 7, 18, 19, 25, 26}            # 23 of 30 kept: over half
    asked = []

    def later(prompt):
        asked.append(prompt)
        name = Q.table_names(prompt)[0]
        return {"fields": {}, "tables": {name: [_row(r) for r in rows]}}

    ed = Q.run(pdf, TPL, _first(rows, skip), later)[0].extracted_data
    rec = [p for p in asked if "RECOVERY REQUEST" in p]
    assert rec, "no recovery request was made"
    # the request names the lines that were left out
    assert "07/06/2019 DEPOSIT REF006" in rec[0] and "07/26/2019 DEPOSIT REF026" in rec[0]
    name = next(k[:-5] for k in ed if k.endswith("_rows") and ed[k])
    assert len(ed[f"{name}_rows"]) == 30
    assert not any("figure" in a["text"] and "in no cell" in a["text"]
                   for a in ed["attention"])


def test_when_recovery_brings_nothing_conservation_names_the_rows(tmp_path):
    pdf, rows = _pdf(tmp_path)
    skip = {5, 6, 7}
    ed = Q.run(pdf, TPL, _first(rows, skip))[0].extracted_data
    texts = " ".join(a["text"] for a in ed["attention"])
    assert "07/06/2019" in texts and "07/08/2019" in texts


def test_a_page_whose_rows_are_all_held_is_not_asked_again(tmp_path):
    pdf, rows = _pdf(tmp_path)
    asked = []

    def later(prompt):
        asked.append(prompt)
        return None

    Q.run(pdf, TPL, _first(rows, set()), later)
    assert not [p for p in asked if "RECOVERY REQUEST" in p]
