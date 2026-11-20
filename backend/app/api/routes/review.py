"""
Review routes — what the review screen reads and writes.

* `GET  /api/review/reasons` — the one reason map and the status vocabulary
  (app/core/review.py), so the screen never keeps its own copy.
* `GET  /api/jobs/{job}/review` — every document's values with their review
  status, and the counts for the header and the export dialog.
* `GET  /api/jobs/{job}/docs/{doc}/pages/{n}` — the page as the READER saw it:
  its origin, the image frame, and a box for each value on it where the
  value's own quote can be found there exactly once. A value with no box says
  why; nothing is guessed.
* `GET  /api/jobs/{job}/docs/{doc}/pages/{n}/image` — that page's image: the
  straightened image an OCR'd page was read from, or the rendered page.
* `POST /api/jobs/{job}/docs/{doc}/review` — mark values (or the whole
  document) reviewed. Stored inside `extraction_json`; no schema change.

Access: the same `_get_job_or_404` as every job route (another tenant's job
answers 404, like a missing id); reviewing needs `job.review`.
"""
from __future__ import annotations

import io
import re
import threading
from collections import OrderedDict
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import app.services.paths  # noqa: F401  (engine on sys.path)
from app.core import review as R
from app.core.auth import get_current_user
from app.models import DocumentResult, User, get_db

router = APIRouter(prefix="/api", tags=["review"])

#: Display resolution for page images. Boxes are in points (1/72 in) from the
#: frame's top-left; the client scales them by the image's own size.
PAGE_DPI = 110
#: A page image is never sent larger than this on its long side.
MAX_SIDE_PX = 2000
#: Source files whose reading is kept in memory (a reading holds every page's
#: lines and, for OCR'd pages, the straightened image).
_CACHE_FILES = 6
_cache: "OrderedDict[str, dict]" = OrderedDict()
_cache_lock = threading.Lock()


def _job_for(job_id, user, db, action="job.view"):
    from app.api.routes.extract import _get_job_or_404
    return _get_job_or_404(job_id, user, db, action)


def _doc_for(job_id, doc_id, user, db, action="job.view"):
    job = _job_for(job_id, user, db, action)
    doc = db.query(DocumentResult).filter(
        DocumentResult.id == doc_id, DocumentResult.job_id == job_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return job, doc


# ── reasons ──────────────────────────────────────────────────────────────────

@router.get("/review/reasons")
def review_reasons(current_user: User = Depends(get_current_user)):
    return {"reasons": {c: {"label": l, "tooltip": t} for c, (l, t) in R.REASONS.items()},
            "statuses": {s: {"label": l, "tooltip": t} for s, (l, t) in R.STATUSES.items()}}


# ── job review summary ───────────────────────────────────────────────────────

def _pages_of(ed: dict) -> list[int]:
    pages = set()
    for p in (ed.get("field_provenance") or {}).values():
        if isinstance(p, dict) and isinstance(p.get("page"), int):
            pages.add(p["page"])
    for _, key in R.table_keys(ed):
        for row in ed.get(key) or []:
            if isinstance(row, dict) and isinstance(row.get("_page"), int):
                pages.add(row["_page"])
    sp = ed.get("source_pages")
    if isinstance(sp, list) and len(sp) == 2 and all(isinstance(x, int) for x in sp):
        pages.update(range(sp[0], sp[1] + 1))
    # Overnight E2: EVERY page of the document, not only the pages holding a
    # value — mammoth_2pg's page 2 had lost its rows, so the dialog offered
    # page 1 alone and the page the reviewer had to check was unreachable.
    diag = ed.get("diagnostics") if isinstance(ed.get("diagnostics"), dict) else {}
    for k in (diag.get("pages") or {}) if isinstance(diag.get("pages"), dict) else ():
        if str(k).isdigit() and int(k) >= 1:
            pages.add(int(k))
    n = (diag.get("inventory") or {}).get("pages") if isinstance(diag.get("inventory"), dict) else None
    if isinstance(n, int) and n >= 1 and not (isinstance(sp, list) and len(sp) == 2):
        pages.update(range(1, n + 1))
    return sorted(pages)


@router.get("/jobs/{job_id}/charts")
def job_charts(job_id: int, db: Session = Depends(get_db),
               current_user: User = Depends(get_current_user)):
    """Chart data for a job (Part A5): exact aggregations of the CURRENT
    values (edits included), one currency at a time, with how many values
    still need review — the banner every chart shows."""
    _job_for(job_id, current_user, db)
    from charts import aggregate
    eds, values = [], []
    for d in db.query(DocumentResult).filter(DocumentResult.job_id == job_id).all():
        ed = d.get_extracted_data() or {}
        if isinstance(ed, dict):
            eds.append(ed)
            values += R.document_values(ed)
    out = aggregate(eds)
    out["needs_review"] = R.summarise(values)["needs_review"]
    return out


@router.get("/jobs/{job_id}/review")
def job_review(job_id: int, db: Session = Depends(get_db),
               current_user: User = Depends(get_current_user)):
    from app.api.routes.extract import _document_index
    _job_for(job_id, current_user, db)
    docs = db.query(DocumentResult).filter(DocumentResult.job_id == job_id).all()
    docs.sort(key=lambda d: ((d.original_filename or d.filename or "").casefold(),
                             _document_index(d), d.id))
    out, all_values = [], []
    for d in docs:
        ed = d.get_extracted_data() or {}
        ed = ed if isinstance(ed, dict) else {}
        values = R.document_values(ed)
        all_values += values
        out.append({
            "doc_id": d.id, "filename": d.filename,
            "original_filename": d.original_filename or d.filename,
            "document_index": ed.get("document_index"),
            "document_count": ed.get("document_count"),
            "document_type": d.document_type,
            "pages": _pages_of(ed),
            "needs_review": bool(d.needs_review),
            "document_reviewed": R.document_reviewed(ed),
            "failed": not ed or ed.get("document_state") == "FAILED",
            "error": d.validation_errors or "",
            "values": values,
            "summary": R.summarise(values),
            # Run A, A4/A5: the completeness reasons and the state they set
            "attention": R.attention_items(ed),
            "document_state": R.document_state(ed, failed=not ed),
            "pages_ledger": (ed.get("diagnostics") or {}).get("pages") or {},
            # Part A3: informational, counted, never a level
            "anomalies": [a for a in (ed.get("anomalies") or []) if isinstance(a, dict)],
        })
    s = R.summarise(all_values)
    s["documents"] = len(out)
    s["anomalies"] = sum(len(o["anomalies"]) for o in out)
    s["documents_needing_review"] = sum(1 for o in out if o["summary"]["needs_review"]
                                        or (o["failed"] and not o["document_reviewed"])
                                        or o["document_state"] == "NEEDS_ATTENTION")
    s["documents_needing_attention"] = sum(1 for o in out
                                           if o["document_state"] == "NEEDS_ATTENTION")
    s["attention_open"] = sum(len([a for a in o["attention"] if not a.get("disposition")])
                              for o in out)
    return {"job_id": job_id, "summary": s, "documents": out}


# ── marking reviewed ─────────────────────────────────────────────────────────

class ReviewMark(BaseModel):
    #: "document", or a list of values: {"ref": "B6"} or
    #: {"table": "table", "row": 0}
    scope: str = Field("values", pattern="^(values|document)$")
    values: list[dict] = []
    reviewed: bool = True
    #: Run A, A5 — one per NEEDS_ATTENTION reason being settled:
    #: {"id": "att-1", "choice": "confirmed_absent" | "entered_manually",
    #:  "note": "..."}. Applied before the marks.
    dispositions: list[dict] = []


def _disposition_of(v: dict) -> Optional[str]:
    d = v.get("disposition")
    if d is None:
        return None
    if d not in R.VALUE_DISPOSITIONS:
        raise HTTPException(status_code=422, detail=(
            f"Unknown disposition {d!r}; use "
            f"{' / '.join(R.VALUE_DISPOSITIONS)}"))
    if d == "corrected" and "value" not in v:
        raise HTTPException(status_code=422,
                            detail="A correction needs the corrected value")
    return d


def _clear_field_flags(ed: dict, ref: str) -> list:
    """Remove `ref`'s entries (by ref or by its label) from
    validation.flagged_fields; return them, so the mark can keep them."""
    label = next((f.get("row_label") for f in (ed.get("slot_map") or {}).get("fields") or []
                  if str(f.get("ref")) == ref), None)
    val = ed.setdefault("validation", {})
    keep, gone = [], []
    for f in val.get("flagged_fields") or []:
        hit = isinstance(f, dict) and str(f.get("ref")) in {ref, str(label)}
        (gone if hit else keep).append(f)
    val["flagged_fields"] = keep
    return gone


def _find_row(ed: dict, v: dict):
    """(table name, row index, row) for a value entry naming a table row by
    `row` and/or `row_id`. A row id wins; a row index that disagrees with it
    is a conflict (409), never a guess."""
    tables = dict(R.table_keys(ed))
    name = str(v["table"])
    key = tables.get(name)
    rows = ed.get(key) if key else None
    if not isinstance(rows, list):
        raise HTTPException(status_code=404, detail="No such table row")
    idx = v.get("row")
    if v.get("row_id") is not None:
        found = [i for i, r in enumerate(rows)
                 if isinstance(r, dict) and str(r.get("_row_id")) == str(v["row_id"])]
        if not found:
            raise HTTPException(status_code=404, detail="No row with that row id")
        if isinstance(idx, int) and idx != found[0]:
            raise HTTPException(status_code=409, detail=(
                "The row id and the row number name different rows; reload "
                "and try again"))
        idx = found[0]
    if not isinstance(idx, int) or not 0 <= idx < len(rows) \
            or not isinstance(rows[idx], dict):
        raise HTTPException(status_code=404, detail="No such table row")
    return name, idx, rows[idx]


def _apply_marks(ed: dict, payload: ReviewMark, stamp: dict) -> dict:
    """The marks in `payload` applied to `ed` in place (and returned).
    Marking a value already marked re-stamps it; nothing accumulates.

    Run G, G4: a value entry may carry a `disposition`:
      accepted_as_is — the value is right as it is
      corrected      — `value` replaces it AND it is accepted, one operation
      confirmed_empty — the slot is cleared, its flags set aside
    stored on the value's own mark with who and when and logged in
    `edit_log`. A table entry with a disposition must name its `column`: a
    cell is accepted, never its whole row."""
    from app.services.edits import _edit_cell, _edit_field
    if payload.scope == "document":
        ed["review"] = ({"document_reviewed": True, **stamp} if payload.reviewed
                        else {"document_reviewed": False})
        return ed
    prov = ed.setdefault("field_provenance", {})
    log = ed.setdefault("edit_log", [])
    for v in payload.values:
        disp = _disposition_of(v)
        if disp and not payload.reviewed:
            raise HTTPException(status_code=422, detail=(
                "A disposition cannot be withdrawn; correct the value instead"))
        if v.get("ref") is not None:
            ref = str(v["ref"])
            if ref not in prov and ref not in (ed.get("extracted_fields") or {}) \
                    and ref not in {str(f.get("ref")) for f in
                                    (ed.get("slot_map") or {}).get("fields") or []}:
                raise HTTPException(status_code=404, detail=f"No field at {ref!r}")
            if not payload.reviewed:
                prov.setdefault(ref, {}).pop("reviewed", None)
                continue
            if not disp:
                prov.setdefault(ref, {})["reviewed"] = stamp
                continue
            old = (ed.get("extracted_fields") or {}).get(ref, "")
            event = {**stamp, "kind": "field", "ref": ref, "disposition": disp}
            if disp == "corrected":
                _edit_field(ed, ed, ref, str(v.get("value") or ""))
                event.update(old=old, new=ed["extracted_fields"][ref],
                             reason="corrected in review")
            elif disp == "confirmed_empty":
                if str(old or "") != "":
                    _edit_field(ed, ed, ref, "")
                else:
                    ed.setdefault("extracted_fields", {})[ref] = ""
                cleared = _clear_field_flags(ed, ref)
                event.update(old=old, new="", reason="confirmed empty in review",
                             cleared_flags=cleared)
            else:
                event.update(value=old, reason="accepted as is in review")
            mark = {"disposition": disp, **stamp}
            prov.setdefault(ref, {})["reviewed"] = mark
            log.append(event)
        elif v.get("table") is not None and (isinstance(v.get("row"), int)
                                             or v.get("row_id") is not None):
            name, idx, row = _find_row(ed, v)
            col = v.get("column")
            if col is None:
                if disp:
                    raise HTTPException(status_code=422, detail=(
                        "A disposition on a table names its column: a cell "
                        "is accepted, not its row"))
                if payload.reviewed:
                    row["_reviewed"] = stamp
                else:
                    row.pop("_reviewed", None)
                continue
            col = str(col)
            if not payload.reviewed:
                (row.get("_reviewed_cells") or {}).pop(col, None)
                continue
            old = row.get(col, "")
            event = {**stamp, "kind": "cell", "table": name, "row": idx,
                     "row_id": row.get("_row_id"), "column": col,
                     "disposition": disp or "accepted_as_is"}
            if disp == "corrected":
                _edit_cell(ed, name, idx, col, str(v.get("value") or ""))
                event.update(old=old, new=row.get(col, ""), reason="corrected in review")
            elif disp == "confirmed_empty":
                _edit_cell(ed, name, idx, col, "")
                event.update(old=old, new="", reason="confirmed empty in review")
            else:
                if col.startswith("_") or col not in row:
                    raise HTTPException(status_code=404,
                                        detail=f"No column {col!r} in this row")
                event.update(value=old, reason="accepted as is in review")
            cells = row.setdefault("_reviewed_cells", {})
            cells[col] = {"disposition": event["disposition"], **stamp}
            log.append(event)
        else:
            raise HTTPException(status_code=422,
                                detail="Each value needs a ref, or a table and a row")
    return ed


def _swap(db, doc_id: int, old: str, values: dict) -> bool:
    """UPDATE the row only if its stored JSON is still `old`; True if it was.

    A compare-and-swap on the text itself: no version column, no migration,
    and it works the same on SQLite and PostgreSQL and across processes."""
    from sqlalchemy import update
    from app.models.models import DocumentResult
    done = db.execute(update(DocumentResult)
                      .where(DocumentResult.id == doc_id,
                             DocumentResult.extraction_json.is_(None)
                             if old is None else
                             DocumentResult.extraction_json == old)
                      .values(**values)
                      .execution_options(synchronize_session=False))
    if done.rowcount == 1:
        db.commit()
        return True
    db.rollback()
    return False


#: How often a mark is re-read and re-applied after losing a race.
MARK_ATTEMPTS = 8


@router.post("/jobs/{job_id}/docs/{doc_id}/review")
def mark_reviewed(job_id: int, doc_id: int, payload: ReviewMark,
                  db: Session = Depends(get_db),
                  current_user: User = Depends(get_current_user)):
    """Mark values (or the document) reviewed.

    CONCURRENCY-SAFE without a migration: the stored JSON is re-read, the
    marks applied to that, and written only if nobody wrote in between
    (`_swap`); otherwise read again and re-applied. Two reviewers marking
    different values at once both persist; a conflict that never clears is a
    409, never a silently dropped mark."""
    import json
    from sqlalchemy import select
    from app.models.models import DocumentResult
    _, doc = _doc_for(job_id, doc_id, current_user, db, "job.review")
    stamp = {"by": current_user.username, "at": datetime.utcnow().isoformat() + "Z"}
    for _attempt in range(MARK_ATTEMPTS):
        row = db.execute(select(DocumentResult.extraction_json,
                                DocumentResult.reviewed_by)
                         .where(DocumentResult.id == doc.id)).one()
        db.rollback()          # end the read: the write starts fresh (SQLite WAL)
        old, reviewed_by = row
        try:
            stored = json.loads(old) if old else {}
        except ValueError:
            stored = {}
        if not isinstance(stored, dict):
            raise HTTPException(status_code=422,
                                detail="This document has no stored result")
        missing = R.apply_dispositions(stored, payload.dispositions, stamp)
        if missing:
            raise HTTPException(status_code=404,
                                detail=f"No open reason {', '.join(missing)} on this "
                                       f"document, or an unknown choice (use "
                                       f"{' / '.join(R.DISPOSITIONS)})")
        open_reasons = R.attention_open(stored)
        if payload.scope == "document" and payload.reviewed and open_reasons:
            # REVIEW CAN NEVER ERASE A MISSING SECTION. A single click used
            # to set needs_review false on a document whose table came back
            # empty, and the export then said nothing needed review.
            raise HTTPException(status_code=409, detail={
                "message": (f"{len(open_reasons)} completeness reason(s) are still "
                            f"open on this document. Say for each one whether it "
                            f"is confirmed absent or entered by hand before "
                            f"marking the document reviewed."),
                "open": [{"id": a.get("id"), "text": a.get("text")}
                         for a in open_reasons]})
        ed = _apply_marks(stored, payload, stamp)
        values = R.document_values(ed)
        open_ = R.unsettled(ed)
        # The document is reviewed when nothing in it is still owed a look.
        cols = {"extraction_json": json.dumps(ed, default=str),
                "reviewed": open_ == 0,
                "reviewed_by": current_user.username if open_ == 0 else reviewed_by}
        if open_ == 0:
            cols.update(reviewed_at=datetime.utcnow(), needs_review=False)
        if _swap(db, doc.id, old, cols):
            return {"doc_id": doc_id, "summary": R.summarise(values),
                    "values": values, "document_reviewed": R.document_reviewed(ed),
                    "attention": R.attention_items(ed),
                    "document_state": R.document_state(ed)}
    raise HTTPException(status_code=409,
                        detail="This document was changed by someone else at the "
                               "same moment; nothing was marked. Try again.")


# ── adding a missing table row (Run G, G4) ───────────────────────────────────

class AddRow(BaseModel):
    #: {column key: value} — only the table's own columns
    values: dict[str, str]
    #: the open completeness reason this row answers ("a printed row is
    #: missing"); it is settled as entered_manually by the same write
    attention_id: Optional[str] = None
    #: where the row goes (0 = first); default the end of the table
    position: Optional[int] = None


_TOTAL_LABEL = re.compile(r"\b(?:sub\s*-?\s*total|total|amount\s+due|balance\s+due)\b", re.I)


def _amount(s):
    """A plain amount as Decimal, or None (`$1,234.50`, `(20.00)`, `-5`)."""
    from decimal import Decimal, InvalidOperation
    t = str(s or "").strip()
    if not t:
        return None
    neg = t.startswith("(") and t.endswith(")")
    t = re.sub(r"[\s$£€₹¥,()]", "", t).replace("−", "-")
    if not re.fullmatch(r"-?\d+(?:\.\d+)?", t):
        return None
    try:
        d = Decimal(t)
    except InvalidOperation:
        return None
    return -d if neg else d


def _amount_column(rows, columns):
    """The table's one amount column: every filled cell a plain amount. When
    several qualify, the one headed amount/total/value; None when that still
    leaves more than one (no guess)."""
    numeric = [c for c in columns
               if any(str(r.get(c, "")).strip() for r in rows)
               and all(_amount(r.get(c)) is not None
                       for r in rows if str(r.get(c, "")).strip())]
    if len(numeric) == 1:
        return numeric[0]
    named = [c for c in numeric if re.search(r"amount|total|value", c, re.I)]
    return named[0] if len(named) == 1 else None


def _recheck_totals(ed: dict, table: str, rows: list, columns: list) -> list:
    """After a person adds a row, every TOTAL-labelled field slot is checked
    again against the table's amount column. A total that no longer equals
    the rows' sum — or cannot be checked — is RE-FLAGGED, never rewritten:
    a total is the document's printed figure, and only a person may change
    it. Returns the refs flagged."""
    fields = [f for f in (ed.get("slot_map") or {}).get("fields") or []
              if f.get("ref") and _TOTAL_LABEL.search(str(f.get("row_label") or ""))]
    if not fields:
        return []
    col = _amount_column(rows, columns)
    total = (sum((_amount(r.get(col)) or 0) for r in rows) if col else None)
    prov = ed.setdefault("field_provenance", {})
    val = ed.setdefault("validation", {})
    flagged = []
    for f in fields:
        ref = str(f["ref"])
        v = (ed.get("extracted_fields") or {}).get(ref, "")
        got = _amount(v)
        if col is not None and got is not None and got == total:
            continue
        why = (f"total no longer matches the {table} rows after a row was added: "
               f"the rows sum to {total:.2f}" if col is not None and got is not None
               else f"total could not be rechecked after a row was added to {table}")
        val.setdefault("flagged_fields", []).append({"ref": ref, "value": v, "reason": why})
        p = prov.setdefault(ref, {})
        p["review_required"] = True
        p["review_reasons"] = list(dict.fromkeys(list(p.get("review_reasons") or [])
                                                 + ["totals_mismatch"]))
        p.pop("reviewed", None)        # a check that changed owes a fresh look
        flagged.append(ref)
    return flagged


@router.post("/jobs/{job_id}/docs/{doc_id}/rows/{table}", status_code=201)
def add_row(job_id: int, doc_id: int, table: str, payload: AddRow,
            db: Session = Depends(get_db),
            current_user: User = Depends(get_current_user)):
    """Add a row the extraction missed. The row gets a stable `_row_id`
    (returned), is marked typed-by-a-person, is logged, and goes into the
    exported band like any other row. Total slots are re-flagged when the
    rows no longer sum to them; a named completeness reason is settled as
    entered_manually by the same write."""
    import json
    import uuid
    from sqlalchemy import select
    from app.core.confidence import EDITED
    _, doc = _doc_for(job_id, doc_id, current_user, db, "job.review")
    stamp = {"by": current_user.username, "at": datetime.utcnow().isoformat() + "Z"}
    for _attempt in range(MARK_ATTEMPTS):
        old, reviewed_by = db.execute(select(DocumentResult.extraction_json,
                                             DocumentResult.reviewed_by)
                                      .where(DocumentResult.id == doc.id)).one()
        db.rollback()
        try:
            ed = json.loads(old) if old else {}
        except ValueError:
            ed = {}
        if not isinstance(ed, dict) or not ed:
            raise HTTPException(status_code=422, detail="This document has no stored result")
        spec = next((t for t in (ed.get("slot_map") or {}).get("tables") or []
                     if str(t.get("name")) == table), None)
        key = dict(R.table_keys(ed)).get(table)
        if spec is None or key is None:
            raise HTTPException(status_code=404, detail=f"No table {table!r} on this document")
        columns = [str(c.get("key") or c.get("header")) for c in spec.get("columns") or []]
        unknown = [k for k in payload.values if k not in columns]
        if unknown:
            raise HTTPException(status_code=422, detail=(
                f"Not a column of {table}: {', '.join(unknown)}"))
        given = {k: str(v) for k, v in payload.values.items() if str(v).strip()}
        if not given:
            raise HTTPException(status_code=422, detail="The new row has no values")
        rows = ed.get(key)
        rows = rows if isinstance(rows, list) else []
        ed[key] = rows
        for r in rows:
            if isinstance(r, dict) and not r.get("_row_id"):
                r["_row_id"] = f"r-{uuid.uuid4().hex[:12]}"
        row_id = f"added-{uuid.uuid4().hex[:12]}"
        row = {c: given.get(c, "") for c in columns}
        row.update({"_row_id": row_id, "_added": stamp, "_confidence": EDITED,
                    "_edited": sorted(given), "_original": {c: "" for c in given}})
        pos = len(rows) if payload.position is None else payload.position
        if not 0 <= pos <= len(rows):
            raise HTTPException(status_code=422, detail="Position is outside the table")
        rows.insert(pos, row)
        if payload.attention_id is not None:
            a = next((a for a in R.attention_open(ed)
                      if str(a.get("id")) == str(payload.attention_id)), None)
            if a is None:
                raise HTTPException(status_code=404, detail=(
                    f"No open reason {payload.attention_id} on this document"))
            a["disposition"] = {"choice": "entered_manually",
                                "note": f"row added to {table}", **stamp}
        reflagged = _recheck_totals(ed, table, [r for r in rows if isinstance(r, dict)],
                                    columns)
        ed.setdefault("edit_log", []).append({
            **stamp, "kind": "add_row", "table": table, "row": pos, "row_id": row_id,
            "values": given, "attention_id": payload.attention_id,
            "reflagged_totals": reflagged, "reason": "row added in review"})
        values = R.document_values(ed)
        open_ = R.unsettled(ed)
        cols = {"extraction_json": json.dumps(ed, default=str),
                "reviewed": open_ == 0,
                "reviewed_by": current_user.username if open_ == 0 else reviewed_by,
                "needs_review": open_ > 0}
        if _swap(db, doc.id, old, cols):
            return {"doc_id": doc_id, "table": table, "row": pos, "row_id": row_id,
                    "reflagged_totals": reflagged,
                    "summary": R.summarise(values),
                    "attention": R.attention_items(ed),
                    "document_state": R.document_state(ed)}
    raise HTTPException(status_code=409,
                        detail="This document was changed by someone else at the "
                               "same moment; nothing was added. Try again.")


@router.get("/jobs/{job_id}/docs/{doc_id}/history")
def document_history(job_id: int, doc_id: int, db: Session = Depends(get_db),
                     current_user: User = Depends(get_current_user)):
    """The document's append-only history (Run G, G4): every edit,
    correction, disposition and added row, oldest first, each with who
    (`by`), when (`at`), what (`kind`, `ref` or `table`/`row`/`column`) and
    `old` / `new`. Read-only; nothing here can change a value."""
    _, doc = _doc_for(job_id, doc_id, current_user, db)
    ed = doc.get_extracted_data() or {}
    ed = ed if isinstance(ed, dict) else {}
    events = [e for e in (ed.get("edit_log") or []) if isinstance(e, dict)]
    for a in R.attention_items(ed):
        d = a.get("disposition")
        if isinstance(d, dict) and d.get("at"):
            events.append({"kind": "attention", "attention_id": a.get("id"),
                           "text": a.get("text"), "disposition": d.get("choice"),
                           "note": d.get("note"), "by": d.get("by"), "at": d.get("at")})
    rv = ed.get("review") or {}
    if rv.get("document_reviewed") and rv.get("at"):
        events.append({"kind": "document", "disposition": "document_reviewed",
                       "by": rv.get("by"), "at": rv.get("at")})
    events.sort(key=lambda e: str(e.get("at") or ""))
    return {"doc_id": doc_id, "job_id": job_id, "events": events}


# ── page images and boxes ────────────────────────────────────────────────────

def _source_path(job, doc):
    from app.api.routes.extract import _resolve_source
    from app.core.storage import get_storage
    storage = get_storage()
    for ref in (doc.s3_key,
                storage.upload_key(job.client_id, job.id,
                                   doc.original_filename or doc.filename)):
        if not ref:
            continue
        try:
            p = _resolve_source(storage, ref)
        except Exception:
            p = None
        if p is not None:
            return str(ref), p
    raise HTTPException(status_code=404,
                        detail="The source document is not retained for this result")


def forget_sources(keys) -> int:
    """Drop the cached readings of these source keys — their page and OCR
    images held in memory — and release the temp copy each one rendered from
    (object store only; a local path is the stored file and is left alone).
    Returns how many readings went. Used by a job's hard delete."""
    from app.core.storage import get_storage
    gone = []
    with _cache_lock:
        for k in set(keys):
            r = _cache.pop(k, None)
            if r is not None:
                gone.append(r)
    storage = get_storage()
    for r in gone:
        storage.release(r.get("path"))
    return len(gone)


def _reading(job, doc) -> dict:
    """The engine's own reading of the source file, cached per file."""
    key, path = _source_path(job, doc)
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    import contextlib
    import sys
    from app.api.routes.extract import _backend_dir, _engine_dir, _project_dir
    for p in (str(_engine_dir), str(_backend_dir), str(_project_dir)):
        if p not in sys.path:
            sys.path.insert(0, p)
    from core.preprocessor import ImageTooLarge, preprocess_file
    if str(path).lower().endswith(".pdf"):
        from pdf_password import pdf_lock_state
        try:
            locked = pdf_lock_state(path) != "open"
        except Exception:
            locked = False
        if locked:
            # The password was used once, in memory, and not kept (Part 1.7):
            # the stored original cannot be shown.
            raise HTTPException(status_code=409, detail=(
                "This PDF is password-protected and its password is not kept, "
                "so its pages cannot be shown here. The extracted values are "
                "unaffected."))
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            pd = preprocess_file(path)
    except ImageTooLarge as exc:
        raise HTTPException(status_code=413, detail=str(exc))
    ocr_images = dict(getattr(pd, "ocr_images", {}) or {})
    sizes = {n: (im.width * 72.0 / dpi, im.height * 72.0 / dpi)
             for n, (im, dpi) in ocr_images.items()}
    if pd.file_type == "pdf":
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            for n, pg in enumerate(pdf.pages, 1):
                sizes.setdefault(n, (float(pg.width), float(pg.height)))
    reading = {"path": str(path), "origins": list(pd.page_origins or []),
               "lines": list(pd.page_lines or []), "ocr_images": ocr_images,
               "sizes": sizes,
               "pages": int(pd.total_pages or len(pd.page_lines or []) or 1),
               "file_type": pd.file_type}
    with _cache_lock:
        _cache[key] = reading
        while len(_cache) > _CACHE_FILES:
            _cache.popitem(last=False)
    return reading


def _norm(s) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().casefold()


def _words_box(words) -> list[float]:
    return [round(min(float(w["x0"]) for w in words), 1),
            round(min(float(w["top"]) for w in words), 1),
            round(max(float(w["x1"]) for w in words), 1),
            round(max(float(w.get("bottom", float(w["top"]) + float(w.get("size", 10))))
                      for w in words), 1)]


def _inside(words, region) -> bool:
    if not region:
        return True
    x0, top, x1, bottom = region
    cx = sum((float(w["x0"]) + float(w["x1"])) / 2 for w in words) / len(words)
    cy = sum(float(w["top"]) for w in words) / len(words)
    return x0 - 2 <= cx <= x1 + 2 and top - 2 <= cy <= bottom + 2


#: what `find_box` reports when it located nothing (Run C, C6)
NOT_FOUND = "location not found for this value"


def _key(s) -> str:
    """A value or word with its notation dropped: case, spaces, currency
    symbols and thousands separators. `- 46.32`, `-46.32` and `−46.32` meet."""
    t = str(s or "").casefold().replace("−", "-")
    return re.sub(r"[\s$£€₹¥,]", "", t)


def _value_spans(words, value, max_words=4):
    """Runs of 1..max_words consecutive words on one line that spell `value`
    once notation is dropped — a number the text layer split into two words
    (`-` + `46.32`, `19,6` + `94`) is found as well as a whole one."""
    want = _key(value)
    if not want:
        return []
    out = []
    keys = [_key(w["text"]) for w in words]
    for i in range(len(words)):
        acc = ""
        for j in range(i, min(len(words), i + max_words)):
            acc += keys[j]
            if acc == want:
                out.append(words[i:j + 1])
                break
            if not want.startswith(acc):
                break
    return out


def _centre(box):
    return ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)


def _nearest(boxes, anchors):
    """The box nearest any anchor box (by centre distance); None without
    anchors."""
    if not anchors:
        return None
    def dist(b):
        cx, cy = _centre(b)
        return min((cx - ax) ** 2 + (cy - ay) ** 2
                   for ax, ay in (_centre(a) for a in anchors))
    return min(boxes, key=dist)


def _anchor_boxes(lines, near, region=None):
    """Where each anchor text (a field's label, a row's other values) is
    printed on the page."""
    out = []
    for text in near or []:
        if not _key(text) or len(_key(text)) < 2:
            continue
        for ln in lines or []:
            words = [w for w in ln if str(w.get("text", "")).strip()]
            if not words or not _inside(words, region):
                continue
            joined = _norm(" ".join(str(w["text"]) for w in words))
            if _norm(text) and _norm(text) in joined:
                spans = _value_spans(words, text, max_words=8)
                out.append(_words_box(spans[0]) if spans else _words_box(words))
    return out


def find_box(lines, quote, value, region=None, near=None) -> tuple[Optional[list], str]:
    """(box, how) for a value on one page, or (None, why not).

    The quote's first line matching exactly ONE printed line (inside the
    record's region when it has one) is the strong case: the box is then the
    value's own words on that line when they are there in order, else the
    whole line (`how` = "value" | "line").

    Run C, C6: a real multi-page statement often gives no such line — the
    quote matches two printed lines (a repeated row), or none (the page
    interleaves an overlaid layer with the statement's words, so the model's
    clean quote is not a substring of any printed line, or the value was
    split across words). It used to stop there, and the review screen turned
    to the page and drew nothing. Now, failing a unique quote line, the VALUE
    itself is looked for — among the quote's lines when there are several,
    else on the whole page — with its notation dropped and split words
    rejoined. One place: `how` = "value" (or "line" when only its line is
    known). Several: the one nearest `near` (the slot's label, or the row's
    other values) with `how` = "ambiguous: …" naming the count. None: no box,
    `how` says the location was not found and why.
    """
    q = [_norm(x) for x in str(quote or "").split("\n") if _norm(x)]
    hits = []
    for ln in lines or []:
        words = [w for w in ln if str(w.get("text", "")).strip()]
        if not words or not _inside(words, region):
            continue
        text = _norm(" ".join(str(w["text"]) for w in words))
        if q and text and (q[0] in text or (len(text) > 3 and text in q[0])):
            hits.append(words)
    if len(hits) == 1:
        words = hits[0]
        toks = _norm(value).split()
        if toks:
            texts = [_norm(w["text"]) for w in words]
            for i in range(len(texts) - len(toks) + 1):
                if texts[i:i + len(toks)] == toks:
                    return _words_box(words[i:i + len(toks)]), "value"
            spans = _value_spans(words, value)
            if spans:
                return _words_box(spans[0]), "value"
            # Run E, E3 (C6): the quote's line does not print the value (a
            # label quoted on one line, its amount on another). Box the value
            # itself — nearest its label when it is printed more than once —
            # and fall back to the quote's line only when it is nowhere.
            k = _key(value)
            if k and (len(k) >= 3 or re.search(r"\d", k)):
                cands = [_words_box(s)
                         for ln in (lines or [])
                         for ws in [[w for w in ln if str(w.get("text", "")).strip()]]
                         if ws and _inside(ws, region)
                         for s in _value_spans(ws, value)]
                if len(cands) == 1:
                    return cands[0], "value"
                if cands:
                    pick = (_nearest(cands, _anchor_boxes(lines, near, region))
                            or cands[0])
                    return pick, (f"ambiguous: printed in {len(cands)} places on "
                                  f"this page; showing the one nearest its label")
        return _words_box(words), "line"

    # no unique quote line: look for the value itself
    why = ("no quote was stored for this value" if not q
           else f"the quote matches {len(hits)} lines on this page" if hits
           else "the quote was not found on this page")
    k = _key(value)
    if not k or (len(k) < 3 and not re.search(r"\d", k)):
        return None, f"{NOT_FOUND}: {why}"
    pool = hits or [[w for w in ln if str(w.get("text", "")).strip()]
                    for ln in (lines or [])]
    cands = [_words_box(s) for words in pool if words and _inside(words, region)
             for s in _value_spans(words, value)]
    kind = "value"
    if not cands and hits:
        cands, kind = [_words_box(words) for words in hits], "line"
    if not cands:
        return None, f"{NOT_FOUND}: {why}"
    if len(cands) == 1:
        return cands[0], kind
    pick = _nearest(cands, _anchor_boxes(lines, near, region)) or cands[0]
    return pick, (f"ambiguous: printed in {len(cands)} places on this page; "
                  f"showing the one nearest its label")


def _page_or_404(reading, n):
    if not isinstance(n, int) or n < 1 or n > max(reading["pages"], len(reading["lines"])):
        raise HTTPException(status_code=404, detail="No such page")


@router.get("/jobs/{job_id}/docs/{doc_id}/pages/{page}")
def page_meta(job_id: int, doc_id: int, page: int, db: Session = Depends(get_db),
              current_user: User = Depends(get_current_user)):
    job, doc = _doc_for(job_id, doc_id, current_user, db)
    reading = _reading(job, doc)
    _page_or_404(reading, page)
    ed = doc.get_extracted_data() or {}
    ed = ed if isinstance(ed, dict) else {}
    origin = reading["origins"][page - 1] if page - 1 < len(reading["origins"]) else "native"
    lines = reading["lines"][page - 1] if page - 1 < len(reading["lines"]) else []
    sr = (ed.get("validation") or {}).get("source_region") or {}
    region = sr.get("box_pt") if sr.get("page") == page else None
    boxes = boxes_for(ed, page, lines, region)
    frame = ("straightened page image, points from its top-left"
             if origin == "ocr" else "rendered page, points from its top-left")
    w, h = reading["sizes"].get(page, (None, None))
    return {"page": page, "origin": origin, "frame": frame,
            "width_pt": round(w, 1) if w else None,
            "height_pt": round(h, 1) if h else None,
            "record_box_pt": region, "boxes": boxes,
            # overnight E2: the dialog's previous/next and "page n of N"
            "page_count": max(int(reading.get("pages") or 1), len(reading.get("lines") or [])),
            }


def boxes_for(ed, page, lines, region=None) -> list:
    """Every value stored for `page`, with its box on that page or the reason
    it has none (the page route's `boxes`)."""
    boxes = []
    rows_of = dict(R.table_keys(ed))
    for v in R.document_values(ed):
        if v.get("page") != page:
            continue
        # what a repeated value is placed NEAR (C6): a field's label; a
        # table cell's other values on the same row
        if v["kind"] == "field":
            near = [v.get("label")]
        else:
            rows = ed.get(rows_of.get(v.get("table"), "")) or []
            i = v.get("row")
            row = rows[i] if isinstance(i, int) and 0 <= i < len(rows) else {}
            row = row if isinstance(row, dict) else {}
            near = [x for k, x in (row or {}).items()
                    if not str(k).startswith("_") and k != v.get("column") and x]
        box, how = find_box(lines, v.get("source"), v.get("value"), region, near=near)
        ambiguous = bool(box) and how.startswith("ambiguous")
        boxes.append({"kind": v["kind"], "ref": v.get("ref"), "table": v.get("table"),
                      "row": v.get("row"), "column": v.get("column"),
                      "box_pt": box,
                      "match": ("value" if ambiguous else how) if box else None,
                      "ambiguous": ambiguous,
                      "note": how if ambiguous else None,
                      "no_box_reason": None if box else how})
    return boxes


def _page_png(reading, page) -> bytes:
    from PIL import Image
    origin = reading["origins"][page - 1] if page - 1 < len(reading["origins"]) else "native"
    img = None
    if origin == "ocr" and page in reading["ocr_images"]:
        straight, dpi = reading["ocr_images"][page]
        scale = PAGE_DPI / float(dpi)
        img = straight.resize((max(1, int(straight.width * scale)),
                               max(1, int(straight.height * scale))))
    elif reading["file_type"] == "pdf":
        from ocr_source import ToolTimeout, ToolUnavailable, render_pdf_page
        try:
            img = render_pdf_page(reading["path"], page, dpi=PAGE_DPI)
        except (ToolTimeout, ToolUnavailable) as exc:
            raise HTTPException(status_code=503,
                                detail=f"This page could not be rendered: {exc}")
    else:
        from core.preprocessor import ImageTooLarge, open_image_bounded
        try:
            img = open_image_bounded(reading["path"])   # header checked first
        except ImageTooLarge as exc:
            raise HTTPException(status_code=413, detail=str(exc))
    if img is None:
        raise HTTPException(status_code=404, detail="This page could not be rendered")
    img = img.convert("RGB")
    if max(img.size) > MAX_SIDE_PX:
        img.thumbnail((MAX_SIDE_PX, MAX_SIDE_PX))
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


@router.get("/jobs/{job_id}/docs/{doc_id}/pages/{page}/image")
def page_image(job_id: int, doc_id: int, page: int, db: Session = Depends(get_db),
               current_user: User = Depends(get_current_user)):
    job, doc = _doc_for(job_id, doc_id, current_user, db)
    reading = _reading(job, doc)
    _page_or_404(reading, page)
    key = ("png", page)
    png = reading.get(key)
    if png is None:
        png = _page_png(reading, page)
        reading[key] = png
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "private, max-age=3600"})
