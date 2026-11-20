"""Value edits addressed by slot (`_edit_field`, `_reconcile_edits`).

Moved verbatim from app/api/routes/extract.py (round 13); extract.py re-exports every name.
"""

import app.services.paths  # noqa: F401  (engine on sys.path)
from fastapi import HTTPException
# --imports-end--


def _field_refs(ed):
    refs = {str(f.get("ref")) for f in (ed.get("slot_map") or {}).get("fields") or []
            if f.get("ref")}
    return refs | {str(r) for r in (ed.get("extracted_fields") or {})}


def _ref_for_label(ed, label):
    """The one slot a label names, or None. Two slots under one label is an
    error the caller must hear about, not a choice made for them.

    The stored projection is asked first: its key may be a qualified label
    (`Principal (Years 8-30)`) that no template cell spells."""
    entry = (ed.get("extracted_data") or {}).get(label)
    if isinstance(entry, dict) and entry.get("ref"):
        return str(entry["ref"])
    refs = [str(f.get("ref")) for f in (ed.get("slot_map") or {}).get("fields") or []
            if f.get("row_label") == label and f.get("ref")]
    if len(refs) > 1:
        raise HTTPException(
            status_code=422,
            detail=(f"'{label}' names {len(refs)} cells ({', '.join(refs)}). "
                    f"Edit by cell reference instead."))
    return refs[0] if refs else None


def _edit_field(ed, stored, ref, value, label_key=None):
    """Write one field-slot edit into every copy of the value, and mark it."""
    from app.core.confidence import EDITED
    before = (stored.get("extracted_fields") or {}).get(ref, "")
    ed.setdefault("extracted_fields", {})[ref] = value
    ed.setdefault("validation", {}).setdefault("confidence_map", {})[ref] = EDITED
    prov = dict((stored.get("field_provenance") or {}).get(ref) or {})
    if not prov.get("edited"):
        prov["original_value"] = before
    prov["edited"] = True
    ed.setdefault("field_provenance", {})[ref] = prov
    kv = ed.setdefault("extracted_data", {})
    key = label_key or next((k for k, e in kv.items()
                             if isinstance(e, dict) and e.get("ref") == ref), None)
    if key is None:
        slot = next((f for f in (ed.get("slot_map") or {}).get("fields") or []
                     if f.get("ref") == ref), {})
        key = slot.get("row_label") or ref
        if key in kv and (kv[key] or {}).get("ref") not in (None, ref):
            key = f"{key} [{ref}]"
    kv[key] = {"value": value, "confidence": EDITED, "ref": ref}


def _reconcile_edits(stored, incoming):
    """A whole-document save, made safe.

    Kept for the grid bundles already open in browsers when this deploys, and
    for API callers. It (1) carries a label-projection edit into its slot, (2)
    marks a slot value changed directly, (3) never lets a payload built from a
    stale copy undo an edit already stored, and (4) does the same for table
    rows, cell by cell.
    """
    import copy
    from app.core.confidence import EDITED
    ed = copy.deepcopy(incoming)
    s_ef = stored.get("extracted_fields") or {}
    s_cm = (stored.get("validation") or {}).get("confidence_map") or {}
    in_cm = (incoming.get("validation") or {}).get("confidence_map") or {}

    # (3) first, so the diffs below compare against the restored values
    for ref, lvl in s_cm.items():
        if lvl == EDITED and in_cm.get(ref) != EDITED:
            kv_in = incoming.get("extracted_data") or {}
            re_edited = any(isinstance(e, dict) and e.get("confidence") == EDITED
                            and (e.get("ref") == ref or (not e.get("ref") and
                                 _ref_for_label(stored, k) == ref))
                            for k, e in kv_in.items())
            if re_edited:
                continue
            ed.setdefault("extracted_fields", {})[ref] = s_ef.get(ref, "")
            ed.setdefault("validation", {}).setdefault("confidence_map", {})[ref] = EDITED
            ed.setdefault("field_provenance", {})[ref] = (
                (stored.get("field_provenance") or {}).get(ref) or {"edited": True})
            kv = ed.setdefault("extracted_data", {})
            for k in [k for k, e in kv.items() if isinstance(e, dict) and e.get("ref") == ref]:
                del kv[k]
            s_key = next((k for k, e in (stored.get("extracted_data") or {}).items()
                          if isinstance(e, dict) and e.get("ref") == ref), None)
            if s_key is not None:
                kv[s_key] = stored["extracted_data"][s_key]

    # (1) an edit made on the label projection
    for key, e in list((ed.get("extracted_data") or {}).items()):
        if not (isinstance(e, dict) and e.get("confidence") == EDITED):
            continue
        ref = e.get("ref") or _ref_for_label(stored, key)
        if ref is None:
            continue                      # a legacy document with no slots
        if s_cm.get(ref) == EDITED and str(s_ef.get(ref, "")) == str(e.get("value", "")):
            continue                      # already stored exactly so
        _edit_field(ed, stored, ref, e.get("value", ""), label_key=key)

    # (2) a slot value changed directly
    for ref, v in list((ed.get("extracted_fields") or {}).items()):
        cm = (ed.get("validation") or {}).get("confidence_map") or {}
        if str(v) != str(s_ef.get(ref, "")) and cm.get(ref) != EDITED:
            _edit_field(ed, stored, ref, v)

    # (4) table rows: aligned by position, which only holds when the row count
    # is unchanged; a save that adds or removes rows is kept as sent
    for key, rows in ed.items():
        s_rows = stored.get(key)
        if not (key.endswith("_rows") and isinstance(rows, list)
                and isinstance(s_rows, list) and len(rows) == len(s_rows)):
            continue
        for r_in, r_st in zip(rows, s_rows):
            if not (isinstance(r_in, dict) and isinstance(r_st, dict)):
                continue
            edited = set(r_st.get("_edited") or [])
            original = dict(r_st.get("_original") or {})
            for col in edited - set(r_in.get("_edited") or []):
                if str(r_in.get(col, "")) == str(original.get(col, "")):
                    r_in[col] = r_st.get(col, "")       # stale copy: keep the edit
            for col, v in list(r_in.items()):
                if str(col).startswith("_"):
                    continue
                if str(v) != str(r_st.get(col, "")):
                    edited.add(col)
                    original.setdefault(col, r_st.get(col, ""))
            if edited:
                r_in["_edited"] = sorted(edited)
                r_in["_original"] = original
    return ed


#: Keys of a stored result the SERVER owns. A whole-document save is built
#: from whatever copy the browser had, and that copy can predate a review mark,
#: a disposition or another edit; taking it whole silently undid them (Run A,
#: A6: "I edit, save, accept, and the change does not stick"). These are always
#: carried over from the stored row, never from the payload.
SERVER_OWNED = ("review", "attention", "diagnostics", "document_state",
                "failure_kind")


def _edit_cell(ed, table, row, column, value):
    """Write one table-cell edit into `ed` in place and mark it. Returns the
    value it replaced. 404 for a table, row or column the result lacks."""
    from app.core import review as R
    key = dict(R.table_keys(ed)).get(str(table))
    rows = ed.get(key) if key else None
    if not isinstance(rows, list) or not 0 <= int(row) < len(rows) \
            or not isinstance(rows[int(row)], dict):
        raise HTTPException(status_code=404, detail="No such table row")
    r = rows[int(row)]
    col = str(column)
    known = any(str(c.get("key") or c.get("header")) == col
                for t in (ed.get("slot_map") or {}).get("tables") or []
                if str(t.get("name")) == str(table)
                for c in t.get("columns") or [])
    if col.startswith("_") or (col not in r and not known):
        raise HTTPException(status_code=404, detail=f"No column {col!r} in this table")
    before = r.get(col, "")
    edited = set(r.get("_edited") or [])
    original = dict(r.get("_original") or {})
    original.setdefault(col, before)
    edited.add(col)
    r[col] = value
    r["_edited"] = sorted(edited)
    r["_original"] = original
    return before


def _edit_events(stored, ed, who, at):
    """One append-only event per value that changed between the stored row
    and the one about to be saved: who, when, where, old, new. The machine's
    original value is never lost: it is the first event's `old`."""
    events = []
    s_f = (stored or {}).get("extracted_fields") or {}
    e_f = (ed or {}).get("extracted_fields") or {}
    for ref in sorted(set(s_f) | set(e_f)):
        if str(s_f.get(ref, "")) != str(e_f.get(ref, "")):
            events.append({"by": who, "at": at, "kind": "field", "ref": ref,
                           "old": s_f.get(ref, ""), "new": e_f.get(ref, ""),
                           "reason": "edited in review"})
    for key, rows in (ed or {}).items():
        s_rows = (stored or {}).get(key)
        if not (isinstance(key, str) and key.endswith("_rows")
                and isinstance(rows, list)):
            continue
        if not isinstance(s_rows, list) or len(s_rows) != len(rows):
            if s_rows != rows:
                events.append({"by": who, "at": at, "kind": "rows",
                               "table": key[:-5],
                               "old": len(s_rows or []), "new": len(rows),
                               "reason": "row count changed"})
            continue
        for i, (a, b) in enumerate(zip(s_rows, rows)):
            if not (isinstance(a, dict) and isinstance(b, dict)):
                continue
            for col in sorted(set(a) | set(b)):
                if str(col).startswith("_"):
                    continue
                if str(a.get(col, "")) != str(b.get(col, "")):
                    events.append({"by": who, "at": at, "kind": "cell",
                                   "table": key[:-5], "row": i, "column": col,
                                   "old": a.get(col, ""), "new": b.get(col, ""),
                                   "reason": "edited in review"})
    return events


def _keep_server_state(stored, ed):
    """Carry what the server owns from `stored` into `ed`, in place: the
    keys above, and every per-value review mark the payload's copy lacks."""
    for k in SERVER_OWNED:
        if k in (stored or {}):
            ed[k] = stored[k]
    s_prov = (stored or {}).get("field_provenance") or {}
    e_prov = ed.setdefault("field_provenance", {})
    for ref, p in s_prov.items():
        if isinstance(p, dict) and p.get("reviewed") and ref in e_prov \
                and isinstance(e_prov[ref], dict) and not e_prov[ref].get("reviewed"):
            e_prov[ref]["reviewed"] = p["reviewed"]
    # Run G: a flag a reviewer set aside (confirmed empty) stays set aside
    cleared = {str(ref) for ref, p in s_prov.items() if isinstance(p, dict)
               and (p.get("reviewed") or {}).get("disposition") == "confirmed_empty"}
    if cleared:
        val = ed.setdefault("validation", {})
        val["flagged_fields"] = [f for f in val.get("flagged_fields") or []
                                 if not (isinstance(f, dict) and str(f.get("ref")) in cleared)]
    for key, s_rows in (stored or {}).items():
        rows = ed.get(key)
        if isinstance(key, str) and key.endswith("_rows") and isinstance(s_rows, list) \
                and isinstance(rows, list) and len(rows) == len(s_rows):
            for a, b in zip(s_rows, rows):
                if not (isinstance(a, dict) and isinstance(b, dict)):
                    continue
                if a.get("_reviewed") and not b.get("_reviewed"):
                    b["_reviewed"] = a["_reviewed"]
                # Run G: per-cell marks and a row's stable id are server state
                for col, m in (a.get("_reviewed_cells") or {}).items():
                    b.setdefault("_reviewed_cells", {}).setdefault(col, m)
                if a.get("_row_id") and not b.get("_row_id"):
                    b["_row_id"] = a["_row_id"]


def _save_edit(doc, ed, current_user, db, stored=None):
    """Persist an edit. `stored` is the row as read before the edit: the
    server-owned state comes from it, and the edit log is extended from it.

    An edit no longer marks the document reviewed while a completeness
    reason is open: typing one value does not settle a missing table."""
    from datetime import datetime
    from app.core import review as R
    if stored is None:
        stored = doc.get_extracted_data() or {}
        stored = stored if isinstance(stored, dict) else {}
    _keep_server_state(stored, ed)
    at = datetime.utcnow().isoformat() + "Z"
    ed["edit_log"] = list(stored.get("edit_log") or []) + _edit_events(
        stored, ed, current_user.username, at)
    doc.set_extracted_data(ed)
    # Run G, G4: the one review state — an edit settles the document only
    # when nothing else on it is still owed a look.
    open_ = R.unsettled(ed) > 0
    doc.reviewed = not open_
    if not open_:
        doc.reviewed_by = current_user.username
    doc.needs_review = open_
    db.commit()
