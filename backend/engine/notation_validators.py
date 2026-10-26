"""Number notation — a property of a VALUE, so it runs for every family.

An amount whose notation cannot be read with certainty is not a number the
engine may use. Two cases, both UNREADABLE (the reason is added and the value
needs review; its level does not move — the string itself may be right):

  number_ambiguous       "1,234" / "1.234": a thousands group or three
                         decimals, and nothing on this record (locale, other
                         numbers, currency) says which. The verbatim text is
                         kept; nothing downstream reads it as a number.
  minor_units_mismatch   a fraction the currency does not have: a yen amount
                         with decimals, a dollar amount with three.

The parser and its evidence rules are engine/amounts.py.
"""
from __future__ import annotations

from amounts import (DOCUMENT_HINT, MINOR_UNITS_MISMATCH, NUMBER_AMBIGUOUS,
                     parse_amount)
from validators import ANY, UNREADABLE, CheckResult, register

_SAID = {
    NUMBER_AMBIGUOUS: "the number's notation is ambiguous on this document "
                      "(a thousands group or three decimals) — kept as text",
    MINOR_UNITS_MISMATCH: "the number has more or fewer decimals than its "
                          "currency uses",
}


def _cells(ctx):
    for ref, v in (ctx.values or {}).items():
        yield ref, v
    for name, rows in (ctx.rows or {}).items():
        for i, r in enumerate(rows or []):
            if isinstance(r, dict):
                for k, v in r.items():
                    if not str(k).startswith("_"):
                        yield f"{name}_rows[{i}]", v


def number_notation(ctx):
    hint = DOCUMENT_HINT.get()
    hits = {NUMBER_AMBIGUOUS: [], MINOR_UNITS_MISMATCH: []}
    for ref, v in _cells(ctx):
        if v is None or not str(v).strip():
            continue
        a = parse_amount(v, hint)
        for reason in (NUMBER_AMBIGUOUS, MINOR_UNITS_MISMATCH):
            if reason in a.reasons and ref not in hits[reason]:
                hits[reason].append(ref)
    out = []
    for reason, refs in hits.items():
        if refs:
            out.append(CheckResult(
                "number_notation", UNREADABLE, refs, reason,
                notes=[f"{len(refs)} value(s): {_SAID[reason]}"],
                validation={f"{reason}_count": len(refs)}))
    return out


register(ANY, number_notation)
