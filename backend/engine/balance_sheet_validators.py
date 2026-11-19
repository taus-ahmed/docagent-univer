"""Balance-sheet identity (Run C, C8), behind the validator registry.

ONE check, flag only: when a record holds both TOTAL ASSETS and TOTAL
LIABILITIES & EQUITY and they differ by more than rounding, both values are
exactly low with `assets_not_equal_liabilities_plus_equity` and the flag
states the difference. Equal totals raise nothing. Nothing is recomputed or
corrected, and no other accounting check lives here.

Registered for ANY family and keyed on the two labels, because a balance
sheet arrives under several document-type names (balance_sheet,
financial_statement, ...) and the labels are what identify the two totals.
"""
from __future__ import annotations

import re
from decimal import Decimal

from validators import ANY, FAIL, PASS, CheckResult, register

IDENTITY_FAILED = "assets_not_equal_liabilities_plus_equity"


def _norm(label) -> str:
    t = str(label or "").casefold().replace("&", " and ")
    t = re.sub(r"[’'`]", "", t)
    return " ".join(re.sub(r"[^a-z0-9]+", " ", t).split())


_ASSETS = re.compile(r"^total assets$")
_LIAB_EQ = re.compile(r"^total liabilities and (?:(?:share|stock)holders |owners |"
                      r"members |partners )?(?:equity|capital|net worth)$")


def role_of(label) -> str:
    n = _norm(label)
    if _ASSETS.match(n):
        return "assets"
    if _LIAB_EQ.match(n):
        return "liab_eq"
    return ""


def _found(ctx):
    """{role: [(ref, label, value text)]} over field slots and table rows."""
    out = {}
    for f in ctx.fields:
        r = role_of(f.get("row_label"))
        if r and str(ctx.values.get(f["ref"], "")).strip():
            out.setdefault(r, []).append((f["ref"], f["row_label"], ctx.values[f["ref"]]))
    for name, rows in (ctx.rows or {}).items():
        for i, row in enumerate(rows or []):
            if not isinstance(row, dict):
                continue
            cells = [(k, v) for k, v in row.items() if not str(k).startswith("_")]
            label = next((v for _k, v in cells if role_of(v)), None)
            if not label:
                continue
            amt = next((v for _k, v in cells if v is not label and _amount(v)), None)
            if amt is not None:
                out.setdefault(role_of(label), []).append(
                    (f"{name}_rows[{i}]", str(label), amt))
    return out


def _amount(text):
    from amounts import parse_amount
    a = parse_amount(str(text or "").strip())
    return a if (a.ok and not a.percent) else None


def balance_identity(ctx):
    found = _found(ctx)
    if len(found.get("assets", [])) != 1 or len(found.get("liab_eq", [])) != 1:
        return []                      # absent, or ambiguous: nothing to compare
    (ra, la, va), (rl, ll, vl) = found["assets"][0], found["liab_eq"][0]
    a, b = _amount(va), _amount(vl)
    if a is None or b is None:
        return []
    places = max(a.decimals or 0, b.decimals or 0)
    tol = Decimal(1).scaleb(-places)   # one unit of the last printed place
    diff = Decimal(str(a.value)) - Decimal(str(b.value))
    if abs(diff) <= tol:
        return [CheckResult("balance_identity", PASS, [ra, rl], "",
                            evidence={ra: {"balance_identity": "pass"},
                                      rl: {"balance_identity": "pass"}})]
    shown = f"{abs(diff):,.{places}f}"
    said = (f"{IDENTITY_FAILED}: {la} {va} and {ll} {vl} differ by {shown} — "
            f"a balance sheet's assets equal its liabilities plus equity")
    return [CheckResult(
        "balance_identity", FAIL, [ra, rl], IDENTITY_FAILED,
        evidence={ra: {"balance_identity": "fail", "difference": shown},
                  rl: {"balance_identity": "fail", "difference": shown}},
        flags=[(la, va, said), (ll, vl, said)], notes=[said],
        validation={"balance_identity_difference": shown})]


register(ANY, balance_identity)
