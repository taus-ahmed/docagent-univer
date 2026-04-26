"""
DocAgent v2 — Extract Routes (Univer branch)
Upgraded extraction: header fields + line items, all rows extracted.
"""

import sys
import time
import json
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.config import settings
from app.core.auth import get_current_user
from app.core.storage import get_storage
from app.models import get_db, User, ExtractionJob, DocumentResult, ColumnTemplate
from app.schemas.schemas import (
    JobStatus, JobListItem, DocumentResultResponse,
    DocumentUpdateRequest, ExtractUploadResponse,
)

router = APIRouter(prefix="/api", tags=["extract"])

_backend_dir = Path(__file__).resolve().parent.parent.parent.parent
_project_dir = _backend_dir.parent
_engine_dir  = _backend_dir / "engine"


@router.post("/extract/upload", response_model=ExtractUploadResponse, status_code=202)
async def upload_and_extract(
    files: list[UploadFile] = File(...),
    client_id: str = Form(...),
    template_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    storage=Depends(get_storage),
):
    if len(files) > settings.MAX_FILES_PER_BATCH:
        raise HTTPException(status_code=400, detail=f"Max {settings.MAX_FILES_PER_BATCH} files.")

    for f in files:
        content = await f.read()
        await f.seek(0)
        error = storage.validate_upload(f.filename, len(content))
        if error:
            raise HTTPException(status_code=400, detail=f"{f.filename}: {error}")

    schema_path = storage.get_schema_path(client_id)
    if schema_path is None:
        schema_path = storage.get_schema_path("demo_001")
    if schema_path is None:
        raise HTTPException(status_code=404, detail="No schema found.")

    # Load template with extraction_type per column
    template_data = None
    if template_id:
        tpl = db.query(ColumnTemplate).filter(ColumnTemplate.id == template_id).first()
        if tpl and tpl.columns_json:
            try:
                raw = json.loads(tpl.columns_json)
                header_cols = []
                lineitem_cols = []
                for i, item in enumerate(raw):
                    if isinstance(item, str):
                        col = {"name": item, "type": "Text", "order": i, "extraction_type": "header"}
                    else:
                        col = {
                            "name": item.get("name", ""),
                            "type": item.get("type", "Text"),
                            "order": item.get("order", i),
                            "extraction_type": item.get("extraction_type", "header"),
                        }
                    if col["extraction_type"] == "lineitem":
                        lineitem_cols.append(col)
                    else:
                        header_cols.append(col)

                template_data = {
                    "header_cols": header_cols,
                    "lineitem_cols": lineitem_cols,
                    "doc_type": tpl.document_type,
                    "all_cols": raw if isinstance(raw[0], dict) else [{"name": c, "type": "Text", "order": i, "extraction_type": "header"} for i, c in enumerate(raw)],
                }
            except Exception as e:
                print(f"[UPLOAD] Template parse error: {e}", flush=True)

    job = ExtractionJob(
        user_id=current_user.id,
        client_id=client_id,
        status="pending",
        total_docs=len(files),
        input_source="upload",
        started_at=datetime.utcnow(),
        schema_id=str(template_id) if template_id else None,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    job_id = job.id

    saved_paths = []
    for f in files:
        content = await f.read()
        local_path, _ = storage.save_upload(content, f.filename, job_id, current_user.id)
        saved_paths.append(str(local_path))

    thread = threading.Thread(
        target=_run_extraction_sync,
        args=(job_id, saved_paths, str(schema_path), settings.DATABASE_URL,
              template_data, str(_project_dir), str(_backend_dir), str(_engine_dir)),
        daemon=True,
    )
    thread.start()

    return ExtractUploadResponse(
        job_id=job_id,
        message=f"Extraction started for {len(files)} file(s)",
        total_files=len(files),
        status="processing",
    )


def _run_extraction_sync(
    job_id: int,
    file_paths: list,
    schema_path: str,
    db_url: str,
    template_data: Optional[dict],
    project_dir: str,
    backend_dir: str,
    engine_dir: str,
):
    import os, traceback
    os.environ["PYTHONUTF8"] = "1"

    for p in [engine_dir, backend_dir, project_dir]:
        if p not in sys.path:
            sys.path.insert(0, p)

    print(f"[THREAD] job={job_id} template={'yes' if template_data else 'no'}", flush=True)

    try:
        from sqlalchemy import create_engine as sa_engine
        from sqlalchemy.orm import sessionmaker
        from app.models.models import ExtractionJob, DocumentResult
    except Exception as e:
        print(f"[THREAD] DB import failed: {e}", flush=True)
        return

    try:
        connect_args = {"check_same_thread": False} if "sqlite" in db_url else {}
        _eng = sa_engine(db_url, connect_args=connect_args)
        Session = sessionmaker(bind=_eng)
        session = Session()
    except Exception as e:
        print(f"[THREAD] DB session failed: {e}", flush=True)
        return

    try:
        job = session.query(ExtractionJob).filter_by(id=job_id).first()
        if not job:
            return
        job.status = "processing"
        session.commit()

        from orchestrator import Orchestrator
        orchestrator = Orchestrator(client_schema_path=schema_path)
        print(f"[THREAD] Orchestrator OK", flush=True)

        successful = failed = needs_review = 0
        start_time = time.time()
        all_docs = []

        for fp in file_paths:
            try:
                file_path = Path(fp)
                if template_data:
                    raw_results = _extract_with_template(orchestrator, file_path, template_data)
                else:
                    result = orchestrator._process_single_document(file_path)
                    raw_results = [result] if result.success else []
                    if not raw_results:
                        raw_results = [result]

                for result in raw_results:
                    doc = DocumentResult(
                        job_id=job_id,
                        filename=result.filename,
                        document_type=result.document_type if result.success else "unknown",
                        overall_confidence=(result.extracted_data or {}).get("overall_confidence"),
                        extraction_json=json.dumps(result.extracted_data, default=str) if result.extracted_data else None,
                        validation_errors="; ".join(result.validation.errors) if result.validation else "",
                        validation_warnings="; ".join(result.validation.warnings) if result.validation else "",
                        needs_review=result.validation.needs_review if result.validation else False,
                        model_used=result.extraction_response.model_used if result.extraction_response else "",
                        tokens_used=result.extraction_response.tokens_used if result.extraction_response else 0,
                        latency_ms=result.processing_time_ms,
                    )
                    session.add(doc)
                    all_docs.append(doc)
                    if result.success:
                        successful += 1
                        if result.validation and result.validation.needs_review:
                            needs_review += 1
                    else:
                        failed += 1

            except Exception as doc_err:
                print(f"[THREAD] doc error: {doc_err}", flush=True)
                traceback.print_exc()
                failed += 1

        session.commit()
        job.status = "completed"
        job.successful = successful
        job.failed = failed
        job.needs_review = needs_review
        job.total_time_sec = time.time() - start_time
        job.completed_at = datetime.utcnow()
        session.commit()
        print(f"[THREAD] done: {successful} docs ok, {failed} failed", flush=True)

    except Exception as e:
        print(f"[THREAD] FAILED: {e}", flush=True)
        traceback.print_exc()
        try:
            job = session.query(ExtractionJob).filter_by(id=job_id).first()
            if job:
                job.status = "failed"
                job.error_message = str(e)
                job.completed_at = datetime.utcnow()
                session.commit()
        except Exception:
            pass
    finally:
        session.close()


def _build_template_prompt(template_data: dict, doc_type: str) -> str:
    """
    Build a rich extraction prompt that instructs the AI to:
    1. Extract header fields ONCE per document
    2. Extract ALL line items as an array (every row, not just the first)
    3. Return empty string for missing fields (never null/N/A)
    """
    header_cols = template_data.get("header_cols", [])
    lineitem_cols = template_data.get("lineitem_cols", [])

    # If no explicit types, treat all as header
    if not header_cols and not lineitem_cols:
        header_cols = template_data.get("all_cols", [])

    def col_hint(col):
        t = col.get("type", "Text")
        return {
            "Number":   "number only, no currency symbols or commas",
            "Currency": "number only, no currency symbols or commas (e.g. 1250.00 not $1,250.00)",
            "Date":     "YYYY-MM-DD format",
            "Text":     "text as-is",
        }.get(t, "text")

    header_lines = "\n".join(
        f'  - "{c["name"]}": {col_hint(c)}'
        for c in sorted(header_cols, key=lambda x: x.get("order", 0))
        if c.get("name", "").strip()
    )

    lineitem_lines = "\n".join(
        f'  - "{c["name"]}": {col_hint(c)}'
        for c in sorted(lineitem_cols, key=lambda x: x.get("order", 0))
        if c.get("name", "").strip()
    )

    has_lineitems = bool(lineitem_cols)

    prompt = f"""You are an expert document data extraction agent specializing in {doc_type} documents.
Your extractions are highly accurate and complete — you never miss line items.

"""

    if header_lines:
        prompt += f"""HEADER FIELDS (extract exactly ONCE per document — these are document-level fields):
{header_lines}

"""

    if has_lineitems:
        prompt += f"""LINE ITEM FIELDS (extract for EVERY SINGLE ROW in the document — do not stop at the first):
{lineitem_lines}

CRITICAL LINE ITEM RULES:
- Scan the ENTIRE document from top to bottom
- Extract EVERY product/service row, not just the first one
- If a document has 14 line items, return all 14 objects in the array
- Do not summarize or combine rows
- Each row = one object in the line_items array

"""

    prompt += f"""UNIVERSAL RULES:
1. If a field is NOT present in the document → return "" (empty string). NEVER use null, "N/A", "-", "n/a", "none", or any other placeholder.
2. Numbers: strip all currency symbols and commas. "$1,250.00" → 1250.00
3. Dates: normalize to YYYY-MM-DD. "Jun 18, 2025" → "2025-06-18"
4. Text fields: extract verbatim, preserve original spelling/case
5. Do not invent or guess data that is not clearly visible in the document

Respond with ONLY this JSON (no markdown, no explanation, no ```):
{{
  "document_type": "{doc_type}",
  "overall_confidence": "high|medium|low",
  "header": {{
    "FIELD_NAME": {{"value": "extracted value or empty string", "confidence": "high|medium|low"}}
  }},
  "line_items": [
    {{"FIELD_NAME": "value", "FIELD_NAME": "value"}},
    ... one object per line item row
  ],
  "metadata": {{
    "total_line_items_found": 0,
    "currency_detected": null,
    "extraction_notes": ""
  }}
}}

Replace FIELD_NAME with the exact field names listed above.
Scan the entire document now and extract all data:"""

    return prompt


def _extract_with_template(orchestrator, file_path: Path, template_data: dict):
    """
    Extract using template prompt. Returns a list of DocumentExtractionResult objects —
    one per line item row (header fields repeated), or just one if no line items.
    """
    import time as t
    from core.preprocessor import preprocess_file

    doc_type = template_data.get("doc_type", "document")
    prompt = _build_template_prompt(template_data, doc_type)
    start = t.time()

    results = []

    try:
        doc = preprocess_file(file_path)
        use_vision = doc.needs_vision and bool(doc.page_images_b64)

        if use_vision:
            extraction = orchestrator.llm.extract(image_b64=doc.page_images_b64[0], prompt=prompt)
        else:
            extraction = orchestrator.llm.extract(text=doc.extracted_text, prompt=prompt)

        elapsed = (t.time() - start) * 1000

        if not extraction.success or not extraction.parsed_json:
            # Return a failed result
            from orchestrator import DocumentExtractionResult
            r = DocumentExtractionResult(filename=file_path.name)
            r.error = f"Extraction failed: {extraction.error}"
            r.processing_time_ms = elapsed
            return [r]

        raw = extraction.parsed_json
        header_data = raw.get("header", raw.get("extracted_data", {}))
        line_items = raw.get("line_items", [])
        confidence = raw.get("overall_confidence", "medium")
        metadata = raw.get("metadata", {})

        header_cols = template_data.get("header_cols", [])
        lineitem_cols = template_data.get("lineitem_cols", [])

        # Normalize header fields — missing = ""
        normalized_header = {}
        for col in header_cols:
            name = col.get("name", "").strip()
            if not name:
                continue
            fd = header_data.get(name)
            if fd is None:
                normalized_header[name] = {"value": "", "confidence": "high"}
            elif isinstance(fd, dict):
                v = fd.get("value")
                normalized_header[name] = {"value": "" if v is None else v, "confidence": fd.get("confidence", "high")}
            else:
                normalized_header[name] = {"value": "" if fd is None else fd, "confidence": "high"}

        if not line_items or not lineitem_cols:
            # No line items — return single result with all header fields
            from orchestrator import DocumentExtractionResult
            r = DocumentExtractionResult(filename=file_path.name)
            r.document_type = doc_type
            r.extracted_data = {
                "document_type": doc_type,
                "overall_confidence": confidence,
                "extracted_data": normalized_header,
                "line_items": [],
                "metadata": metadata,
            }
            r.extraction_response = extraction
            r.processing_time_ms = elapsed
            r.success = True
            return [r]

        # Expand line items — one result per row, header fields repeated
        from orchestrator import DocumentExtractionResult
        for li_idx, li_row in enumerate(line_items):
            r = DocumentExtractionResult(filename=file_path.name)
            r.document_type = doc_type

            # Merge header + this line item row
            row_data = dict(normalized_header)
            for col in lineitem_cols:
                name = col.get("name", "").strip()
                if not name:
                    continue
                v = li_row.get(name)
                row_data[name] = {"value": "" if v is None else v, "confidence": "high"}

            r.extracted_data = {
                "document_type": doc_type,
                "overall_confidence": confidence,
                "extracted_data": row_data,
                "line_items": [],
                "metadata": {**metadata, "line_item_index": li_idx},
            }
            r.extraction_response = extraction
            r.processing_time_ms = elapsed / len(line_items)
            r.success = True
            results.append(r)

        print(f"[THREAD] {file_path.name}: {len(results)} line item rows extracted", flush=True)

    except Exception as e:
        import traceback
        print(f"[THREAD] template extract error: {e}", flush=True)
        traceback.print_exc()
        from orchestrator import DocumentExtractionResult
        r = DocumentExtractionResult(filename=file_path.name)
        r.error = str(e)
        r.processing_time_ms = (t.time() - start) * 1000
        results.append(r)

    return results if results else [_make_failed_result(file_path.name, "No data extracted")]


def _make_failed_result(filename: str, error: str):
    from orchestrator import DocumentExtractionResult
    r = DocumentExtractionResult(filename=filename)
    r.error = error
    r.processing_time_ms = 0
    return r


# ─── Job Routes ───────────────────────────────────────────────────────────────

@router.get("/jobs", response_model=list[JobListItem])
def list_jobs(limit: int = 50, offset: int = 0, status_filter: Optional[str] = None,
              db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    q = db.query(ExtractionJob).order_by(ExtractionJob.created_at.desc())
    if current_user.role != "admin":
        q = q.filter(ExtractionJob.user_id == current_user.id)
    if status_filter:
        q = q.filter(ExtractionJob.status == status_filter)
    return q.offset(offset).limit(limit).all()


@router.get("/jobs/{job_id}", response_model=JobStatus)
def get_job(job_id: int, db: Session = Depends(get_db),
            current_user: User = Depends(get_current_user)):
    return _get_job_or_404(job_id, current_user, db)


@router.get("/jobs/{job_id}/results", response_model=list[DocumentResultResponse])
def get_job_results(job_id: int, doc_type: Optional[str] = None,
                    needs_review: Optional[bool] = None,
                    db: Session = Depends(get_db),
                    current_user: User = Depends(get_current_user)):
    _get_job_or_404(job_id, current_user, db)
    q = db.query(DocumentResult).filter(DocumentResult.job_id == job_id)
    if doc_type:
        q = q.filter(DocumentResult.document_type == doc_type)
    if needs_review is not None:
        q = q.filter(DocumentResult.needs_review == needs_review)
    docs = q.order_by(DocumentResult.id).all()
    return [DocumentResultResponse(
        id=d.id, job_id=d.job_id, filename=d.filename,
        document_type=d.document_type, overall_confidence=d.overall_confidence,
        extracted_data=d.get_extracted_data(),
        validation_errors=d.validation_errors, validation_warnings=d.validation_warnings,
        needs_review=d.needs_review, reviewed=d.reviewed, reviewed_by=d.reviewed_by,
        model_used=d.model_used, tokens_used=d.tokens_used or 0,
        latency_ms=d.latency_ms or 0, created_at=d.created_at,
    ) for d in docs]


@router.put("/jobs/{job_id}/docs/{doc_id}")
def update_document(job_id: int, doc_id: int, payload: DocumentUpdateRequest,
                    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _get_job_or_404(job_id, current_user, db)
    doc = db.query(DocumentResult).filter(DocumentResult.id == doc_id, DocumentResult.job_id == job_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    doc.set_extracted_data(payload.extracted_data)
    doc.reviewed = True
    doc.reviewed_by = current_user.username
    doc.reviewed_at = datetime.utcnow()
    doc.needs_review = False
    db.commit()
    return {"message": "Document updated", "doc_id": doc_id}


@router.post("/jobs/{job_id}/docs/{doc_id}/approve")
def approve_document(job_id: int, doc_id: int, db: Session = Depends(get_db),
                     current_user: User = Depends(get_current_user)):
    _get_job_or_404(job_id, current_user, db)
    doc = db.query(DocumentResult).filter(DocumentResult.id == doc_id, DocumentResult.job_id == job_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    doc.reviewed = True
    doc.reviewed_by = current_user.username
    doc.reviewed_at = datetime.utcnow()
    doc.needs_review = False
    db.commit()
    return {"message": "Document approved", "doc_id": doc_id}


@router.delete("/jobs/{job_id}")
def cancel_job(job_id: int, db: Session = Depends(get_db),
               current_user: User = Depends(get_current_user)):
    job = _get_job_or_404(job_id, current_user, db)
    if job.status not in ("pending", "processing"):
        raise HTTPException(status_code=400, detail=f"Cannot cancel job with status '{job.status}'")
    job.status = "cancelled"
    job.completed_at = datetime.utcnow()
    db.commit()
    return {"message": "Job cancelled", "job_id": job_id}


def _get_job_or_404(job_id: int, current_user, db) -> ExtractionJob:
    job = db.query(ExtractionJob).filter(ExtractionJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if current_user.role != "admin" and job.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    return job
