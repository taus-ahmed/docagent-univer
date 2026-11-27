"""Reviewer structure edits (Run T2, Stage 6): correct a document's Organized
layout without retyping it. Contract: docs/REVIEWER_STRUCTURE_API.md.

    GET    /api/jobs/{job_id}/docs/{doc_id}/structure                  the layout + edits
    POST   /api/jobs/{job_id}/docs/{doc_id}/structure/edits            add one edit
    DELETE /api/jobs/{job_id}/docs/{doc_id}/structure/edits/{edit_id}  remove one edit

Edits are stored with the document's words (`perception_json`), each with
who made it and when; the Organized export lays the document out from the
stored words, plan and edits, so it applies them. An edit that cannot apply
to the layout as it stands is refused (422) and never stored."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

import app.services.paths  # noqa: F401  (engine on sys.path)
from app.core.auth import get_current_user
from app.models import DocumentResult, User, get_db

router = APIRouter(prefix="/api", tags=["structure"])


class StructureEdit(BaseModel):
    op: str
    page: int
    line_id: Optional[str] = None
    reason: Optional[str] = None
    region: Optional[str] = None
    word_ids: Optional[Any] = None
    column: Optional[int] = None
    cell: Optional[str] = None
    to: Optional[str] = None
    cells: Optional[list] = None
    at: Optional[int] = None


def _doc(job_id, doc_id, user, db, action):
    from app.api.routes.extract import _get_job_or_404
    _get_job_or_404(job_id, user, db, action)
    doc = db.query(DocumentResult).filter(DocumentResult.id == doc_id,
                                          DocumentResult.job_id == job_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


def _perception(doc):
    """The stored words; for a record stored before them, read once from the
    stored source file and KEPT (so an edit has stable word and line ids)."""
    from app.services import perception_store as PS
    perc = PS.stored(doc)
    if perc is not None:
        return perc, False
    if not getattr(doc, "s3_key", None):
        return None, False
    from app.core.storage import get_storage
    import perception as P
    st = get_storage()
    path = st.get_local_path(doc.s3_key)
    if path is None:
        return None, False
    try:
        return P.read_document(path), True
    except Exception:
        return None, False
    finally:
        st.release(path)


def _view(perc) -> dict:
    """The layout as the reviewer sees it: per page its cells (address,
    text, word ids, region), its regions with anchors, its lines with
    whether each is left out and why; and the edits with their results."""
    import structure_engine as S
    from openpyxl.utils import get_column_letter
    lay = S.layout_document(perc, plans=S.stored_plans(perc))
    excluded = {}
    for e in lay["excluded"]:
        if e.get("line_id"):
            excluded[(e["page"], e["line_id"])] = e["reason"]
    pages = []
    cell_pages = iter(lay["pages"])
    for pg in perc.get("pages") or []:
        n = pg["page"]
        if n not in lay["plans"]:
            pages.append({"page": n, "skipped": True, "cells": [], "regions": [], "lines": []})
            continue
        cells = next(cell_pages, [])
        regions = [{"id": r["id"], "kind": r["kind"], "line_ids": r.get("line_ids") or [],
                    "anchor": lay["anchors"].get(n, {}).get(r["id"]),
                    "columns": len(r.get("columns") or []) or None}
                   for r in lay["plans"][n].get("regions") or []]
        pages.append({
            "page": n,
            "cells": [{"cell": f"{get_column_letter(c['col'] + 1)}{c['row'] + 1}",
                       "text": c.get("text"), "word_ids": c.get("word_ids") or [],
                       "kind": c.get("kind"), "edited": bool(c.get("edited"))}
                      for c in sorted(cells, key=lambda c: (c["row"], c["col"]))],
            "regions": regions,
            "lines": [{"id": ln["id"], "text": ln["text"],
                       "left_out": (n, ln["id"]) in excluded,
                       "reason": excluded.get((n, ln["id"]))} for ln in pg.get("lines") or []]})
    return {"pages": pages, "edits": perc.get("structure_edits") or [],
            "edit_results": lay.get("edit_results") or [], "flags": lay["flags"],
            "skipped": lay["skipped"]}


def _save(doc, perc, db):
    import perception as P
    doc.perception_json = P.pack(perc)
    db.commit()


@router.get("/jobs/{job_id}/docs/{doc_id}/structure")
def get_structure(job_id: int, doc_id: int, db: Session = Depends(get_db),
                  current_user: User = Depends(get_current_user)):
    doc = _doc(job_id, doc_id, current_user, db, "job.view")
    perc, _fresh = _perception(doc)
    if perc is None:
        raise HTTPException(status_code=404, detail="This document has no stored layout")
    return _view(perc)


@router.post("/jobs/{job_id}/docs/{doc_id}/structure/edits", status_code=201)
def add_structure_edit(job_id: int, doc_id: int, payload: StructureEdit,
                       db: Session = Depends(get_db),
                       current_user: User = Depends(get_current_user)):
    import structure_edits as SE
    doc = _doc(job_id, doc_id, current_user, db, "job.review")
    perc, _fresh = _perception(doc)
    if perc is None:
        raise HTTPException(status_code=404, detail="This document has no stored layout")
    edit = {k: v for k, v in payload.model_dump().items() if v is not None}
    errs = SE.check_shape(edit)
    if errs:
        raise HTTPException(status_code=422, detail={"message": "invalid edit", "errors": errs})
    if edit["page"] not in {p["page"] for p in perc.get("pages") or []}:
        raise HTTPException(status_code=422, detail={"message": "invalid edit",
                                                     "errors": [f"no page {edit['page']}"]})
    # a cell edit records the words of the cell(s) it was made on, so it can
    # never land on other words later
    if edit["op"] in SE.CELL_OPS:
        page_cells = next((p["cells"] for p in _view(perc)["pages"] if p["page"] == edit["page"]),
                          [])
        words_at = {c["cell"]: c["word_ids"] for c in page_cells}
        if edit["op"] == "merge_cells":
            edit["word_ids"] = [words_at.get(a) for a in edit["cells"]]
        else:
            edit["word_ids"] = words_at.get(edit["cell"])
    edits = list(perc.get("structure_edits") or [])
    edit["id"] = max([e.get("id", 0) for e in edits] + [0]) + 1
    edit["by"] = current_user.username
    edit["when"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    trial = dict(perc, structure_edits=edits + [edit])
    view = _view(trial)
    res = next((r for r in view["edit_results"] if r["id"] == edit["id"]), None)
    if res is None or not res["applied"]:
        raise HTTPException(status_code=422, detail={
            "message": "this edit cannot apply to the layout as it stands",
            "errors": [res["why"] if res else "the page was not laid out"]})
    _save(doc, trial, db)
    return {"edit": edit, **view}


@router.delete("/jobs/{job_id}/docs/{doc_id}/structure/edits/{edit_id}")
def delete_structure_edit(job_id: int, doc_id: int, edit_id: int,
                          db: Session = Depends(get_db),
                          current_user: User = Depends(get_current_user)):
    doc = _doc(job_id, doc_id, current_user, db, "job.review")
    perc, _fresh = _perception(doc)
    edits = list((perc or {}).get("structure_edits") or [])
    if not any(e.get("id") == edit_id for e in edits):
        raise HTTPException(status_code=404, detail="Edit not found")
    perc["structure_edits"] = [e for e in edits if e.get("id") != edit_id]
    _save(doc, perc, db)
    return _view(perc)
