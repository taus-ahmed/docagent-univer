"""Bank-statement checks, behind the validator registry (validators.py).

  bank_summary          opening balance + total credits - total debits equals
                        the closing balance, within one cent
  bank_running_balance  where the transactions table has a Debit, a Credit and
                        a Balance column, each row's balance equals the
                        previous balance plus its credit minus its debit; the
                        opening balance stands before the first row and the
                        closing balance after the last, when extracted

A check runs only when every value it needs was extracted, and a role (two
`Closing Balance`s, two Balance columns) that is ambiguous runs nothing. A
value present but not a plain amount (`TBD`, `1.234,56`, `12.00 CR`) makes the
check UNREADABLE — never a guessed number. Debits are taken as magnitudes, so a
statement printing them negative checks the same.

The running check reads the table's rows in printed order, or reversed when a
statement lists newest first: the order with more consistent steps wins, and a
table consistent in NEITHER order follows a convention this check does not
know, so it does not run. A row whose text says it is a total is not a
transaction. A table some gate dropped rows from (another region, a duplicate,
an empty row — ctx.incomplete) is not checked: the gap is already flagged, and
a balance chain across it would call correct rows wrong.

Reason codes: balance_mismatch, balance_unreadable (OCR-READER-SEAM-DESIGN §12).
"""
from __future__ import annotations

from invoice_validators import CENT, _words, money
from validators import FAIL, PASS, UNREADABLE, CheckResult, register

BALANCE_MISMATCH = "balance_mismatch"
BALANCE_UNREADABLE = "balance_unreadable"

_CREDIT = {"credit", "credits", "deposit", "deposits"}
_DEBIT = {"debit", "debits", "withdrawal", "withdrawals"}
_NOT_AN_AMOUNT = {"id", "no", "number", "count", "items", "rate", "limit",
                  "average", "available", "interest", "date", "code"}
_TOTAL = {"total", "totals", "subtotal"}


def _w(label):
    w = _words(label)
    return (w - {"bal"}) | {"balance"} if "bal" in w else w


def role(label):
    """'opening' | 'closing' | 'credits' | 'debits' | ''."""
    w = _w(label)
    if not w or w & _NOT_AN_AMOUNT:
        return ""
    if "balance" in w and w & {"opening", "beginning", "starting", "previous",
                               "forward"}:
        return "opening"
    if "balance" in w and (w & {"closing", "ending", "final"} or "new" in w):
        return "closing"
    if w & _CREDIT and not w & _DEBIT:
        return "credits"
    if w & _DEBIT and not w & _CREDIT:
        return "debits"
    return ""


def _column(table, test):
    hits = [c["key"] for c in table.get("columns") or [] if test(_w(c.get("header")))]
    return hits[0] if len(hits) == 1 else None


def _txn_columns(table):
    cr = _column(table, lambda w: bool(w & _CREDIT or {"paid", "in"} <= w)
                 and not w & _DEBIT)
    dr = _column(table, lambda w: bool(w & _DEBIT or {"paid", "out"} <= w)
                 and not w & _CREDIT)
    bal = _column(table, lambda w: "balance" in w and not w & (_CREDIT | _DEBIT))
    return (cr, dr, bal) if cr and dr and bal else None


def _single(roles, name):
    got = roles.get(name) or []
    return got[0] if len(got) == 1 else None


def _summary(ctx, f):
    need = [f["opening"], f["credits"], f["debits"], f["closing"]]
    if None in need or any(x["ref"] not in ctx.values for x in need):
        return []
    ids = [x["ref"] for x in need]
    vals = [money(ctx.values[r]) for r in ids]
    if None in vals:
        return [CheckResult(
            "bank_summary", UNREADABLE, ids, BALANCE_UNREADABLE,
            {r: {"balance_check": "unreadable"} for r in ids},
            notes=["bank statement balance check could not be completed — "
                   + ", ".join(x["row_label"] for x, v in zip(need, vals) if v is None)
                   + " is not a plain amount"])]
    opening, credits, debits, closing = vals
    want = opening + abs(credits) - abs(debits)
    ok = abs(want - closing) <= CENT
    return [CheckResult(
        "bank_summary", PASS if ok else FAIL, ids,
        "" if ok else BALANCE_MISMATCH,
        {r: {"balance_check": "pass" if ok else "fail"} for r in ids},
        flags=[] if ok else [(
            f["closing"]["row_label"], ctx.values[f["closing"]["ref"]],
            f"opening balance + credits - debits comes to {want}, not the "
            f"closing balance {closing} — one of them is wrong")],
        notes=[] if ok else [
            f"bank statement: opening + credits - debits = {want}; closing "
            f"reads {closing} — MISMATCH, all four values marked low"])]


def _transactions(ctx, table, cols):
    """[(i, row)] in printed order, leaving out rows whose text is a total."""
    return [(i, r) for i, r in enumerate(ctx.rows.get(table["name"]) or [])
            if not any(_w(v) & _TOTAL for k, v in r.items()
                       if k not in cols and not str(k).startswith("_"))]


def _chain(ctx, name, cols, ordered, opening, closing):
    """[(ids, status, (want, got, at) | None)], one per balance step."""
    cr, dr, bal = cols
    out = []
    prev_ids, prev = [], None
    if opening is not None:
        prev_ids, prev = [opening["ref"]], money(ctx.values[opening["ref"]])
        if prev is None:
            prev_ids, prev = [opening["ref"]], "?"
    span, delta, odd = [], 0, False
    for i, r in ordered:
        ref = f"{name}_rows[{i}]"
        span.append(ref)
        for k, sign in ((cr, 1), (dr, -1)):
            s = str(r.get(k) or "").strip()
            if s:
                v = money(s)
                if v is None:
                    odd = True
                else:
                    delta += sign * abs(v)
        b_text = str(r.get(bal) or "").strip()
        if not b_text:
            continue                        # balance printed later: carry
        b = money(b_text)
        if prev is not None:
            ids = prev_ids + span
            if odd or b is None or prev == "?":
                out.append((ids, UNREADABLE, None))
            else:
                want = prev + delta
                out.append((ids, PASS if abs(want - b) <= CENT else FAIL,
                            (want, b, ref)))
        prev_ids, prev = [ref], ("?" if b is None else b)
        span, delta, odd = [], 0, False
    if closing is not None and prev is not None:
        c = money(ctx.values[closing["ref"]])
        ids = prev_ids + span + [closing["ref"]]
        if odd or c is None or prev == "?":
            out.append((ids, UNREADABLE, None))
        else:
            want = prev + delta
            out.append((ids, PASS if abs(want - c) <= CENT else FAIL,
                        (want, c, closing["ref"])))
    return out


def _running(ctx, f):
    out = []
    tables = [(t, _txn_columns(t)) for t in ctx.tables or []]
    tables = [(t, c) for t, c in tables if c]
    if len(tables) != 1:
        return out
    t, cols = tables[0]
    if t["name"] in (ctx.incomplete or ()):
        return out
    rows = _transactions(ctx, t, cols)
    if not rows:
        return out
    opening = f["opening"] if f["opening"] and f["opening"]["ref"] in ctx.values else None
    closing = f["closing"] if f["closing"] and f["closing"]["ref"] in ctx.values else None
    readings = [_chain(ctx, t["name"], cols, rows, opening, closing),
                _chain(ctx, t["name"], cols, rows[::-1], opening, closing)]
    passes = [sum(s == PASS for _i, s, _d in r) for r in readings]
    if not any(passes) and any(s == FAIL for r in readings for _i, s, _d in r):
        return out                          # consistent in neither order
    steps = readings[0] if passes[0] >= passes[1] else readings[1]
    anchors = [x["ref"] for x in (opening, closing) if x]
    for ids, status, detail in steps:
        if status == FAIL:
            want, got, at = detail
            out.append(CheckResult(
                "bank_running_balance", FAIL, ids, BALANCE_MISMATCH,
                {r: {"running_balance_check": "fail"} for r in ids if r in anchors},
                flags=[(f'{t["name"]}[balance]', str(got),
                        f"the previous balance plus this row's credit minus its "
                        f"debit comes to {want}, not the balance {got} — a "
                        f"row, a balance or a missing row is wrong")],
                notes=[f"bank statement running balance: expected {want}, "
                       f"printed {got} at {at} — MISMATCH, the rows either "
                       f"side marked low"]))
        elif status == UNREADABLE:
            out.append(CheckResult(
                "bank_running_balance", UNREADABLE, ids, BALANCE_UNREADABLE,
                {r: {"running_balance_check": "unreadable"} for r in ids
                 if r in anchors},
                notes=["bank statement running balance could not be checked "
                       "across a row whose debit, credit or balance is not a "
                       "plain amount"]))
    if steps and all(s == PASS for _i, s, _d in steps):
        out.append(CheckResult(
            "bank_running_balance", PASS, [],
            evidence={r: {"running_balance_check": "pass"} for r in anchors}))
    return out


def bank_balances(ctx):
    roles = {}
    for fld in ctx.fields:
        r = role(fld["row_label"])
        if r:
            roles.setdefault(r, []).append(fld)
    if any(len(v) > 1 for v in roles.values()):
        return []                           # ambiguous: do not guess
    f = {k: _single(roles, k) for k in ("opening", "credits", "debits", "closing")}
    return _summary(ctx, f) + _running(ctx, f)


register("bank_statement", bank_balances)
