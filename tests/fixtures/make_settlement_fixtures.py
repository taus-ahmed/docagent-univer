"""Derived fixtures with truth (Part 3.4 e), generated — equivalents of the
native test files, which are not in the repository.

  settlement_2p        a 2-page merchant settlement: batches on page 1, the
                       summary (gross, fees, chargebacks, net) on page 2
  settlement_2p_junk   the same with the net settlement printed "aaaaaa"
  statement_5p         a 5-page statement excerpt, "Page n of 5", four rows a
                       page — one document, twenty truth rows

Each document: {pages: [[line]], fields: {label: value}, columns, rows,
template}. The settlement template declares the settlement rule.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_locale_fixtures as M  # noqa: E402
from make_scan_variants import build_pdf  # noqa: E402

SETTLEMENT_RULES = [{"name": "settlement", "type": "sum_equals",
                     "terms": ["Gross Sales", "-Processing Fees", "-Chargebacks?"],
                     "total": "Net Settlement"},
                    {"name": "batches_sum", "type": "sum_equals",
                     "terms": ["batches.Amount"], "total": "Gross Sales"}]


def _money(c):
    return f"${c // 100:,}.{c % 100:02d}"


def settlement(junk=False):
    batches = [("2024-05-27", "Card batch 0412", 412_550), ("2024-05-28", "Card batch 0413", 389_020),
               ("2024-05-29", "Card batch 0414", 455_175), ("2024-05-30", "Card batch 0415", 401_300),
               ("2024-05-31", "Card batch 0416", 377_955)]
    gross = sum(a for *_x, a in batches)
    fees, cb = gross * 29 // 1000, 12_500
    net = gross - fees - cb
    fields = {"Merchant ID": "MID-778201", "Settlement Date": "2024-05-31",
              "Gross Sales": _money(gross), "Processing Fees": _money(fees),
              "Chargebacks": _money(cb), "Net Settlement": "aaaaaa" if junk else _money(net)}
    cols = ["Date", "Description", "Amount"]
    rows = [{"Date": d, "Description": t, "Amount": _money(a)} for d, t, a in batches]
    p1 = ["MERCHANT SETTLEMENT STATEMENT", f"Merchant ID: {fields['Merchant ID']}",
          f"Settlement Date: {fields['Settlement Date']}", "Page 1 of 2", list(cols)]
    p1 += [[r[c] for c in cols] for r in rows]
    p2 = ["MERCHANT SETTLEMENT STATEMENT", f"Merchant ID: {fields['Merchant ID']}", "Page 2 of 2"]
    p2 += [f"{k}: {fields[k]}" for k in ("Gross Sales", "Processing Fees", "Chargebacks",
                                         "Net Settlement")]
    grid = M._grid(list(fields), cols)
    grid["regions"][0]["name"] = "batches"
    grid["rules"] = SETTLEMENT_RULES
    return {"pages": [p1, p2], "fields": fields, "columns": cols, "rows": rows,
            "table": "batches",
            "template": {"layout": grid, "doc_type": "settlement", "mode": "layout",
                         "locale": "en-US"}}


def statement_5p():
    cols = ["Date", "Description", "Amount"]
    rows, pages = [], []
    for p in range(5):
        page = ["ACCOUNT STATEMENT", "Account Number: 000555123456", f"Page {p + 1} of 5",
                list(cols)]
        for k in range(4):
            n = p * 4 + k
            r = {"Date": f"2024-04-{n + 1:02d}", "Description": f"Transfer ref TR{7100 + n}",
                 "Amount": _money(10_000 + 731 * n)}
            rows.append(r)
            page.append([r[c] for c in cols])
        pages.append(page)
    fields = {"Account Number": "000555123456"}
    grid = M._grid(list(fields), cols)
    return {"pages": pages, "fields": fields, "columns": cols, "rows": rows, "table": "rows",
            "template": {"layout": grid, "doc_type": "bank_statement", "mode": "layout",
                         "locale": "en-US"}}


def documents():
    return {"settlement_2p": settlement(), "settlement_2p_junk": settlement(junk=True),
            "statement_5p": statement_5p()}


_COL_X = (56, 150, 400)


def _ops(lines) -> bytes:
    """A str is one line at the margin; a list is a table line, each cell
    printed at its column's x — so a value sits under its own heading, as on
    a real statement (placement checks this)."""
    out = [b"BT", b"0 Tr"]
    for i, item in enumerate(lines):
        y = 780 - 18 * i
        for x, text in (zip(_COL_X, item) if isinstance(item, list) else [(56, item)]):
            enc = (str(text).encode("cp1252", "replace").replace(b"\\", b"\\\\")
                   .replace(b"(", b"\\(").replace(b")", b"\\)"))
            out.append(f"/F1 10 Tf 1 0 0 1 {x} {y} Tm (".encode() + enc + b") Tj")
    out.append(b"ET")
    return b"\n".join(out)


def pdf(doc) -> bytes:
    return build_pdf([{"w_pt": 612, "h_pt": 792, "ops": _ops(lines)} for lines in doc["pages"]])
