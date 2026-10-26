"""Possible duplicates in one result set — the same cheque scanned twice.

A pure function over the records (`extracted_data` dicts) of one batch.
Two records look like the same cheque when their routing number, account
number and serial (cheque number) all agree, AND their amount and their date
agree wherever both records carry one. Two different cheques from the same
account differ in serial, so sharing a bank is never enough.

A match is FLAGGED on both records, never resolved: `possible_duplicate` on
every identity value (routing, account, serial, amount, date) with
`review_required`, `validation.possible_duplicate = {"of": [the others]}`,
one `flagged_fields` entry, and `needs_review`. No level moves, nothing is
merged and nothing is dropped — which copy is the real one is a person's call.

Identity is read from the template's labels; a record without all three of
routing, account and serial is not compared.

Reason code: possible_duplicate (OCR-READER-SEAM-DESIGN §12).
"""
from __future__ import annotations

import re
from datetime import datetime

POSSIBLE_DUPLICATE = "possible_duplicate"
IDENTITY = ("routing", "account", "serial", "amount", "date")


def _words(label) -> set:
    return set(re.sub(r"[^a-z# ]+", " ", str(label or "").lower()).split())


def role(label) -> str:
    """Which identity part a label names, or ''."""
    w = _words(label)
    if not w:
        return ""
    if w & {"routing", "transit", "aba"}:
        return "routing"
    if "account" in w and not w & {"holder", "name", "type", "payee", "title"}:
        return "account"
    if "serial" in w or (w & {"cheque", "check"} and w & {"number", "no", "num", "#"}):
        return "serial"
    if "amount" in w and "words" not in w:
        return "amount"
    if "date" in w:
        return "date"
    return ""


def _digits(v) -> str:
    """The value's digits (any script), or ''."""
    return "".join(str(int(c)) for c in str(v or "") if c.isdecimal())


def _amount(v, hint=None):
    """The shared parser (engine/amounts.py) with the record's own evidence;
    an ambiguous amount is None — unknown, so never a duplicate by amount."""
    from amounts import money
    return money(v, hint)


_DATE_FORMATS = ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%d %B %Y", "%B %d, %Y",
                 "%b %d, %Y", "%d %b %Y", "%m-%d-%Y")


def _date(v):
    t = re.sub(r"\s+", " ", str(v or "")).strip()
    for f in _DATE_FORMATS:
        try:
            return datetime.strptime(t, f).date()
        except ValueError:
            continue
    return _digits(t) or None


def identity(ed) -> dict | None:
    """{routing, account, serial, amount, date, refs: {part: ref}}, or None
    when the record cannot say routing, account AND serial."""
    if not isinstance(ed, dict):
        return None
    fields = (ed.get("slot_map") or {}).get("fields") or []
    values = ed.get("extracted_fields") or {}
    if not isinstance(values, dict):
        return None
    by_role: dict = {}
    for f in fields:
        if not isinstance(f, dict) or not f.get("ref"):
            continue
        r = role(f.get("row_label"))
        v = values.get(f["ref"])
        if r and str(v or "").strip():
            by_role.setdefault(r, []).append((f["ref"], v))
    from amounts import document_hint
    hint = document_hint(list(values.values()), ed.get("locale"))
    out, refs = {}, {}
    for r in IDENTITY:
        hits = by_role.get(r) or []
        if len(hits) != 1:
            out[r] = None                         # absent, or ambiguous: unknown
            continue
        ref, v = hits[0]
        if r in ("routing", "account"):
            out[r] = _digits(v) or None
        elif r == "serial":
            d = _digits(v)
            out[r] = d.lstrip("0") or ("0" if d else None)
        elif r == "amount":
            out[r] = _amount(v, hint)
        else:
            out[r] = _date(v)
        if out[r] is not None:
            refs[r] = ref
    if not (out["routing"] and out["account"] and out["serial"]):
        return None
    out["refs"] = refs
    return out


def _same(a, b) -> bool:
    if any(a[k] != b[k] for k in ("routing", "account", "serial")):
        return False
    return all(a[k] is None or b[k] is None or a[k] == b[k] for k in ("amount", "date"))


def flag_possible_duplicates(records, names=None) -> list[int]:
    """Flag records that look like the same cheque. Mutates them in place and
    returns the indexes flagged (in order). `names` label each record in the
    others' flags (default "record k")."""
    records = list(records or [])
    names = list(names or [])
    ids = []
    for ed in records:
        try:
            ids.append(identity(ed))
        except Exception:
            ids.append(None)
    others: dict = {}
    for i in range(len(records)):
        for j in range(i + 1, len(records)):
            if ids[i] and ids[j] and _same(ids[i], ids[j]):
                others.setdefault(i, []).append(j)
                others.setdefault(j, []).append(i)

    def label(k):
        return names[k] if k < len(names) and names[k] else f"record {k + 1}"

    for k in sorted(others):
        ed = records[k]
        prov = ed.setdefault("field_provenance", {})
        for ref in ids[k]["refs"].values():
            p = prov.setdefault(ref, {})
            rs = p.setdefault("review_reasons", [])
            if POSSIBLE_DUPLICATE not in rs:
                rs.append(POSSIBLE_DUPLICATE)
            p["review_required"] = True
        v = ed.setdefault("validation", {})
        of = [label(j) for j in sorted(others[k])]
        v["possible_duplicate"] = {"of": of}
        flags = v.setdefault("flagged_fields", [])
        flags[:] = [f for f in flags if not (isinstance(f, dict)
                                             and str(f.get("reason", "")).startswith(POSSIBLE_DUPLICATE))]
        serial_ref = ids[k]["refs"].get("serial")
        serial_label = next((f.get("row_label") for f in
                             (ed.get("slot_map") or {}).get("fields") or []
                             if isinstance(f, dict) and f.get("ref") == serial_ref),
                            serial_ref)
        flags.append({"ref": serial_label,
                      "value": (ed.get("extracted_fields") or {}).get(serial_ref, ""),
                      "reason": f"{POSSIBLE_DUPLICATE}: same routing, account and serial"
                                f" as {', '.join(of)} — check it was not scanned twice"})
        v["flagged_count"] = len(flags)
        ed["needs_review"] = True
    return sorted(others)
