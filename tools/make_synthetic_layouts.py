"""Run T1, Stage 4: synthetic layouts with KNOWN ground truth.

    backend\\.venv\\Scripts\\python.exe tools\\make_synthetic_layouts.py

Writes tests/fixtures/synthetic_layouts/<case>.pdf and <case>.truth.json,
one per failure class the structure engine must handle, in several
vocabularies (English, Spanish, German, French words; invented names and
numbers throughout). Deterministic: same code, same bytes.

truth.json:
  tables   [{"header": [...], "rows": [[...], ...]}]  values as PRINTED;
           "" in a header is a column the page prints no heading for
           (the group identifier and name columns)
  pairs    [[label as printed, value as printed]]
  absent   texts that must never reach a cell (background, side panels,
           notes)
  zeros    identifiers whose leading zeros must survive as text
  dates    {"printed": [year, month, day]} the date a printed text must be
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests import t1_pdf  # noqa: E402

OUT = ROOT / "tests" / "fixtures" / "synthetic_layouts"


def R(x_right, y, text, size=10):
    """Right-aligned text ending at x_right (Helvetica digit width)."""
    return (x_right - 0.556 * size * len(text), y, text)


def C(x_mid, y, text, size=10):
    """Text centred on x_mid (approximate Helvetica width)."""
    return (x_mid - 0.5 * size * len(text) * 0.5, y, text)


def _statement(words, n=6, y0=640, x_shift=0.0, heading=True, start=1000.0, day0=3):
    """A ledger table in the vocabulary `words` = (date, desc, debit, credit,
    balance); debits on even rows, credits on odd ones (blank cells)."""
    d, de, db, cr, ba = words
    items = []
    if heading:
        items += [(44 + x_shift, y0 + 16, d), (110 + x_shift, y0 + 16, de),
                  C(330 + x_shift, y0 + 16, db), C(410 + x_shift, y0 + 16, cr),
                  C(490 + x_shift, y0 + 16, ba)]
    rows, bal = [], start
    for i in range(n):
        y = y0 - 14 * i
        amt = f"{(i + 1) * 7:.2f}"
        date = f"07/{day0 + i:02d}/2026"
        desc = f"Item {chr(65 + i)}{i}"
        if i % 2 == 0:
            bal -= (i + 1) * 7
            items += [(44 + x_shift, y, date), (110 + x_shift, y, desc),
                      R(350 + x_shift, y, amt), R(515 + x_shift, y, f"{bal:,.2f}")]
            rows.append([date, desc, amt, "", f"{bal:,.2f}"])
        else:
            bal += (i + 1) * 7
            items += [(44 + x_shift, y, date), (110 + x_shift, y, desc),
                      R(430 + x_shift, y, amt), R(515 + x_shift, y, f"{bal:,.2f}")]
            rows.append([date, desc, "", amt, f"{bal:,.2f}"])
    return items, {"header": list(words), "rows": rows}, bal


def case_wrapped_groups():
    items, rows = [], []
    head = ["Numero", "Fecha", "Importe"]
    for g, x in enumerate((40, 230, 420)):
        items += [(x, 700, head[0]), (x + 55, 700, head[1]), C(x + 140, 700, head[2])]
        for i in range(4):
            y = 686 - 14 * i
            vals = [f"F{g}{i:02d}", f"07/{10 + i}/2026", f"{g * 100 + i * 3 + 1}.50"]
            items += [(x, y, vals[0]), (x + 55, y, vals[1]), R(x + 165, y, vals[2])]
            rows.append(vals)
    return [items], {"tables": [{"header": head, "rows": rows}]}


def case_stacked_headers():
    items = [(44, 712, "Tran"), (44, 703, "Date"), (130, 712, "Reference"),
             (130, 703, "Number"), C(330, 712, "Amount"), C(330, 703, "USD")]
    rows = []
    for i in range(4):
        y = 686 - 14 * i
        v = [f"07/{11 + i}/2026", f"RF{4400 + i}", f"{10 + i}.25"]
        items += [(44, y, v[0]), (130, y, v[1]), R(350, y, v[2])]
        rows.append(v)
    return [items], {"tables": [{"header": ["Tran Date", "Reference Number", "Amount USD"],
                                 "rows": rows}]}


def case_group_headers():
    items = [(44, 712, "Rechnung"), (160, 712, "Datum"), C(320, 712, "Betrag")]
    rows, y = [], 698
    for gid, name in (("7711", "RIVER GOODS"), ("8820", "LAKE WORKS")):
        items.append((44, y, f"{gid} {name}"))
        y -= 14
        for i in range(2):
            v = [f"RE{gid[:2]}{i}", "07/14/2026", f"{i + 2}.40"]
            items += [(44, y, v[0]), (160, y, v[1]), R(340, y, v[2])]
            rows.append([gid, name] + v)
            y -= 14
    return [items], {"tables": [{"header": ["", "", "Rechnung", "Datum", "Betrag"],
                                 "rows": rows}]}


def case_wrapped_description():
    items = [(44, 712, "Date"), (110, 712, "Libelle"), C(330, 712, "Montant"),
             (44, 698, "07/14/2026"), (110, 698, "Virement vers"), R(350, 698, "50.00"),
             (110, 687, "compte epargne"),
             (44, 673, "07/15/2026"), (110, 673, "Frais"), R(350, 673, "1.00"),
             (44, 659, "07/16/2026"), (110, 659, "Paiement carte"), R(350, 659, "12.30"),
             (110, 648, "magasin central")]
    return [items], {"tables": [{"header": ["Date", "Libelle", "Montant"], "rows": [
        ["07/14/2026", "Virement vers compte epargne", "50.00"],
        ["07/15/2026", "Frais", "1.00"],
        ["07/16/2026", "Paiement carte magasin central", "12.30"]]}]}


def case_right_aligned_centred():
    items = [(44, 712, "Article"), C(230, 712, "Quantity"), C(330, 712, "Unit Price"),
             C(450, 712, "Line Total")]
    rows = []
    for i, (q, u) in enumerate((("2", "1,250.00"), ("15", "9.99"), ("120", "0.75"))):
        y = 698 - 14 * i
        t = f"{float(q) * float(u.replace(',', '')):,.2f}"
        items += [(44, y, f"Part {i + 1}"), R(250, y, q), R(360, y, u), R(480, y, t)]
        rows.append([f"Part {i + 1}", q, u, t])
    return [items], {"tables": [{"header": ["Article", "Quantity", "Unit Price", "Line Total"],
                                 "rows": rows}]}


def case_side_panel_chart():
    items, table, _ = _statement(("Date", "Description", "Debit", "Credit", "Balance"), n=6)
    absent = []
    for k in range(7):
        t = f"Tip {k + 1}"
        items.append((548, 720 - 22 * k, t))
        absent.append(t)
    return [(items, [])], {"tables": [table], "absent": absent}


def case_watermark():
    items, table, _ = _statement(("Date", "Description", "Debit", "Credit", "Balance"), n=5)
    items.append({"x": 140, "y": 380, "text": "CONFIDENTIAL", "angle": 40, "size": 64,
                  "gray": 0.85})
    return [items], {"tables": [table], "absent": ["CONFIDENTIAL"]}


def case_multipage_shifted():
    w = ("Date", "Description", "Debit", "Credit", "Balance")
    p1, t1, bal = _statement(w, n=6)
    p2, t2, _ = _statement(w, n=6, y0=740, x_shift=12.0, heading=False, start=bal, day0=20)
    return [p1, p2], {"tables": [{"header": list(w), "rows": t1["rows"] + t2["rows"]}],
                      "once": list(w)}


def case_blank_cells():
    items, table, _ = _statement(("Fecha", "Concepto", "Cargo", "Abono", "Saldo"), n=8)
    return [items], {"tables": [table]}


def case_leading_zeros():
    items = [(44, 712, "Account No: 0025"), (300, 712, "Branch: 000123"),
             (44, 680, "Code"), (150, 680, "Name"), C(330, 680, "Amount")]
    rows = []
    for i, code in enumerate(("0007", "0042", "00911")):
        y = 666 - 14 * i
        items += [(44, y, code), (150, y, f"Unit {i}"), R(350, y, f"{i + 1}.00")]
        rows.append([code, f"Unit {i}", f"{i + 1}.00"])
    return [items], {"pairs": [["Account No:", "0025"], ["Branch:", "000123"]],
                     "tables": [{"header": ["Code", "Name", "Amount"], "rows": rows}],
                     "zeros": ["0025", "000123", "0007", "0042", "00911"]}


def case_trailing_minus():
    items = [(44, 712, "Date"), (110, 712, "Description"), C(330, 712, "Amount")]
    rows = []
    for i, a in enumerate(("26.08-", "100.00", "3.50-")):
        y = 698 - 14 * i
        items += [(44, y, f"07/0{i + 4}/2026"), (110, y, f"Entry {i}"), R(352, y, a)]
        rows.append([f"07/0{i + 4}/2026", f"Entry {i}", a])
    return [items], {"tables": [{"header": ["Date", "Description", "Amount"], "rows": rows}],
                     "trailing": ["26.08-", "3.50-"]}


def case_formula_text():
    items = [(44, 712, "Ref"), (220, 712, "Note"), C(400, 712, "Amount")]
    rows = []
    for i, (r, n) in enumerate((("=A1+1", "formula looking"), ("+44 20 7946", "phone"),
                                ("@team", "handle"), ("-ref", "dash led"))):
        y = 698 - 14 * i
        items += [(44, y, r), (220, y, n), R(420, y, f"{i + 1}.00")]
        rows.append([r, n, f"{i + 1}.00"])
    return [items], {"tables": [{"header": ["Ref", "Note", "Amount"], "rows": rows}],
                     "as_text": ["=A1+1", "+44 20 7946", "@team", "-ref"]}


def case_day_month():
    items = [(44, 712, "Datum"), (160, 712, "Omschrijving"), C(330, 712, "Bedrag")]
    rows, dates = [], {}
    for i, (d, m) in enumerate(((25, 12), (3, 1), (14, 2))):
        t = f"{d:02d}/{m:02d}/2026"
        y = 698 - 14 * i
        items += [(44, y, t), (160, y, f"Post {i}"), R(350, y, f"{i + 4}.00")]
        rows.append([t, f"Post {i}", f"{i + 4}.00"])
        dates[t] = [2026, m, d]
    return [items], {"tables": [{"header": ["Datum", "Omschrijving", "Bedrag"], "rows": rows}],
                     "dates": dates}


def case_month_day():
    items = [(44, 712, "Date"), (160, 712, "Memo"), C(330, 712, "Amount")]
    rows, dates = [], {}
    for i, (m, d) in enumerate(((12, 25), (1, 3), (2, 14))):
        t = f"{m:02d}/{d:02d}/2026"
        y = 698 - 14 * i
        items += [(44, y, t), (160, y, f"Memo {i}"), R(350, y, f"{i + 4}.00")]
        rows.append([t, f"Memo {i}", f"{i + 4}.00"])
        dates[t] = [2026, m, d]
    return [items], {"tables": [{"header": ["Date", "Memo", "Amount"], "rows": rows}],
                     "dates": dates}


def case_form_and_note():
    items = [{"x": 200, "y": 750, "text": "Payment Advice", "size": 16},
             (44, 712, "Payee: Northwind Partners"), (330, 712, "Reference: PA-2291"),
             (44, 698, "Issued: 08/14/2026"), (330, 698, "Total: 1,204.50"),
             (44, 660, "This advice is issued for information only and does not "
                       "replace the remittance terms agreed between the parties.")]
    return [items], {"pairs": [["Payee:", "Northwind Partners"], ["Reference:", "PA-2291"],
                               ["Issued:", "08/14/2026"], ["Total:", "1,204.50"]],
                     "absent": ["remittance terms"]}


CASES = {k[5:]: v for k, v in sorted(globals().items()) if k.startswith("case_")}


def build(out: Path = OUT) -> list:
    out.mkdir(parents=True, exist_ok=True)
    made = []
    for name, fn in CASES.items():
        pages, truth = fn()
        t1_pdf.make(out / f"{name}.pdf", pages)
        truth = {"name": name, "tables": [], "pairs": [], "absent": [], "zeros": [],
                 "dates": {}, **truth}
        (out / f"{name}.truth.json").write_text(json.dumps(truth, indent=1), encoding="utf-8")
        made.append(name)
    return made


if __name__ == "__main__":
    print("\n".join(build()))
