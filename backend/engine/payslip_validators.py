"""Payslip checks, behind the validator registry (validators.py).

  payslip_net_pay     gross pay - total deductions equals net pay, within one
                      cent
  payslip_deductions  the listed deductions sum to the total deductions,
                      within one cent per line, when both are extracted

A check runs only when every value it needs was extracted. A role is read from
the label, and only an UNQUALIFIED label takes it: `YTD Gross Earnings`,
`Total Pre-Tax Deductions` and `Annual Salary` are different quantities, so a
label carrying any word beyond the role's own is not the role — and two labels
taking one role run nothing. A value present but not a plain amount makes the
check UNREADABLE — never a guessed number. Deductions are taken as magnitudes,
so a payslip printing them in parentheses or negative checks the same.

The listed deductions are the rows of the one table whose name or section names
deductions, read from its one amount column. A row whose text says it is a
total is the table's own total line, not a deduction. A table some gate dropped
rows from (ctx.incomplete) is not summed: the loss is already flagged, and a
sum over what is left would call a correct total wrong.

Reason codes: payslip_mismatch, payslip_unreadable (OCR-READER-SEAM-DESIGN §12).
"""
from __future__ import annotations

from invoice_validators import CENT, _words, money
from validators import FAIL, PASS, UNREADABLE, CheckResult, register

PAYSLIP_MISMATCH = "payslip_mismatch"
PAYSLIP_UNREADABLE = "payslip_unreadable"

_PERIOD = {"current", "this", "period", "amount"}
_GROSS = {"gross", "total", "earnings", "pay", "wages"} | _PERIOD
_DEDUCT = {"total", "deduction", "deductions"} | _PERIOD
_NET = {"net", "pay", "salary", "wages", "take", "home"} | _PERIOD
_TOTAL = {"total", "totals", "subtotal"}
_YTD = {"ytd", "year", "date", "annual"}


def role(label):
    """'gross' | 'deductions' | 'net' | ''."""
    w = _words(label)
    if not w:
        return ""
    if w <= _GROSS and ("gross" in w or "total" in w and w & {"earnings", "wages"}):
        return "gross"
    if w <= _DEDUCT and w & {"deduction", "deductions"} and (
            "total" in w or w == {"deductions"}):
        return "deductions"
    if w <= _NET and ("net" in w or {"take", "home"} <= w):
        return "net"
    return ""


def _deduction_table(ctx):
    hits = [t for t in ctx.tables or []
            if _words(f'{t.get("name", "")} {t.get("section") or ""}')
            & {"deduction", "deductions"}]
    if len(hits) != 1:
        return None, None
    t = hits[0]
    cols = [c["key"] for c in t.get("columns") or []
            if _words(c.get("header")) & {"amount", "current", "total"}
            and not _words(c.get("header")) & _YTD]
    return (t, cols[0]) if len(cols) == 1 else (None, None)


def _listed(ctx, total):
    t, key = _deduction_table(ctx)
    if not t or t["name"] in (ctx.incomplete or ()):
        return []
    rows = [(i, r) for i, r in enumerate(ctx.rows.get(t["name"]) or [])
            if str(r.get(key) or "").strip()
            and not any(_words(v) & _TOTAL for k, v in r.items()
                        if k != key and not str(k).startswith("_"))]
    if not rows:
        return []
    ids = [total["ref"]] + [f'{t["name"]}_rows[{i}]' for i, _r in rows]
    amounts = [money(r[key]) for _i, r in rows]
    want = money(ctx.values[total["ref"]])
    if want is None or None in amounts:
        return [CheckResult(
            "payslip_deductions", UNREADABLE, ids, PAYSLIP_UNREADABLE,
            evidence={total["ref"]: {"deductions_check": "unreadable"}},
            notes=["payslip deductions check could not be completed — a "
                   "deduction or the total deductions is not a plain amount"])]
    got = sum(abs(a) for a in amounts)
    ok = abs(got - abs(want)) <= CENT * len(amounts)
    return [CheckResult(
        "payslip_deductions", PASS if ok else FAIL, ids,
        "" if ok else PAYSLIP_MISMATCH,
        evidence={total["ref"]: {"deductions_check": "pass" if ok else "fail"}},
        flags=[] if ok else [(
            total["row_label"], ctx.values[total["ref"]],
            f"the {len(amounts)} listed deduction(s) sum to {got}, not the "
            f"total deductions {abs(want)} — a line or the total is wrong")],
        notes=[] if ok else [
            f"payslip deductions sum to {got}; total reads {abs(want)} — "
            f"MISMATCH, the total and every deduction marked low"])]


def _net_pay(ctx, gross, total, net):
    ids = [gross["ref"], total["ref"], net["ref"]]
    vals = [money(ctx.values[r]) for r in ids]
    if None in vals:
        return [CheckResult(
            "payslip_net_pay", UNREADABLE, ids, PAYSLIP_UNREADABLE,
            {r: {"net_pay_check": "unreadable"} for r in ids},
            notes=["payslip net pay check could not be completed — "
                   + ", ".join(f["row_label"] for f, v in
                               zip((gross, total, net), vals) if v is None)
                   + " is not a plain amount"])]
    g, d, n = vals
    want = g - abs(d)
    ok = abs(want - n) <= CENT
    return [CheckResult(
        "payslip_net_pay", PASS if ok else FAIL, ids,
        "" if ok else PAYSLIP_MISMATCH,
        {r: {"net_pay_check": "pass" if ok else "fail"} for r in ids},
        flags=[] if ok else [(
            net["row_label"], ctx.values[net["ref"]],
            f"gross pay minus total deductions comes to {want}, not the net "
            f"pay {n} — one of them is wrong")],
        notes=[] if ok else [
            f"payslip: gross - deductions = {want}; net pay reads {n} — "
            f"MISMATCH, all three values marked low"])]


def payslip_totals(ctx):
    roles = {}
    for f in ctx.fields:
        r = role(f["row_label"])
        if r:
            roles.setdefault(r, []).append(f)
    if any(len(v) > 1 for v in roles.values()):
        return []                           # ambiguous: do not guess
    gross, total, net = (next((f for f in roles.get(k, [])
                               if f["ref"] in ctx.values), None)
                         for k in ("gross", "deductions", "net"))
    out = []
    if gross and total and net:
        out += _net_pay(ctx, gross, total, net)
    if total:
        out += _listed(ctx, total)
    return out


register("payslip", payslip_totals)
