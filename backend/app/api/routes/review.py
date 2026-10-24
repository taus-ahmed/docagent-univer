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

Access: the same `_get_job_or_404` as every job route, except that another
tenant's job answers 404 rather than 403 here, so a page id reveals nothing.
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


def _job_for(job_id, user, db):
    from app.api.routes.extract import _get_job_or_404
    try:
        return _get_job_or_404(job_id, user, db)
    except HTTPException as e:
        if e.status_code == 403:
            raise HTTPException(status_code=404, detail="Job not found")
        raise


def _doc_for(job_id, doc_id, user, db):
    job = _job_for(job_id, user, db)
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
    return sorted(pages)


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
            "failed": not ed,
            "error": d.validation_errors or "",
            "values": values,
            "summary": R.summarise(values),
        })
    s = R.summarise(all_values)
    s["documents"] = len(out)
    s["documents_needing_review"] = sum(1 for o in out if o["summary"]["needs_review"]
                                        or (o["failed"] and not o["document_reviewed"]))
    return {"job_id": job_id, "summary": s, "documents": out}


# ── marking reviewed ─────────────────────────────────────────────────────────

class ReviewMark(BaseModel):
    #: "document", or a list of values: {"ref": "B6"} or
    #: {"table": "table", "row": 0}
    scope: str = Field("values", pattern="^(values|document)$")
    values: list[dict] = []
    reviewed: bool = True


@router.post("/jobs/{job_id}/docs/{doc_id}/review")
def mark_reviewed(job_id: int, doc_id: int, payload: ReviewMark,
                  db: Session = Depends(get_db),
                  current_user: User = Depends(get_current_user)):
    import copy
    _, doc = _doc_for(job_id, doc_id, current_user, db)
    stored = doc.get_extracted_data() or {}
    if not isinstance(stored, dict):
        raise HTTPException(status_code=422, detail="This document has no stored result")
    ed = copy.deepcopy(stored)
    stamp = {"by": current_user.username, "at": datetime.utcnow().isoformat() + "Z"}
    if payload.scope == "document":
        ed["review"] = ({"document_reviewed": True, **stamp} if payload.reviewed
                        else {"document_reviewed": False})
    else:
        prov = ed.setdefault("field_provenance", {})
        tables = dict(R.table_keys(ed))
        for v in payload.values:
            if v.get("ref") is not None:
                ref = str(v["ref"])
                if ref not in prov and ref not in (ed.get("extracted_fields") or {}):
                    raise HTTPException(status_code=404, detail=f"No field at {ref!r}")
                p = prov.setdefault(ref, {})
                if payload.reviewed:
                    p["reviewed"] = stamp
                else:
                    p.pop("reviewed", None)
            elif v.get("table") is not None and isinstance(v.get("row"), int):
                key = tables.get(str(v["table"]))
                rows = ed.get(key) if key else None
                if not isinstance(rows, list) or not 0 <= v["row"] < len(rows) \
                        or not isinstance(rows[v["row"]], dict):
                    raise HTTPException(status_code=404, detail="No such table row")
                if payload.reviewed:
                    rows[v["row"]]["_reviewed"] = stamp
                else:
                    rows[v["row"]].pop("_reviewed", None)
            else:
                raise HTTPException(status_code=422,
                                    detail="Each value needs a ref, or a table and a row")
    values = R.document_values(ed)
    open_ = R.summarise(values)["needs_review"]
    doc.set_extracted_data(ed)
    # The document is reviewed when nothing in it is still owed a look.
    doc.reviewed = open_ == 0
    doc.reviewed_by = current_user.username if open_ == 0 else doc.reviewed_by
    if open_ == 0:
        doc.reviewed_at = datetime.utcnow()
        doc.needs_review = False
    db.commit()
    return {"doc_id": doc_id, "summary": R.summarise(values), "values": values,
            "document_reviewed": R.document_reviewed(ed)}


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
    from core.preprocessor import preprocess_file
    with contextlib.redirect_stdout(io.StringIO()):
        pd = preprocess_file(path)
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


def find_box(lines, quote, value, region=None) -> tuple[Optional[list], str]:
    """(box, how) for a value on one page, or (None, why not).

    The quote's first line must match exactly ONE printed line (inside the
    record's region when it has one); the box is then the value's own words on
    that line when they are there in order, else the whole line."""
    q = [_norm(x) for x in str(quote or "").split("\n") if _norm(x)]
    if not q:
        return None, "no quote was stored for this value"
    hits = []
    for ln in lines or []:
        words = [w for w in ln if str(w.get("text", "")).strip()]
        if not words or not _inside(words, region):
            continue
        text = _norm(" ".join(str(w["text"]) for w in words))
        if text and (q[0] in text or (len(text) > 3 and text in q[0])):
            hits.append(words)
    if not hits:
        return None, "the quote was not found on this page"
    if len(hits) > 1:
        return None, f"the quote matches {len(hits)} lines on this page"
    words = hits[0]
    toks = _norm(value).split()
    if toks:
        texts = [_norm(w["text"]) for w in words]
        for i in range(len(texts) - len(toks) + 1):
            if texts[i:i + len(toks)] == toks:
                return _words_box(words[i:i + len(toks)]), "value"
    return _words_box(words), "line"


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
    boxes = []
    for v in R.document_values(ed):
        if v.get("page") != page:
            continue
        box, how = find_box(lines, v.get("source"), v.get("value"), region)
        boxes.append({"kind": v["kind"], "ref": v.get("ref"), "table": v.get("table"),
                      "row": v.get("row"), "column": v.get("column"),
                      "box_pt": box, "match": how if box else None,
                      "no_box_reason": None if box else how})
    frame = ("straightened page image, points from its top-left"
             if origin == "ocr" else "rendered page, points from its top-left")
    w, h = reading["sizes"].get(page, (None, None))
    return {"page": page, "origin": origin, "frame": frame,
            "width_pt": round(w, 1) if w else None,
            "height_pt": round(h, 1) if h else None,
            "record_box_pt": region, "boxes": boxes}


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
        from ocr_source import render_pdf_page
        img = render_pdf_page(reading["path"], page, dpi=PAGE_DPI)
    else:
        img = Image.open(reading["path"])
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
