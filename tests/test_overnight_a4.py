"""A4 — lost page recovery (mammoth_2pg, job 46).

The real model answered one call with the 37 rows of page 1; page 2 prints 11
more (08/29 to 09/04, header repeated) and the gate raised reasons for page
2's amounts without repairing anything. Recovery: one page-targeted table
call per page whose candidate rows are missing, merged in page order, before
any completeness reason is raised.
"""

from __future__ import annotations

import re

from tests import overnight_helpers as H

MAMMOTH = "bank_statement/mammoth_2pg.pdf"
FIELDS = ["Bank Name", "Account Holder", "Account Number Last 4", "Account Type",
          "Statement Period Start", "Statement Period End", "Opening Balance",
          "Closing Balance", "Total Deposits and Credits",
          "Total Withdrawals and Debits", "Service Fees", "Interest Earned",
          "Average Balance"]
HEADERS = ["Date", "Description", "Check Number", "Withdrawal", "Deposit",
           "Running Balance", "GL Account", "Memo"]
DATE = re.compile(r"^\d{2}/\d{2}/\d{4}$")


def mammoth_grid():
    return H.column_grid(FIELDS, [("Transactions", HEADERS, 40)])


def mammoth_rows(page):
    """The statement's own rows on `page` (1-based), as the model reads them."""
    doc = H.document(MAMMOTH)
    rows = []
    for ln in doc.page_lines[page - 1]:
        ws = [w for w in ln if str(w.get("text", "")).strip()]
        if not ws or not DATE.match(str(ws[0]["text"])):
            continue
        amounts = [w for w in ws[1:] if re.fullmatch(r"[\d,]+\.\d{2}", str(w["text"]))]
        desc = " ".join(str(w["text"]) for w in ws[1:] if w not in amounts)
        cells = {"Date": ws[0]["text"], "Description": desc}
        for w in amounts[:-1]:
            cells["Deposit" if float(w["x0"]) > 455 else "Withdrawal"] = w["text"]
        cells["Running Balance"] = amounts[-1]["text"]
        rows.append({"cells": cells,
                     "source": " ".join(str(w["text"]) for w in ws), "page": page})
    return rows


def mammoth_fields(g):
    a = H.ans
    f = {"Bank Name": a("EXAMPLE COMMUNITY BANK", "EXAMPLE COMMUNITY BANK"),
         "Opening Balance": a("$4,210.55", "Opening balance: $4,210.55 Closing balance: $14,269.35"),
         "Closing Balance": a("$14,269.35", "Opening balance: $4,210.55 Closing balance: $14,269.35"),
         "Statement Period Start": a("08/01/2026", "Account: XXXX-0000 Period: 08/01/2026 - 08/31/2026"),
         "Statement Period End": a("08/31/2026", "Account: XXXX-0000 Period: 08/01/2026 - 08/31/2026")}
    return {H.field_id(g, k): v for k, v in f.items()}


def test_page_rows_are_what_the_document_prints():
    assert len(mammoth_rows(1)) == 37
    assert len(mammoth_rows(2)) == 11


def test_a_lost_page_is_recovered_before_any_reason_is_raised():
    g = mammoth_grid()
    name = H.table_name(g, "Transactions")
    first = {"fields": mammoth_fields(g), "tables": {name: mammoth_rows(1)}}
    recovery = {"fields": {}, "tables": {name: mammoth_rows(2)}}
    data, calls = H.run(MAMMOTH, g, None, doc_type="bank_statement",
                        answers=[first, recovery])
    rows = data.get(f"{name}_rows") or []
    assert len(rows) == 48, len(rows)
    dates = [r.get("Date") for r in rows]
    assert dates[37] == "08/29/2026" and dates[-1] == "09/04/2026"
    assert "Date" not in dates, "the repeated header row is not a row"
    text = " ".join(H.reasons(data)).casefold()
    assert "649.37" not in text and "177.30" not in text, H.reasons(data)
    page_calls = [c for c in calls if "page 2" in str(c.get("prompt") or c)]
    assert len(calls) == 2 and page_calls, [str(c)[:120] for c in calls]


def test_recovery_that_still_fails_raises_the_reason():
    g = mammoth_grid()
    name = H.table_name(g, "Transactions")
    first = {"fields": mammoth_fields(g), "tables": {name: mammoth_rows(1)}}
    empty = {"fields": {}, "tables": {name: []}}
    data, _calls = H.run(MAMMOTH, g, None, doc_type="bank_statement",
                         answers=[first, empty])
    assert len(data.get(f"{name}_rows") or []) == 37
    assert data.get("attention"), "a page still missing must stay visible"
