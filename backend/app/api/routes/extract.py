"""
DocAgent v2 — Extract Routes (Layout-aware template extraction)
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

    schema_path = storage.get_schema_path(client_id) or storage.get_schema_path("demo_001")
    if schema_path is None:
        raise HTTPException(status_code=404, detail="No schema found.")

    # Load template with full layout data
    template_data = None
    if template_id:
        tpl = db.query(ColumnTemplate).filter(ColumnTemplate.id == template_id).first()
        if tpl:
            template_data = _parse_template(tpl)

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


def _parse_template(tpl: ColumnTemplate) -> Optional[dict]:
    """Parse template into extraction-ready format."""
    if not tpl.columns_json:
        return None
    try:
        raw = json.loads(tpl.columns_json)

        # New format: full layout with extraction targets
        if isinstance(raw, dict) and "extractTargets" in raw:
            return {
                "mode": "layout",
                "layout": raw,
                "doc_type": tpl.document_type,
                "name": tpl.name,
            }

        # Legacy format: flat column list
        header_cols, lineitem_cols = [], []
        for i, item in enumerate(raw if isinstance(raw, list) else []):
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

        return {
            "mode": "columns",
            "header_cols": header_cols,
            "lineitem_cols": lineitem_cols,
            "doc_type": tpl.document_type,
            "name": tpl.name,
        }
    except Exception as e:
        print(f"[TEMPLATE] Parse error: {e}", flush=True)
        return None


def _build_layout_prompt(template_data: dict, doc_text: str) -> str:
    """
    Build a prompt for layout-aware extraction.
    Sends the full template grid structure to the AI.
    AI fills in extraction targets and repeats rows as needed.
    """
    layout = template_data["layout"]
    doc_type = template_data.get("doc_type", "document")

    cells = layout.get("cells", {})
    merges = layout.get("merges", {})
    extract_targets = layout.get("extractTargets", [])
    repeat_rows = layout.get("repeatRows", [])

    # Build human-readable grid description
    grid_lines = []
    # Find max row/col used
    max_r, max_c = 0, 0
    for key in cells:
        parts = key.split(",")
        if len(parts) == 2:
            r, c = int(parts[0]), int(parts[1])
            max_r = max(max_r, r)
            max_c = max(max_c, c)

    for r in range(min(max_r + 1, 30)):
        row_cells = []
        for c in range(min(max_c + 1, 26)):
            k = f"{r},{c}"
            cell = cells.get(k, {})
            val = cell.get("value", "").strip() if isinstance(cell, dict) else ""
            is_extract = cell.get("extractTarget", False) if isinstance(cell, dict) else False
            is_repeat = cell.get("repeatRow", False) if isinstance(cell, dict) else False

            if val or is_extract:
                col_letter = ""
                n = c
                while True:
                    col_letter = chr(65 + (n % 26)) + col_letter
                    n = n // 26 - 1
                    if n < 0:
                        break
                cell_ref = f"{col_letter}{r+1}"

                if is_repeat:
                    row_cells.append(f"{cell_ref}=[REPEAT: {val or 'line item field'}]")
                elif is_extract:
                    row_cells.append(f"{cell_ref}=[EXTRACT: {val or 'value'}]")
                elif val:
                    row_cells.append(f"{cell_ref}=\"{val}\"")

        if row_cells:
            row_in_repeat = r in repeat_rows
            prefix = "  [REPEAT ROW] " if row_in_repeat else "  "
            grid_lines.append(f"{prefix}Row {r+1}: {' | '.join(row_cells)}")

    grid_description = "\n".join(grid_lines) if grid_lines else "  (empty template)"

    # Build extract targets list
    extract_list = []
    for t in extract_targets:
        r, c, label = t.get("r", 0), t.get("c", 0), t.get("label", "")
        col_letter = ""
        n = c
        while True:
            col_letter = chr(65 + (n % 26)) + col_letter
            n = n // 26 - 1
            if n < 0:
                break
        in_repeat = r in repeat_rows
        extract_list.append(f"  - Cell {col_letter}{r+1}: \"{label}\"{'  [REPEATING]' if in_repeat else ''}")

    extract_description = "\n".join(extract_list) if extract_list else "  (no extraction targets marked)"

    prompt = f"""You are an expert {doc_type} data extraction agent. Your job is to fill in a template with data extracted from a document.

TEMPLATE LAYOUT:
The user has designed this template layout. Cells marked [EXTRACT] need to be filled with data from the document. Cells marked [REPEAT] are in repeating rows that should be duplicated for each line item.

Template grid:
{grid_description}

CELLS TO FILL:
{extract_description}

REPEATING ROWS: {repeat_rows if repeat_rows else 'None'}
For repeating rows: extract ALL line items from the document and create one entry per item.

DOCUMENT CONTENT:
{doc_text[:8000]}

EXTRACTION RULES:
1. For each [EXTRACT] cell, find the matching value in the document
2. For [REPEAT] rows, return one set of values per line item — extract ALL items, not just the first
3. Missing fields → use empty string ""
4. Numbers: strip currency symbols, remove commas (e.g. "$1,250.00" → "1250.00")
5. Dates: normalize to YYYY-MM-DD format
6. Do not invent data not present in the document

Return ONLY this JSON (no markdown, no explanation):
{{
  "document_type": "{doc_type}",
  "overall_confidence": "high|medium|low",
  "extracted_fields": {{
    "CELL_REF": "value"
  }},
  "repeat_rows": [
    {{
      "CELL_REF": "value",
      "CELL_REF": "value"
    }}
  ],
  "metadata": {{
    "total_line_items": 0,
    "notes": ""
  }}
}}

Replace CELL_REF with the actual cell reference (e.g. "B2", "A5").
For repeat_rows: create one object per line item, each containing cell references and their values.
Extract the data now:"""

    return prompt


def _build_columns_prompt(template_data: dict, doc_text: str) -> str:
    """Legacy column-list based prompt."""
    header_cols = template_data.get("header_cols", [])
    lineitem_cols = template_data.get("lineitem_cols", [])
    doc_type = template_data.get("doc_type", "document")

    def col_hint(col):
        return {"Number": "number only", "Currency": "number only, no symbols", "Date": "YYYY-MM-DD", "Text": "text"}.get(col.get("type", "Text"), "text")

    header_lines = "\n".join(f'  - "{c["name"]}": {col_hint(c)}' for c in sorted(header_cols, key=lambda x: x.get("order", 0)) if c.get("name", "").strip())
    lineitem_lines = "\n".join(f'  - "{c["name"]}": {col_hint(c)}' for c in sorted(lineitem_cols, key=lambda x: x.get("order", 0)) if c.get("name", "").strip())

    prompt = f"""You are an expert {doc_type} data extraction agent.

"""
    if header_lines:
        prompt += f"HEADER FIELDS (extract once per document):\n{header_lines}\n\n"
    if lineitem_lines:
        prompt += f"""LINE ITEM FIELDS (extract for EVERY SINGLE ROW — do not stop at first):
{lineitem_lines}

CRITICAL: Scan the ENTIRE document. If there are 14 line items, return all 14 objects.

"""
    prompt += f"""RULES:
1. Missing fields → "" (never null or N/A)
2. Numbers: strip currency symbols and commas
3. Dates: YYYY-MM-DD format

DOCUMENT:
{doc_text[:8000]}

Return ONLY this JSON:
{{
  "document_type": "{doc_type}",
  "overall_confidence": "high|medium|low",
  "header": {{}},
  "line_items": []
}}
"""
    return prompt


def _run_extraction_sync(job_id, file_paths, schema_path, db_url, template_data, project_dir, backend_dir, engine_dir):
    import os, traceback
    os.environ["PYTHONUTF8"] = "1"
    for p in [engine_dir, backend_dir, project_dir]:
        if p not in sys.path:
            sys.path.insert(0, p)

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

        successful = failed = needs_review = 0
        start_time = time.time()

        for fp in file_paths:
            try:
                file_path = Path(fp)
                if template_data:
                    results = _extract_with_template(orchestrator, file_path, template_data)
                else:
                    result = orchestrator._process_single_document(file_path)
                    results = [result]

                for result in results:
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
        print(f"[THREAD] done: {successful} ok, {failed} failed", flush=True)

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


def _extract_with_template(orchestrator, file_path: Path, template_data: dict):
    """Extract using template — supports both layout mode and legacy column mode."""
    import time as t
    from core.preprocessor import preprocess_file

    doc_type = template_data.get("doc_type", "document")
    start = t.time()
    results = []

    try:
        doc = preprocess_file(file_path)
        doc_text = doc.extracted_text or ""
        use_vision = doc.needs_vision and bool(doc.page_images_b64)

        mode = template_data.get("mode", "columns")

        if mode == "layout":
            prompt = _build_layout_prompt(template_data, doc_text)
        else:
            prompt = _build_columns_prompt(template_data, doc_text)

        if use_vision:
            extraction = orchestrator.llm.extract(image_b64=doc.page_images_b64[0], prompt=prompt)
        else:
            extraction = orchestrator.llm.extract(text=doc_text, prompt=prompt)

        elapsed = (t.time() - start) * 1000

        if not extraction.success or not extraction.parsed_json:
            from orchestrator import DocumentExtractionResult
            r = DocumentExtractionResult(filename=file_path.name)
            r.error = f"Extraction failed: {extraction.error}"
            r.processing_time_ms = elapsed
            return [r]

        raw = extraction.parsed_json
        confidence = raw.get("overall_confidence", "medium")

        if mode == "layout":
            results = _process_layout_result(raw, template_data, file_path.name, doc_type, confidence, elapsed, extraction)
        else:
            results = _process_columns_result(raw, template_data, file_path.name, doc_type, confidence, elapsed, extraction)

    except Exception as e:
        import traceback
        print(f"[THREAD] extraction error {file_path.name}: {e}", flush=True)
        traceback.print_exc()
        from orchestrator import DocumentExtractionResult
        r = DocumentExtractionResult(filename=file_path.name)
        r.error = str(e)
        r.processing_time_ms = (t.time() - start) * 1000
        results = [r]

    return results if results else [_fail(file_path.name, "No data extracted")]


def _process_layout_result(raw, template_data, filename, doc_type, confidence, elapsed, extraction):
    """Process layout-mode extraction result."""
    from orchestrator import DocumentExtractionResult

    layout = template_data["layout"]
    extracted_fields = raw.get("extracted_fields", {})
    repeat_rows_data = raw.get("repeat_rows", [])
    cells = layout.get("cells", {})
    repeat_rows = layout.get("repeatRows", [])

    # Build flat extracted_data by merging template cells + AI-filled values
    def build_row_data(repeat_item=None):
        row_data = {}
        for key, cell in cells.items():
            if not isinstance(cell, dict):
                continue
            val = cell.get("value", "")
            is_extract = cell.get("extractTarget", False)
            is_repeat = cell.get("repeatRow", False)
            r, c = key.split(",")
            parts = key.split(",")
            cr, cc = int(parts[0]), int(parts[1])
            col_letter = ""
            n = cc
            while True:
                col_letter = chr(65 + (n % 26)) + col_letter
                n = n // 26 - 1
                if n < 0:
                    break
            cell_ref = f"{col_letter}{cr+1}"

            if is_repeat and repeat_item is not None:
                filled = repeat_item.get(cell_ref, "")
                label = val or cell_ref
                row_data[label] = {"value": filled, "confidence": "high"}
            elif is_extract and not is_repeat:
                filled = extracted_fields.get(cell_ref, "")
                label = val or cell_ref
                row_data[label] = {"value": filled, "confidence": "high"}
            elif val and not is_extract:
                # Static label cell
                row_data[f"_label_{cell_ref}"] = {"value": val, "confidence": "high"}

        return row_data

    results = []
    if repeat_rows and repeat_rows_data:
        # Create one result per line item
        for i, repeat_item in enumerate(repeat_rows_data):
            r = DocumentExtractionResult(filename=filename)
            r.document_type = doc_type
            r.extracted_data = {
                "document_type": doc_type,
                "overall_confidence": confidence,
                "extracted_data": build_row_data(repeat_item),
                "layout_mode": True,
                "line_item_index": i,
            }
            r.extraction_response = extraction
            r.processing_time_ms = elapsed / max(len(repeat_rows_data), 1)
            r.success = True
            results.append(r)
    else:
        # Single result
        r = DocumentExtractionResult(filename=filename)
        r.document_type = doc_type
        r.extracted_data = {
            "document_type": doc_type,
            "overall_confidence": confidence,
            "extracted_data": build_row_data(),
            "layout_mode": True,
        }
        r.extraction_response = extraction
        r.processing_time_ms = elapsed
        r.success = True
        results.append(r)

    print(f"[THREAD] layout mode: {len(results)} result(s) for {filename}", flush=True)
    return results


def _process_columns_result(raw, template_data, filename, doc_type, confidence, elapsed, extraction):
    """Process legacy column-list extraction result."""
    from orchestrator import DocumentExtractionResult

    header_data = raw.get("header", raw.get("extracted_data", {}))
    line_items = raw.get("line_items", [])
    header_cols = template_data.get("header_cols", [])
    lineitem_cols = template_data.get("lineitem_cols", [])

    def normalize(cols, data):
        out = {}
        for col in cols:
            name = col.get("name", "").strip()
            if not name:
                continue
            fd = data.get(name)
            if fd is None:
                out[name] = {"value": "", "confidence": "high"}
            elif isinstance(fd, dict):
                v = fd.get("value")
                out[name] = {"value": "" if v is None else v, "confidence": fd.get("confidence", "high")}
            else:
                out[name] = {"value": "" if fd is None else fd, "confidence": "high"}
        return out

    norm_header = normalize(header_cols, header_data)
    results = []

    if line_items and lineitem_cols:
        for li_idx, li_row in enumerate(line_items):
            r = DocumentExtractionResult(filename=filename)
            r.document_type = doc_type
            row_data = dict(norm_header)
            for col in lineitem_cols:
                name = col.get("name", "").strip()
                if not name:
                    continue
                v = li_row.get(name)
                row_data[name] = {"value": "" if v is None else v, "confidence": "high"}
            r.extracted_data = {"document_type": doc_type, "overall_confidence": confidence, "extracted_data": row_data, "line_item_index": li_idx}
            r.extraction_response = extraction
            r.processing_time_ms = elapsed / len(line_items)
            r.success = True
            results.append(r)
    else:
        r = DocumentExtractionResult(filename=filename)
        r.document_type = doc_type
        r.extracted_data = {"document_type": doc_type, "overall_confidence": confidence, "extracted_data": norm_header}
        r.extraction_response = extraction
        r.processing_time_ms = elapsed
        r.success = True
        results.append(r)

    print(f"[THREAD] columns mode: {len(results)} result(s) for {filename}", flush=True)
    return results


def _fail(filename, error):
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
def get_job(job_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return _get_job_or_404(job_id, current_user, db)


@router.get("/jobs/{job_id}/results", response_model=list[DocumentResultResponse])
def get_job_results(job_id: int, doc_type: Optional[str] = None, needs_review: Optional[bool] = None,
                    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
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
    doc.needs_review = False
    db.commit()
    return {"message": "Updated", "doc_id": doc_id}


@router.post("/jobs/{job_id}/docs/{doc_id}/approve")
def approve_document(job_id: int, doc_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _get_job_or_404(job_id, current_user, db)
    doc = db.query(DocumentResult).filter(DocumentResult.id == doc_id, DocumentResult.job_id == job_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    doc.reviewed = True
    doc.reviewed_by = current_user.username
    doc.needs_review = False
    db.commit()
    return {"message": "Approved", "doc_id": doc_id}


@router.delete("/jobs/{job_id}")
def cancel_job(job_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    job = _get_job_or_404(job_id, current_user, db)
    if job.status not in ("pending", "processing"):
        raise HTTPException(status_code=400, detail=f"Cannot cancel job with status '{job.status}'")
    job.status = "cancelled"
    job.completed_at = datetime.utcnow()
    db.commit()
    return {"message": "Cancelled", "job_id": job_id}


def _get_job_or_404(job_id: int, current_user, db) -> ExtractionJob:
    job = db.query(ExtractionJob).filter(ExtractionJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if current_user.role != "admin" and job.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    return job
