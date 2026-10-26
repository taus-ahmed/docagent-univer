#!/usr/bin/env python
"""Synthetic multi-locale documents with truth (Part 1.8). DEV ONLY.

Fictional people, companies and accounts; every number made up. Builds, in
memory or into --out:

  bank statements in six styles   US, UK, EU (comma decimals), India (lakh
                                  grouping, Dr/Cr), UAE, Japan (yen, no decimals)
  invoices with tax lines         US sales tax, UK VAT, India GST
  a payslip and a receipt
  corrupted variants              one wrong digit, a dropped row, swapped
                                  debit/credit, mixed currency, ambiguous date

Each document as a native PDF, a degraded scan of it, and a password-protected
copy. `documents()` returns the specs (lines, truth, template, expected flags)
for tests/test_locale_fixtures.py, which reads them through the engine with a
model stub answering FROM THE TRUTH (quoting the exact printed line).
"""
from __future__ import annotations

import argparse
import copy
import io
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_scan_variants import build_pdf  # noqa: E402

PASSWORD = "Fixture-Pass-1"

# ── locales ──────────────────────────────────────────────────────────────────

def _fmt(value_cents: int, style: str) -> str:
    neg = value_cents < 0
    v = abs(value_cents)
    whole, frac = divmod(v, 100)
    if style == "jp":
        s = f"{(v + 50) // 100:,}"
    elif style == "in":
        w = str(whole)
        head, tail = w[:-3], w[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts + [tail]) + f".{frac:02d}"
    elif style == "eu":
        s = f"{whole:,}".replace(",", ".") + f",{frac:02d}"
    else:
        s = f"{whole:,}.{frac:02d}"
    return ("-" if neg else "") + s


LOCALES = {
    #        style  money prefix/suffix          date order
    "us": dict(style="us", cur=("$", ""), code="USD", date="{m:02d}/{d:02d}/{y}", locale="en-US"),
    "uk": dict(style="us", cur=("£", ""), code="GBP", date="{d:02d}/{m:02d}/{y}", locale="en-GB"),
    "eu": dict(style="eu", cur=("", " €"), code="EUR", date="{d:02d}.{m:02d}.{y}", locale="de-DE"),
    "in": dict(style="in", cur=("Rs. ", ""), code="INR", date="{d:02d}-{m:02d}-{y}", locale="en-IN"),
    "ae": dict(style="us", cur=("AED ", ""), code="AED", date="{d:02d}/{m:02d}/{y}", locale="en-AE"),
    "jp": dict(style="jp", cur=("¥", ""), code="JPY", date="{y}/{m:02d}/{d:02d}", locale="ja-JP"),
}


def money(cents, loc, bare=False):
    L = LOCALES[loc]
    s = _fmt(cents, L["style"])
    return s if bare else f"{L['cur'][0]}{s}{L['cur'][1]}"


def date(loc, y, m, d):
    return LOCALES[loc]["date"].format(y=y, m=m, d=d)


# ── documents ────────────────────────────────────────────────────────────────

def _grid(labels, table=None):
    cells = {f"{r},0": {"value": lab} for r, lab in enumerate(labels)}
    regions = []
    if table:
        r0 = len(labels) + 1
        for c, h in enumerate(table):
            cells[f"{r0},{c}"] = {"value": h}
        regions = [{"type": "table", "r1": r0, "c1": 0, "r2": r0 + 12,
                    "c2": len(table) - 1, "orientation": "rows", "name": "rows"}]
    return {"cells": cells, "colWidths": [], "merges": {}, "repeatRows": [], "regions": regions}


def bank_statement(loc, rng, dr_cr=None):
    """Opening + credits - debits = closing, a running balance per row."""
    dr_cr = loc == "in" if dr_cr is None else dr_cr
    scale = 100 if loc in ("jp", "in") else 1     # yen and lakhs need size
    bal = rng.randrange(500_000, 2_000_000) * scale
    opening = bal
    rows, debits, credits = [], 0, 0
    for i in range(6):
        amt = rng.randrange(1_000, 90_000) * scale
        if loc == "jp":
            amt = (amt // 100) * 100                  # whole yen
        is_credit = i % 3 == 0
        bal += amt if is_credit else -amt
        credits += amt if is_credit else 0
        debits += 0 if is_credit else amt
        day = 3 + 4 * i
        desc = ["Salary credit", "Grocery store", "Electricity bill",
                "Client payment", "Fuel station", "Restaurant"][i]
        if dr_cr:
            rows.append({"Date": date(loc, 2024, 3, day), "Particulars": desc,
                         "Amount": money(amt, loc, bare=True) + (" Cr" if is_credit else " Dr"),
                         "Balance": money(bal, loc, bare=True) + " Cr"})
        else:
            rows.append({"Date": date(loc, 2024, 3, day), "Description": desc,
                         "Debit": "" if is_credit else money(amt, loc, bare=True),
                         "Credit": money(amt, loc, bare=True) if is_credit else "",
                         "Balance": money(bal, loc, bare=True)})
    fields = {"Account Holder": "Avery Fictional", "Account Number": "000123456789",
              "Opening Balance": money(opening, loc), "Total Credits": money(credits, loc),
              "Total Debits": money(debits, loc), "Closing Balance": money(bal, loc),
              "Number of Transactions": str(len(rows))}
    cols = list(rows[0])
    return {"family": "bank_statement", "title": "STATEMENT OF ACCOUNT", "fields": fields,
            "columns": cols, "rows": rows, "locale": LOCALES[loc]["locale"]}


def invoice(loc, rng, tax="sales tax", rate=8):
    items = [("Consulting hours", rng.randrange(20_000, 90_000)),
             ("Software licence", rng.randrange(10_000, 50_000)),
             ("Travel", rng.randrange(5_000, 20_000))]
    sub = sum(a for _n, a in items)
    fields = {"Invoice Number": f"INV-{rng.randrange(1000, 9999)}",
              "Invoice Date": date(loc, 2024, 4, 18), "Bill To": "Northwind Fictional Ltd",
              "Subtotal": money(sub, loc)}
    if tax == "GST":
        half = sub * rate // 200
        fields.update({"CGST": money(half, loc), "SGST": money(half, loc),
                       "Total": money(sub + 2 * half, loc),
                       "GSTIN": "27AAPFU0939F1ZV"})
    else:
        t = sub * rate // 100
        fields.update({tax.title(): money(t, loc), "Total": money(sub + t, loc)})
    rows = [{"Description": n, "Amount": money(a, loc, bare=True)} for n, a in items]
    return {"family": "invoice", "title": "TAX INVOICE" if tax != "sales tax" else "INVOICE",
            "fields": fields, "columns": ["Description", "Amount"], "rows": rows,
            "locale": LOCALES[loc]["locale"]}


def payslip(loc, rng):
    gross = rng.randrange(300_000, 900_000)
    ded = gross * 22 // 100
    return {"family": "payslip", "title": "PAYSLIP", "fields": {
        "Employee": "Jordan Example", "Pay Period": "April 2024",
        "Gross Pay": money(gross, loc), "Total Deductions": money(ded, loc),
        "Net Pay": money(gross - ded, loc)}, "columns": [], "rows": [],
        "locale": LOCALES[loc]["locale"]}


def receipt(loc, rng):
    items = [("Coffee", 450), ("Sandwich", 890), ("Water", 199)]
    sub = sum(a for _n, a in items)
    tax = sub * 7 // 100
    return {"family": "receipt", "title": "RECEIPT", "fields": {
        "Merchant": "Cafe Imaginaire", "Date": date(loc, 2024, 5, 21),
        "Subtotal": money(sub, loc), "Tax": money(tax, loc), "Total": money(sub + tax, loc)},
        "columns": ["Item", "Amount"],
        "rows": [{"Item": n, "Amount": money(a, loc, bare=True)} for n, a in items],
        "locale": LOCALES[loc]["locale"]}


def corrupt(doc, kind, rng):
    """A copy with one defect, and the flag the engine must raise for it."""
    d = copy.deepcopy(doc)
    if kind == "wrong_digit":
        v = d["fields"]["Closing Balance"]
        # a SIGNIFICANT digit (the first one that is not 9): a cent would sit
        # inside the check's one-cent tolerance
        i = min(k for k, ch in enumerate(v) if ch.isdigit() and ch not in "9")
        d["fields"]["Closing Balance"] = v[:i] + str(int(v[i]) + 1) + v[i + 1:]
        expect = "balance_mismatch"
    elif kind == "dropped_row":
        d["rows"].pop(2)
        expect = "row_count_mismatch"
    elif kind == "swapped_debit_credit":
        r = d["rows"][1]
        r["Debit"], r["Credit"] = r["Credit"], r["Debit"]
        expect = "balance_mismatch"
    elif kind == "mixed_currency":
        d["fields"]["Total Debits"] = d["fields"]["Total Debits"].replace("$", "€")
        expect = "currency_mismatch"
    elif kind == "ambiguous_date":
        for r in d["rows"]:                    # every date day <= 12: no evidence
            m = r["Date"].split("/")
            r["Date"] = f"{m[0]}/{int(m[1]) % 12 + 1:02d}/{m[2]}"
        d["locale"] = None
        expect = "date_ambiguous"
    else:
        raise ValueError(kind)
    d["corruption"] = kind
    d["expect_flags"] = [expect]
    return d


def documents(seed=7):
    rng = random.Random(seed)
    docs = {}
    for loc in LOCALES:
        docs[f"statement_{loc}"] = bank_statement(loc, rng)
    docs["invoice_us_sales_tax"] = invoice("us", rng, "sales tax", 8)
    docs["invoice_uk_vat"] = invoice("uk", rng, "VAT", 20)
    docs["invoice_in_gst"] = invoice("in", rng, "GST", 18)
    docs["payslip_uk"] = payslip("uk", rng)
    docs["receipt_eu"] = receipt("eu", rng)
    base = docs["statement_us"]
    for kind in ("wrong_digit", "dropped_row", "swapped_debit_credit",
                 "mixed_currency", "ambiguous_date"):
        docs[f"statement_us_{kind}"] = corrupt(base, kind, rng)
    for name, d in docs.items():
        d.setdefault("expect_flags", [])
        d["id"] = name
        d["lines"] = render_lines(d)
        d["template"] = {"layout": _grid(list(d["fields"]), d["columns"] or None),
                         "doc_type": d["family"], "mode": "layout", "locale": d["locale"]}
    return docs


def render_lines(d):
    """The printed lines, top to bottom; a row's line is what its quote is."""
    lines = [d["title"]] + [f"{k}: {v}" for k, v in d["fields"].items()]
    if d["columns"]:
        lines.append("   ".join(d["columns"]))
        for r in d["rows"]:
            lines.append("   ".join(r[c] if r[c] else "-" for c in d["columns"]))
    return lines


def _ops(lines) -> bytes:
    """Text operators in cp1252 — the font's WinAnsiEncoding, so € and £
    print as themselves (make_scan_variants encodes Latin-1, where € is not)."""
    out = [b"BT", b"0 Tr"]
    for i, text in enumerate(lines):
        enc = (text.encode("cp1252", "replace").replace(b"\\", b"\\\\")
               .replace(b"(", b"\\(").replace(b")", b"\\)"))
        out.append(f"/F1 10 Tf 1 0 0 1 56 {780 - 18 * i} Tm (".encode() + enc + b") Tj")
    out.append(b"ET")
    return b"\n".join(out)


def native_pdf(d) -> bytes:
    ops = _ops(d["lines"])
    return build_pdf([{"w_pt": 612, "h_pt": 792, "ops": ops}])


def scan_pdf(d, seed=1) -> bytes:
    """The native page rendered at 200 dpi, skewed, noised, as an image-only page."""
    from pdf2image import convert_from_bytes
    from PIL import Image, ImageFilter
    img = convert_from_bytes(native_pdf(d), dpi=200)[0].convert("L")
    rng = random.Random(seed)
    img = img.rotate(rng.uniform(-1.5, 1.5), expand=False, fillcolor=255).filter(ImageFilter.GaussianBlur(0.6))
    px = img.load()
    for _ in range(img.width * img.height // 400):
        x, y = rng.randrange(img.width), rng.randrange(img.height)
        px[x, y] = rng.choice((0, 255))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=70)
    return build_pdf([{"w_pt": 612, "h_pt": 792, "jpeg": buf.getvalue(),
                       "jpeg_px": img.size}])


def locked_pdf(d) -> bytes:
    from pypdf import PdfReader, PdfWriter
    w = PdfWriter(clone_from=PdfReader(io.BytesIO(native_pdf(d))))
    w.encrypt(user_password=PASSWORD, owner_password=PASSWORD + "-owner")
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for name, d in documents().items():
        (out / f"{name}.pdf").write_bytes(native_pdf(d))
        (out / f"{name}.scan.pdf").write_bytes(scan_pdf(d))
        (out / f"{name}.locked.pdf").write_bytes(locked_pdf(d))
        manifest[name] = {k: d[k] for k in ("family", "locale", "fields", "rows", "expect_flags")}
    (out / "truth.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(manifest)} documents x 3 forms -> {out}")


if __name__ == "__main__":
    main()
