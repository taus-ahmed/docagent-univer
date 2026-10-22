"""Invoice-family checks, behind the validator registry (validators.py).

  invoice_lines_total   the line items' amounts sum to the subtotal, within
                        one cent per line (each printed line may be rounded)
  invoice_grand_total   subtotal + charges (shipping, handling, freight, fees)
                        + tax - discount equals the total, within one cent

A check runs only when every value it needs was extracted; a document that
lacks them is untouched. A value present but not a plain amount (`TBD`,
`1.234,56`) makes the check UNREADABLE — never a guessed number. Roles are
read from the template's labels; when a role is ambiguous (two `Total`s) the
check does not run.

Reason codes: totals_mismatch, totals_unreadable (OCR-READER-SEAM-DESIGN §12).
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from validators import FAIL, PASS, UNREADABLE, CheckResult, register

TOTALS_MISMATCH = "totals_mismatch"
TOTALS_UNREADABLE = "totals_unreadable"
CENT = Decimal("0.01")

_CHARGE = {"shipping", "handling", "freight", "delivery", "postage", "fee",
           "fees", "surcharge"}
_NOT_AN_AMOUNT = {"id", "no", "number", "rate", "percent", "code", "reg",
                  "registration", "exempt"}


def _words(label):
    return set(re.sub(r"[^a-z ]+", " ", str(label or "").lower()
                      .replace("sub-total", "subtotal")
                      .replace("sub total", "subtotal")).split())


def role(label):
    """'subtotal' | 'tax' | 'discount' | 'charge' | 'total' | ''."""
    w = _words(label)
    # A `%` in the label is NOT a reason to skip it: `Sales Tax (8.88%)` names
    # its rate and holds the tax amount (both gold invoices). A label that is
    # a rate ("Tax Rate") is excluded by its words; a value that is a rate
    # ("8.88%") is not a plain amount, so the check is unreadable, not wrong.
    if not w or w & _NOT_AN_AMOUNT:
        return ""
    if "subtotal" in w:
        return "subtotal"
    if w & {"tax", "vat", "gst", "hst"}:
        return "tax"
    if "discount" in w:
        return "discount"
    if w & _CHARGE:
        return "charge"
    if "total" in w or {"amount", "due"} <= w or {"balance", "due"} <= w:
        return "total"
    return ""


def money(text):
    """Decimal, or None when the string is not one plain amount.
    `$1,234.56`, `1234.5`, `(10.00)` and `-10.00` (negative) are amounts."""
    t = re.sub(r"[\s$€£]|USD|EUR|GBP", "", str(text or ""))
    neg = t.startswith("(") and t.endswith(")") or t.startswith("-")
    t = t.strip("()-")
    if not re.fullmatch(r"\d{1,3}(,\d{3})*(\.\d{1,2})?|\d+(\.\d{1,2})?", t):
        return None
    try:
        v = Decimal(t.replace(",", ""))
    except InvalidOperation:
        return None
    return -v if neg else v


def _line_column(table):
    """The one column of a line-items table holding each line's amount."""
    cols = [c for c in table.get("columns") or []]
    hits = [c for c in cols if _words(c.get("header")) & {"amount", "total",
                                                         "extended", "ext"}
            and not _words(c.get("header")) & {"unit", "tax", "price", "rate"}]
    return hits[0]["key"] if len(hits) == 1 else None


def _roles(fields):
    out = {}
    for f in fields:
        r = role(f["row_label"])
        if r:
            out.setdefault(r, []).append(f)
    return out


def invoice_totals(ctx):
    roles = _roles(ctx.fields)
    if any(len(roles.get(r, [])) > 1 for r in ("subtotal", "tax", "discount", "total")):
        return []                                   # ambiguous: do not guess
    out = []
    sub = (roles.get("subtotal") or [None])[0]
    total = (roles.get("total") or [None])[0]

    # ── lines -> subtotal ──
    lined = [(t, _line_column(t)) for t in (ctx.tables or [])]
    lined = [(t, k) for t, k in lined if k]
    if sub and sub["ref"] in ctx.values and len(lined) == 1:
        t, key = lined[0]
        rows = [(i, r) for i, r in enumerate(ctx.rows.get(t["name"]) or [])
                if str(r.get(key) or "").strip()]
        if rows:
            ids = [sub["ref"]] + [f'{t["name"]}_rows[{i}]' for i, _r in rows]
            amounts = [money(r[key]) for _i, r in rows]
            s = money(ctx.values[sub["ref"]])
            if s is None or None in amounts:
                out.append(CheckResult(
                    "invoice_lines_total", UNREADABLE, ids, TOTALS_UNREADABLE,
                    evidence={sub["ref"]: {"lines_check": "unreadable"}},
                    notes=["invoice line-items check could not be completed — "
                           "a line amount or the subtotal is not a plain amount"]))
            else:
                got = sum(amounts)
                ok = abs(got - s) <= CENT * len(amounts)
                out.append(CheckResult(
                    "invoice_lines_total", PASS if ok else FAIL, ids,
                    "" if ok else TOTALS_MISMATCH,
                    evidence={sub["ref"]: {"lines_check": "pass" if ok else "fail"}},
                    flags=[] if ok else [(
                        sub["row_label"], ctx.values[sub["ref"]],
                        f"the {len(amounts)} line item(s) sum to {got}, not the "
                        f"subtotal {s} — a line or the subtotal is wrong")],
                    notes=[] if ok else [
                        f"invoice line items sum to {got}; subtotal reads {s} — "
                        f"MISMATCH, the subtotal and every line marked low"]))

    # ── subtotal + charges + tax - discount -> total ──
    # An amount the roles do not know, printed between Subtotal and Total
    # (`Bottle deposit`), may be part of the sum: do not guess, do not run.
    unknown = [f for f in ctx.fields
               if sub and total and f.get("row") is not None
               and sub.get("row", -1) < f["row"] < total.get("row", -1)
               and not role(f["row_label"]) and money(ctx.values.get(f["ref"])) is not None]
    if sub and total and sub["ref"] in ctx.values and total["ref"] in ctx.values             and not unknown:
        parts = [f for r in ("charge", "tax", "discount") for f in roles.get(r, [])
                 if f["ref"] in ctx.values]
        ids = [sub["ref"]] + [f["ref"] for f in parts] + [total["ref"]]
        vals = {ref: money(ctx.values[ref]) for ref in ids}
        evidence = {ref: {"totals_check": None} for ref in ids}
        if None in vals.values():
            for e in evidence.values():
                e["totals_check"] = "unreadable"
            out.append(CheckResult(
                "invoice_grand_total", UNREADABLE, ids, TOTALS_UNREADABLE, evidence,
                notes=["invoice total check could not be completed — "
                       + ", ".join(f["row_label"] for f in [sub, total] + parts
                                   if vals[f["ref"]] is None)
                       + " is not a plain amount"]))
        else:
            want = vals[sub["ref"]]
            for f in parts:
                v = vals[f["ref"]]
                want += -abs(v) if role(f["row_label"]) == "discount" else v
            ok = abs(want - vals[total["ref"]]) <= CENT
            for e in evidence.values():
                e["totals_check"] = "pass" if ok else "fail"
            out.append(CheckResult(
                "invoice_grand_total", PASS if ok else FAIL, ids,
                "" if ok else TOTALS_MISMATCH, evidence,
                flags=[] if ok else [(
                    total["row_label"], ctx.values[total["ref"]],
                    f"subtotal, charges, tax and discount come to {want}, not "
                    f"the total {vals[total['ref']]} — one of them is wrong")],
                notes=[] if ok else [
                    f"invoice total: computed {want}, printed "
                    f"{vals[total['ref']]} — MISMATCH, every value in the sum "
                    f"marked low"]))
    return out


register("invoice", invoice_totals)
