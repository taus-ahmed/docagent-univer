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


def _save_edit(doc, ed, current_user, db):
    doc.set_extracted_data(ed)
    doc.reviewed = True
    doc.reviewed_by = current_user.username
    doc.needs_review = False
    db.commit()
