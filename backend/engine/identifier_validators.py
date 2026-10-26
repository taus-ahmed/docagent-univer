"""Identifiers a template declares (`id_type` on a value cell, or on a table
column's heading cell) are checked by their plug-in (engine/identifiers/).

  invalid        FAIL with the plug-in's reason (`iban_invalid`, …): exactly low
  an unknown id_type is a check that cannot run: said, sent for review
  PAN and GSTIN on one record: the PAN must be GSTIN characters 3-12, else
                 FAIL `pan_gstin_mismatch` on both

Empty values are not checked. A valid identifier is evidence only — it never
raises a level (a well-formed IBAN can still be the wrong account).
"""
from __future__ import annotations

import identifiers
from validators import ANY, FAIL, PASS, UNREADABLE, CheckResult, register

PAN_GSTIN_MISMATCH = "pan_gstin_mismatch"


def _declared(ctx):
    """[(ref, id_type, value)] for every declared field and table cell."""
    out = []
    for f in ctx.fields or []:
        kind = f.get("id_type")
        if kind and f.get("ref") in (ctx.values or {}):
            out.append((f["ref"], kind, ctx.values[f["ref"]]))
    for t in ctx.tables or []:
        for c in t.get("columns") or []:
            kind = c.get("id_type")
            if not kind:
                continue
            for i, r in enumerate((ctx.rows or {}).get(t.get("name")) or []):
                if isinstance(r, dict) and str(r.get(c.get("key"), "")).strip():
                    out.append((f"{t['name']}_rows[{i}]", kind, r[c["key"]]))
    return out


def identifier_check(ctx):
    out = []
    seen = {}
    for ref, kind, value in _declared(ctx):
        try:
            v = identifiers.validate(kind, value)
        except KeyError:
            said = f"no identifier check exists for id_type {kind!r}; {ref} was not checked"
            out.append(CheckResult("identifier_check", UNREADABLE, [], "",
                                   flags=[(ref, value, said)], notes=[said],
                                   needs_review=True))
            continue
        if v.ok is None:
            continue
        ev = {ref: {"id_type": kind, "id_check": "pass" if v.ok else "fail"}}
        if v.ok:
            out.append(CheckResult("identifier_check", PASS, [ref], "", evidence=ev))
            seen.setdefault(kind, []).append((ref, v.normalised))
        else:
            said = f"{ref}: not a valid {kind} ({v.note})"
            out.append(CheckResult("identifier_check", FAIL, [ref], v.reason,
                                   evidence=ev, flags=[(ref, value, said)],
                                   notes=[said]))
    pans, gstins = seen.get("pan", []), seen.get("gstin", [])
    if len(pans) == 1 and len(gstins) == 1 and pans[0][1] != gstins[0][1][2:12]:
        refs = [pans[0][0], gstins[0][0]]
        said = "the PAN is not characters 3-12 of the GSTIN on the same record"
        out.append(CheckResult("identifier_check", FAIL, refs, PAN_GSTIN_MISMATCH,
                               flags=[(refs[0], pans[0][1], said)], notes=[said]))
    return out


register(ANY, identifier_check)
