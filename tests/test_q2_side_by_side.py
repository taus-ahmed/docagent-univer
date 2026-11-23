"""Run Q, Q2 — a table printed in side-by-side column groups.

Job 56 (carson_bank_6pg): CHECKS printed as `Number Date Amount` x3 and the
DAILY BALANCE SUMMARY as `Date Amount` x3 came back as the first group only
(3 of 8 checks), the daily balances were filed as transaction rows, and the
ready-reserve loan payment printed under Account 3216 was filed in the
checking (Account 6547) table. Reconstructed from the export and the PDF's
own layout; the `_real` twin reads the source file.
"""
from __future__ import annotations

import pytest

from tests import run_q_support as Q

HEADS = ["Date", "Description", "Check Number", "Withdrawal", "Deposit", "Balance"]
TPL = Q.template(fields=["Account Holder"], tables=[(None, HEADS)], doc_type="bank_statement")


def _pdf(tmp_path):
    g = (72, 250, 420)
    items = [(72, 760, "JOHN TEST Account Number: 6547"),
             (72, 740, "Statement Account Number: 6547"),
             (72, 710, "Date Description Withdrawal Deposit Balance"),
             (72, 692, "07/01/2019 Deposit 209.54 654.82"),
             (72, 674, "07/03/2019 SERVICE CHARGE 10.00 644.82"),
             (72, 640, "CHECKS")]
    items += [(x + d, 622, w) for x in g for d, w in ((0, "Number"), (50, "Date"), (110, "Amount"))]
    for y, recs in ((604, [("4416", "07/08/19", "$100.00"), ("4419*", "07/08/19", "$266.00"),
                           ("4420", "07/08/19", "$69.13")]),
                    (586, [("4421", "07/12/19", "$12.53"), ("4422", "07/12/19", "$25.00")])):
        for x, (a, b, c) in zip(g, recs):
            items += [(x, y, a), (x + 50, y, b), (x + 110, y, c)]
    items += [(72, 560, "DAILY BALANCE SUMMARY")]
    items += [(x + d, 542, w) for x in g for d, w in ((0, "Date"), (80, "Amount"))]
    for x, (a, b) in zip(g, [("07/01/2019", "$2,860.22"), ("07/15/2019", "$11,373.85"),
                             ("07/24/2019", "$7,285.72")]):
        items += [(x, 524, a), (x + 80, 524, b)]
    items += [(72, 490, "Account Number: 3216"), (72, 470, "07/22/2019 OVB LOAN PAYMENT 26.08")]
    return Q.make_pdf(tmp_path / "carson.pdf", [items], size=9)


def _answer(prompt):
    name = Q.table_names(prompt)[0]
    ids = Q.slot_ids(prompt)
    row = lambda d, desc, chk, wd, dep, bal, src: {  # noqa: E731
        "Date": d, "Description": desc, "Check Number": chk, "Withdrawal": wd,
        "Deposit": dep, "Balance": bal, "source": src, "page": 1}
    rows = [row("07/01/2019", "Deposit", "", "", "209.54", "654.82",
                "07/01/2019 Deposit 209.54 654.82"),
            row("07/03/2019", "SERVICE CHARGE", "", "10.00", "", "644.82",
                "07/03/2019 SERVICE CHARGE 10.00 644.82"),
            # the model's real answer: the FIRST group of each line only
            row("07/08/19", "", "4416", "$100.00", "", "", "4416 07/08/19 $100.00"),
            row("07/12/19", "Check", "4421", "$12.53", "", "", "4421 07/12/19 $12.53"),
            row("07/01/2019", "Daily Balance", "", "", "", "$2,860.22", "07/01/2019 $2,860.22"),
            row("07/22/2019", "OVB LOAN PAYMENT", "", "26.08", "", "",
                "07/22/2019 OVB LOAN PAYMENT 26.08")]
    return {"fields": {ids["Account Holder"]: {"value": "JOHN TEST", "source": "JOHN TEST",
                                               "page": 1}},
            "tables": {name: rows}}


def _run(tmp_path):
    prompts = []

    def ans(p):
        prompts.append(p)
        return _answer(p)
    (r,) = Q.run(_pdf(tmp_path), TPL, ans)
    return r.extracted_data, prompts


def _flags(ed):
    return [f for f in ed["validation"]["flagged_fields"] if isinstance(f, dict)]


def test_the_prompt_names_the_column_groups_reconstructed(tmp_path):
    _ed, prompts = _run(tmp_path)
    assert "SIDE-BY-SIDE COLUMN GROUPS" in prompts[0]
    assert "3 side-by-side column groups (5 records)" in prompts[0]


def test_checks_left_in_later_groups_are_named_reconstructed(tmp_path):
    ed, _ = _run(tmp_path)
    side = [f for f in _flags(ed) if "[side-by-side]" in str(f["ref"])]
    assert side, _flags(ed)
    why = side[0]["reason"]
    assert "prints 5 records in 3 side-by-side" in why
    for chk in ("4419*", "4420", "4422"):
        assert chk in why, why
    assert ed["needs_review"]


def test_daily_balances_are_not_transaction_rows_reconstructed(tmp_path):
    ed, _ = _run(tmp_path)
    rows = ed.get("table_rows") or next(v for k, v in ed.items() if k.endswith("_rows") and v)
    assert not any("2,860.22" in str(r.get("Balance")) for r in rows), rows
    assert any("daily-balance" in n for n in ed["validation_notes"])


def test_a_row_under_another_account_is_flagged_reconstructed(tmp_path):
    ed, _ = _run(tmp_path)
    other = [f for f in _flags(ed) if "[other account]" in str(f["ref"])]
    assert len(other) == 1 and "3216" in other[0]["reason"], _flags(ed)
    assert "OVB LOAN PAYMENT" in other[0]["value"]


def test_carson_groups_are_counted_real():
    import pdfplumber
    import column_groups as CG
    import text_layer as T
    f = Q.need_source("carson_bank_6pg.pdf")
    with pdfplumber.open(f) as pdf:
        pl = [T.read_page(p)[1] for p in pdf.pages]
    checks = sum(len(g["records"]) for ls in pl for g in CG.find_groups(ls)
                 if not CG.is_balance_block(g))
    bal = sum(len(g["records"]) for ls in pl for g in CG.find_groups(ls) if CG.is_balance_block(g))
    assert checks == 8      # "Number of Checks 8"
    assert bal == 20
    assert "3216" in set(CG.other_account_lines(pl).values())


def test_a_plain_table_gets_no_group_hint():
    import column_groups as CG
    line = [{"text": t, "x0": 72 + 60 * i} for i, t in enumerate(["Date", "Description", "Amount", "Balance"])]
    assert CG.heading_period(line) is None
    assert CG.prompt_hint([[line]]) == ""


if __name__ == "__main__":
    pytest.main([__file__])
