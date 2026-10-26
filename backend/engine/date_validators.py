"""Date notation — a property of a VALUE, so it runs for every family.

UNREADABLE (reason added, review required, level unchanged):

  date_ambiguous   day and month could swap (both 12 or below) and neither
                   the locale nor another date on the record settles it
  date_unreadable  a date written with digits of another script

A date the locale or the record's other dates resolved records how
(`date_order`, `date_order_resolved_by` in its provenance). engine/dates.py.
"""
from __future__ import annotations

from dates import (DATE_AMBIGUOUS, DATE_UNREADABLE, document_order,
                   looks_like_a_date, parse_date)
from validators import ANY, UNREADABLE, CheckResult, register


def date_notation(ctx):
    from amounts import FIRM_LOCALE
    cells = list((ctx.values or {}).items())
    for name, rows in (ctx.rows or {}).items():
        for i, r in enumerate(rows or []):
            if isinstance(r, dict):
                cells += [(f"{name}_rows[{i}]", v) for k, v in r.items()
                          if not str(k).startswith("_")]
    dates = [(ref, v) for ref, v in cells if looks_like_a_date(v)]
    if not dates:
        return []
    order, how = document_order([v for _r, v in dates],
                                ctx.locale or FIRM_LOCALE.get())
    hits = {DATE_AMBIGUOUS: [], DATE_UNREADABLE: []}
    evidence = {}
    for ref, v in dates:
        d = parse_date(v, order)
        for reason in hits:
            if reason in d.reasons and ref not in hits[reason]:
                hits[reason].append(ref)
        if d.ok and d.resolved_by:
            evidence[ref] = {"date_order": d.order, "date_order_resolved_by": how}
    out = []
    said = {DATE_AMBIGUOUS: "day and month could be either way round, and "
                            "nothing on the record says which",
            DATE_UNREADABLE: "the date is written in digits of another script"}
    for reason, refs in hits.items():
        if refs:
            out.append(CheckResult("date_notation", UNREADABLE, refs, reason,
                                   notes=[f"{len(refs)} date(s): {said[reason]}"],
                                   validation={f"{reason}_count": len(refs)}))
    if evidence:
        out.append(CheckResult("date_notation", "pass", [], "", evidence=evidence))
    return out


register(ANY, date_notation)
