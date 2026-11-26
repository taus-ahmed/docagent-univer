"""Run Q, Q3 — "no-math" checks: arithmetic the document itself states.

Never a correction. Every check here only FLAGS: the cells involved go low
with a reason naming the numbers, and the document's own numbers stay as
printed. Three checks:

  label_arithmetic   (ANY family) a label that states its own sum -
                     SSA-1099 "Box 5. Net Benefits (Box 3 minus Box 4)",
                     "Line 3 (line 1 plus line 2)". The operands are the slots
                     whose labels name those boxes/lines. Job 79 read Box 3
                     17,500, Box 4 15,000 and Box 5 17,500 and said nothing.
  line_product       (receipt, invoice, purchase_order) a row's quantity
                     times its unit price against its amount.
  fuel_product       (receipt) the page's own "6.736 G @ 2.969/G" against the
                     amount it was charged: a fuel receipt's 4.218 x 3.557 = 15.00 is
                     not 21.10 (job 71).

A W-2 gets none of these: its boxes are not sums of one another.
Reason code: arithmetic_mismatch. UNREADABLE when an operand is not a plain
amount; nothing runs when an operand is missing.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from validators import ANY, FAIL, PASS, CheckResult, register

ARITHMETIC_MISMATCH = "arithmetic_mismatch"
CENT = Decimal("0.01")

_STATED = re.compile(
    r"\b(box|line)\s*(\d{1,2}[a-z]?)\s+(minus|less|plus|\+|-)\s+(?:box|line)?\s*(\d{1,2}[a-z]?)\b",
    re.I)
_CODE = re.compile(r"^\s*(?:box|line)?\s*(\d{1,2}[a-z]?)\b[.:)]?", re.I)


def _money(text):
    from invoice_validators import money
    return money(text)


def _code(label) -> str:
    m = _CODE.match(str(label or ""))
    return m.group(1).lower() if m else ""


def label_arithmetic(ctx):
    out = []
    by_code = {}
    for f in ctx.fields or []:
        c = _code(f.get("row_label"))
        if c:
            by_code.setdefault(c, []).append(f)
    for f in ctx.fields or []:
        m = _STATED.search(str(f.get("row_label") or ""))
        if not m or f["ref"] not in (ctx.values or {}):
            continue
        a_code, op, b_code = m.group(2).lower(), m.group(3).lower(), m.group(4).lower()
        a = [x for x in by_code.get(a_code, []) if x is not f]
        b = [x for x in by_code.get(b_code, []) if x is not f]
        if len(a) != 1 or len(b) != 1:
            continue                                  # ambiguous or absent: do not guess
        a, b = a[0], b[0]
        if a["ref"] not in ctx.values or b["ref"] not in ctx.values:
            continue
        va, vb, vr = (_money(ctx.values[x["ref"]]) for x in (a, b, f))
        ids = [a["ref"], b["ref"], f["ref"]]
        if None in (va, vb, vr):
            continue                                  # a value that is not an amount
        want = va - vb if op in ("minus", "less", "-") else va + vb
        ok = abs(want - vr) <= CENT
        word = "minus" if op in ("minus", "less", "-") else "plus"
        said = (f"{a['row_label']} ({ctx.values[a['ref']]}) {word} "
                f"{b['row_label']} ({ctx.values[b['ref']]}) is {want}, but "
                f"{f['row_label']} reads {ctx.values[f['ref']]} - one of the "
                f"three is wrong")
        out.append(CheckResult(
            "label_arithmetic", PASS if ok else FAIL, ids,
            "" if ok else ARITHMETIC_MISMATCH,
            evidence={r: {"arithmetic_check": "pass" if ok else "fail"} for r in ids},
            flags=[] if ok else [(f["row_label"], ctx.values[f["ref"]], said)],
            notes=[] if ok else [said]))
    return out


def _words(h):
    return set(re.findall(r"[a-z]+", str(h or "").casefold()))


def _col(table, want, avoid=frozenset()):
    hits = [c for c in table.get("columns") or []
            if _words(c.get("header")) & want and not _words(c.get("header")) & avoid]
    return hits[0]["key"] if len(hits) == 1 else None


def line_product(ctx):
    """quantity x unit price = amount, per row, where a table has all three."""
    out = []
    for t in ctx.tables or []:
        if t["name"] in (ctx.incomplete or ()):
            continue
        q = _col(t, {"qty", "quantity", "gallons", "gal", "units", "hours", "hrs"})
        u = _col(t, {"unit", "rate", "each", "per"}, avoid={"units"}) or \
            _col(t, {"price"}, avoid={"total", "amount", "extended"})
        a = _col(t, {"amount", "total", "extended", "ext", "line"},
                 avoid={"unit", "price", "rate", "tax"})
        if not (q and u and a) or len({q, u, a}) < 3:
            continue
        for i, r in enumerate(ctx.rows.get(t["name"]) or []):
            if not isinstance(r, dict):
                continue
            vq, vu, va = (_money(r.get(k)) for k in (q, u, a))
            if None in (vq, vu, va) or vq == 0:
                continue
            if not all(v.is_finite() for v in (vq, vu, va)):
                continue
            try:
                want = (vq * vu).quantize(CENT)
            except InvalidOperation:
                continue        # a product no cent can express is not a line item
            if abs(want - va) <= CENT:
                continue
            ref = f'{t["name"]}_rows[{i}]'
            said = (f"{r.get(q)} x {r.get(u)} is {want}, but the amount reads "
                    f"{r.get(a)} - the quantity, the price or the amount is wrong")
            out.append(CheckResult("line_product", FAIL, [ref], ARITHMETIC_MISMATCH,
                                   evidence={ref: {"product_check": "fail"}},
                                   flags=[(ref, r.get(a), said)], notes=[said]))
    return out


_GALLONS = re.compile(r"(\d{1,3}\.\d{3})\s*(?:G|GAL|GALS|GALLONS)\b", re.I)
_PER_GAL = re.compile(r"\$?\s*(\d\.\d{2,3})\s*/\s*(?:G|GAL)\b", re.I)


def fuel_product(ctx):
    """The page prints gallons and a price per gallon; the amount charged for
    them must be their product. One of each on the page, or nothing runs."""
    text = "\n".join(str(p or "") for p in ctx.pages or [])
    g = {m.group(1) for m in _GALLONS.finditer(text)}
    p = {m.group(1) for m in _PER_GAL.finditer(text)}
    if len(g) != 1 or len(p) != 1:
        return []
    gal, per = Decimal(next(iter(g))), Decimal(next(iter(p)))
    want = (gal * per).quantize(CENT)
    # the extracted amounts that could be the charge: a Total field, and every
    # money cell of a line row; the check fires only when NONE equals the product
    cands = []
    for f in ctx.fields or []:
        v = _money((ctx.values or {}).get(f["ref"]))
        if v is not None and _words(f.get("row_label")) & {"total", "amount", "subtotal", "fuel"}:
            cands.append((f["ref"], f["row_label"], ctx.values[f["ref"]], v))
    if not cands:
        return []
    if any(abs(v - want) <= CENT for *_x, v in cands):
        return [CheckResult("fuel_product", PASS, [c[0] for c in cands])]
    ids = [c[0] for c in cands]
    said = (f"the page prints {gal} gallons at {per} per gallon, which is {want}, "
            f"but {', '.join(f'{c[1]} reads {c[2]}' for c in cands[:2])} - the "
            f"gallons, the price or the amount was misread")
    return [CheckResult("fuel_product", FAIL, ids, ARITHMETIC_MISMATCH,
                        evidence={r: {"product_check": "fail"} for r in ids},
                        flags=[(cands[0][1], cands[0][2], said)], notes=[said])]


register(ANY, label_arithmetic)
register("receipt", line_product)
register("receipt", fuel_product)
register("invoice", line_product)
register("purchase_order", line_product)
