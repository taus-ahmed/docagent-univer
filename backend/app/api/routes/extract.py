"""
DocAgent v2 — Extract Routes (Layout-aware template extraction)
Fix 1:
  - _parse_template reads from description field first, falls back to columns_json
  - Repeat row logic removed completely
  - When no extractTargets marked, AI fills all empty cells adjacent to labels intelligently
  - Multi-document detection: pre-pass detects document boundaries, one DocumentResult per doc
  - LLM routing unchanged (Gemini primary, Groq fallback via orchestrator)
Fix 2:
  - GET /api/jobs/{job_id}/export — streams an .xlsx file
  - Reconstructs template grid from ColumnTemplate.description (SheetSaveData)
  - One filled table block per DocumentResult, stacked vertically, one blank row between blocks
  - Applies cell styles (bold, italic, font size, colors, borders, merges, column widths)
"""

import io
import sys
import time
import json
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
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


# ─── Upload & Kick-off ────────────────────────────────────────────────────────

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


# ─── Template Parsing ─────────────────────────────────────────────────────────

def _parse_template(tpl: ColumnTemplate) -> Optional[dict]:
    """
    Parse a ColumnTemplate into extraction-ready format.

    Priority order:
      1. description field — contains full SheetSaveData JSON (cells, colWidths,
         merges, extractTargets, repeatRows) saved by the frontend TemplateEditor.
      2. columns_json — legacy flat column list fallback.
    """

    # ── 1. Try description field first (new layout format) ──────────────────
    if tpl.description:
        try:
            raw = json.loads(tpl.description)
            # SheetSaveData shape: { cells, colWidths, merges, extractTargets, repeatRows, ... }
            if isinstance(raw, dict) and "cells" in raw:
                return {
                    "mode": "layout",
                    "layout": raw,
                    "doc_type": tpl.document_type,
                    "name": tpl.name,
                }
        except Exception as e:
            print(f"[TEMPLATE] description parse error: {e}", flush=True)

    # ── 2. Try columns_json (legacy + transitional formats) ─────────────────
    if not tpl.columns_json:
        return None

    try:
        raw = json.loads(tpl.columns_json)

        # Transitional: full layout accidentally stored in columns_json
        if isinstance(raw, dict) and "extractTargets" in raw:
            return {
                "mode": "layout",
                "layout": raw,
                "doc_type": tpl.document_type,
                "name": tpl.name,
            }

        # Legacy: flat column list
        header_cols = []
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
            header_cols.append(col)

        return {
            "mode": "columns",
            "header_cols": header_cols,
            "lineitem_cols": [],
            "doc_type": tpl.document_type,
            "name": tpl.name,
        }

    except Exception as e:
        print(f"[TEMPLATE] columns_json parse error: {e}", flush=True)
        return None


# ─── Cell-ref helpers ─────────────────────────────────────────────────────────

def _cell_ref(r: int, c: int) -> str:
    """Convert 0-based (row, col) to Excel cell ref like A1, B3."""
    col_letter = ""
    n = c
    while True:
        col_letter = chr(65 + (n % 26)) + col_letter
        n = n // 26 - 1
        if n < 0:
            break
    return f"{col_letter}{r + 1}"


# ─── Layout Prompt Builder ────────────────────────────────────────────────────

def _build_layout_prompt(template_data: dict, doc_text: str, doc_index: int = 0, total_docs: int = 1) -> str:
    """
    Build a prompt for layout-aware single-document extraction.

    Two sub-modes:
      a) extractTargets present  → AI fills only those marked cells.
      b) no extractTargets       → AI fills ALL empty cells adjacent/paired to label cells.

    Repeat row logic has been removed. Every document gets exactly one
    filled copy of the template.
    """
    layout = template_data["layout"]
    doc_type = template_data.get("doc_type", "document")

    cells = layout.get("cells", {})
    extract_targets = layout.get("extractTargets", [])

    has_explicit_targets = bool(extract_targets)

    # ── Build human-readable grid description ────────────────────────────────
    max_r, max_c = 0, 0
    for key in cells:
        parts = key.split(",")
        if len(parts) == 2:
            r, c = int(parts[0]), int(parts[1])
            max_r = max(max_r, r)
            max_c = max(max_c, c)

    grid_lines = []
    empty_cells_near_labels = []  # for auto-fill mode

    for r in range(min(max_r + 1, 30)):
        row_cells = []
        for c in range(min(max_c + 1, 26)):
            k = f"{r},{c}"
            cell = cells.get(k, {})
            val = cell.get("value", "").strip() if isinstance(cell, dict) else ""
            is_extract = cell.get("extractTarget", False) if isinstance(cell, dict) else False

            cell_ref = _cell_ref(r, c)

            if has_explicit_targets:
                # Show label cells as static, extract targets as [EXTRACT: label]
                if is_extract:
                    row_cells.append(f"{cell_ref}=[EXTRACT: {val or 'value'}]")
                elif val:
                    row_cells.append(f"{cell_ref}=\"{val}\"")
            else:
                # Auto-fill mode: show all cells, mark empty ones for filling
                if val:
                    row_cells.append(f"{cell_ref}=\"{val}\"")
                else:
                    # Check if there's a label nearby (same row prev col, or row above same col)
                    left_key = f"{r},{c - 1}" if c > 0 else None
                    above_key = f"{r - 1},{c}" if r > 0 else None
                    left_val = (cells.get(left_key) or {}).get("value", "").strip() if left_key else ""
                    above_val = (cells.get(above_key) or {}).get("value", "").strip() if above_key else ""

                    if left_val or above_val:
                        context = left_val or above_val
                        row_cells.append(f"{cell_ref}=[FILL: near \"{context}\"]")
                        empty_cells_near_labels.append({"ref": cell_ref, "context": context})

        if row_cells:
            grid_lines.append(f"  Row {r + 1}: {' | '.join(row_cells)}")

    grid_description = "\n".join(grid_lines) if grid_lines else "  (empty template)"

    # ── Build the cells-to-fill list ─────────────────────────────────────────
    if has_explicit_targets:
        fill_list = "\n".join(
            f"  - {_cell_ref(t['r'], t['c'])}: \"{t['label']}\""
            for t in extract_targets
        )
        fill_instruction = f"CELLS TO FILL (explicitly marked):\n{fill_list}"
        fill_rule = (
            "Fill ONLY the cells marked [EXTRACT] above. "
            "For each, find the matching value in the document content."
        )
    else:
        if empty_cells_near_labels:
            fill_list = "\n".join(
                f"  - {e['ref']}: (next to \"{e['context']}\")"
                for e in empty_cells_near_labels
            )
            fill_instruction = f"CELLS TO FILL (auto-detected empty cells next to labels):\n{fill_list}"
        else:
            fill_instruction = (
                "CELLS TO FILL: No explicit targets and no empty cells detected adjacent to labels. "
                "Use your best judgment to identify and fill any value-bearing empty cells."
            )
        fill_rule = (
            "The user did not mark explicit extraction targets. "
            "Intelligently fill every empty cell that is contextually paired with a label "
            "(to its left, above it, or part of the same logical field). "
            "Match field names semantically, not just by position."
        )

    # ── Multi-document context note ──────────────────────────────────────────
    doc_context = ""
    if total_docs > 1:
        doc_context = (
            f"\nDOCUMENT CONTEXT: You are extracting document {doc_index + 1} of {total_docs} "
            f"found in this file. Extract ONLY data belonging to this document segment.\n"
        )

    prompt = f"""You are an expert {doc_type} data extraction agent. Your job is to fill in a template with data extracted from a document.
{doc_context}
TEMPLATE LAYOUT:
The user has designed this template. Labels are static text. Empty cells need to be filled with data from the document.

{grid_description}

{fill_instruction}

EXTRACTION RULES:
1. {fill_rule}
2. Missing or not-found fields → use empty string ""
3. Numbers: strip currency symbols, remove commas (e.g. "$1,250.00" → "1250.00")
4. Dates: normalize to YYYY-MM-DD format
5. Do not invent data not present in the document
6. Each document gets exactly ONE filled copy of the template — no row expansion

DOCUMENT CONTENT:
{doc_text[:8000]}

Return ONLY this JSON (no markdown, no explanation):
{{
  "document_type": "{doc_type}",
  "overall_confidence": "high|medium|low",
  "extracted_fields": {{
    "CELL_REF": "value"
  }},
  "metadata": {{
    "notes": ""
  }}
}}

Replace CELL_REF with the actual cell reference (e.g. "B2", "A5").
Extract the data now:"""

    return prompt


# ─── Multi-document Detection ─────────────────────────────────────────────────

def _detect_document_boundaries(orchestrator, doc_text: str, filename: str) -> list[dict]:
    """
    Pre-pass: ask the LLM whether this file contains multiple documents.
    Returns a list of segment dicts: [{"index": 0, "text": "...", "hint": "page 1"}]

    If detection fails or returns 1 document, returns a single segment with full text.
    Falls back gracefully on any error.
    """
    if not doc_text or len(doc_text) < 200:
        return [{"index": 0, "text": doc_text, "hint": "full document"}]

    detection_prompt = f"""You are a document analysis agent. Examine the text below and determine if it contains multiple separate documents (e.g. multiple cheques, invoices, receipts, or statements on separate pages or clearly separated sections).

Return ONLY this JSON (no markdown, no explanation):
{{
  "document_count": <integer>,
  "documents": [
    {{
      "index": 0,
      "hint": "brief description e.g. cheque 1 / page 1",
      "start_marker": "first ~20 chars of this document's text",
      "end_marker": "last ~20 chars of this document's text"
    }}
  ]
}}

If there is only one document, return document_count: 1 with a single entry covering the full text.
Do not split unless there are clear document boundaries.

TEXT TO ANALYSE (first 6000 chars):
{doc_text[:6000]}"""

    try:
        detection = orchestrator.llm.extract(text=doc_text[:6000], prompt=detection_prompt)

        if not detection.success or not detection.parsed_json:
            print(f"[DETECT] Detection failed for {filename}, treating as single doc", flush=True)
            return [{"index": 0, "text": doc_text, "hint": "full document"}]

        raw = detection.parsed_json
        doc_count = raw.get("document_count", 1)

        if doc_count <= 1 or not raw.get("documents"):
            return [{"index": 0, "text": doc_text, "hint": "full document"}]

        print(f"[DETECT] {filename}: {doc_count} documents detected", flush=True)

        # Split text by start_markers
        segments = []
        doc_list = raw["documents"]
        full_text = doc_text

        for i, doc_meta in enumerate(doc_list):
            start_marker = doc_meta.get("start_marker", "").strip()
            end_marker = doc_meta.get("end_marker", "").strip()
            hint = doc_meta.get("hint", f"document {i + 1}")

            # Find segment boundaries in full text
            start_pos = full_text.find(start_marker) if start_marker else -1
            end_pos = full_text.find(end_marker) if end_marker else -1

            if start_pos == -1:
                # Can't locate start — fall back to equal text splits
                chunk_size = len(full_text) // doc_count
                start_pos = i * chunk_size
                end_pos = start_pos + chunk_size if i < doc_count - 1 else len(full_text)
            elif end_pos == -1 or end_pos <= start_pos:
                # Can't locate end — go to next start or end of text
                if i + 1 < len(doc_list):
                    next_start_marker = doc_list[i + 1].get("start_marker", "").strip()
                    next_start = full_text.find(next_start_marker, start_pos + 1) if next_start_marker else -1
                    end_pos = next_start if next_start > start_pos else len(full_text)
                else:
                    end_pos = len(full_text)
            else:
                end_pos = end_pos + len(end_marker)

            segment_text = full_text[start_pos:end_pos].strip()
            if segment_text:
                segments.append({
                    "index": i,
                    "text": segment_text,
                    "hint": hint,
                })

        return segments if segments else [{"index": 0, "text": doc_text, "hint": "full document"}]

    except Exception as e:
        print(f"[DETECT] Exception during detection for {filename}: {e}", flush=True)
        return [{"index": 0, "text": doc_text, "hint": "full document"}]


# ─── Columns Prompt Builder (legacy) ──────────────────────────────────────────

def _build_columns_prompt(template_data: dict, doc_text: str) -> str:
    """Legacy column-list based prompt."""
    header_cols = template_data.get("header_cols", [])
    doc_type = template_data.get("doc_type", "document")

    def col_hint(col):
        return {
            "Number": "number only",
            "Currency": "number only, no symbols",
            "Date": "YYYY-MM-DD",
            "Text": "text",
        }.get(col.get("type", "Text"), "text")

    header_lines = "\n".join(
        f'  - "{c["name"]}": {col_hint(c)}'
        for c in sorted(header_cols, key=lambda x: x.get("order", 0))
        if c.get("name", "").strip()
    )

    prompt = f"""You are an expert {doc_type} data extraction agent.

HEADER FIELDS (extract once per document):
{header_lines}

RULES:
1. Missing fields → "" (never null or N/A)
2. Numbers: strip currency symbols and commas
3. Dates: YYYY-MM-DD format

DOCUMENT:
{doc_text[:8000]}

Return ONLY this JSON:
{{
  "document_type": "{doc_type}",
  "overall_confidence": "high|medium|low",
  "header": {{}}
}}
"""
    return prompt


# ─── Background Thread ────────────────────────────────────────────────────────

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


# ─── Template-mode Extraction ─────────────────────────────────────────────────

def _extract_with_template(orchestrator, file_path: Path, template_data: dict):
    """
    Extract using template — layout mode or legacy columns mode.

    Layout mode:
      1. Pre-pass: detect how many documents are in the file.
      2. For each detected document segment, run one extraction pass.
      3. Return one DocumentResult per document found.

    Columns mode:
      Single-pass extraction, one DocumentResult per file.
    """
    import time as t
    from core.preprocessor import preprocess_file

    doc_type = template_data.get("doc_type", "document")
    start = t.time()
    results = []
    mode = template_data.get("mode", "columns")

    try:
        doc = preprocess_file(file_path)
        doc_text = doc.extracted_text or ""
        use_vision = doc.needs_vision and bool(doc.page_images_b64)

        if mode == "layout":
            # ── Multi-document pre-pass ──────────────────────────────────────
            segments = _detect_document_boundaries(orchestrator, doc_text, file_path.name)
            total_docs = len(segments)
            print(f"[EXTRACT] {file_path.name}: {total_docs} segment(s) to process", flush=True)

            for segment in segments:
                seg_text = segment["text"]
                seg_index = segment["index"]
                seg_hint = segment.get("hint", f"document {seg_index + 1}")

                prompt = _build_layout_prompt(template_data, seg_text, seg_index, total_docs)

                if use_vision and seg_index == 0:
                    # Vision only available for first page / full doc
                    extraction = orchestrator.llm.extract(image_b64=doc.page_images_b64[0], prompt=prompt)
                else:
                    extraction = orchestrator.llm.extract(text=seg_text, prompt=prompt)

                elapsed = (t.time() - start) * 1000

                if not extraction.success or not extraction.parsed_json:
                    r = _fail(
                        file_path.name if total_docs == 1 else f"{file_path.stem}_doc{seg_index + 1}{file_path.suffix}",
                        f"Extraction failed: {extraction.error}"
                    )
                    r.processing_time_ms = elapsed
                    results.append(r)
                    continue

                raw = extraction.parsed_json
                confidence = raw.get("overall_confidence", "medium")

                seg_filename = (
                    file_path.name if total_docs == 1
                    else f"{file_path.stem}_doc{seg_index + 1}{file_path.suffix}"
                )

                result = _process_layout_result(
                    raw, template_data, seg_filename, doc_type,
                    confidence, elapsed, extraction, seg_hint
                )
                results.append(result)

        else:
            # ── Legacy columns mode (single pass) ────────────────────────────
            prompt = _build_columns_prompt(template_data, doc_text)

            if use_vision:
                extraction = orchestrator.llm.extract(image_b64=doc.page_images_b64[0], prompt=prompt)
            else:
                extraction = orchestrator.llm.extract(text=doc_text, prompt=prompt)

            elapsed = (t.time() - start) * 1000

            if not extraction.success or not extraction.parsed_json:
                r = _fail(file_path.name, f"Extraction failed: {extraction.error}")
                r.processing_time_ms = elapsed
                results.append(r)
            else:
                raw = extraction.parsed_json
                confidence = raw.get("overall_confidence", "medium")
                results.append(
                    _process_columns_result(raw, template_data, file_path.name, doc_type, confidence, elapsed, extraction)
                )

    except Exception as e:
        import traceback
        print(f"[EXTRACT] error {file_path.name}: {e}", flush=True)
        traceback.print_exc()
        r = _fail(file_path.name, str(e))
        r.processing_time_ms = (t.time() - start) * 1000
        results.append(r)

    return results if results else [_fail(file_path.name, "No data extracted")]


# ─── Result Processors ────────────────────────────────────────────────────────

def _process_layout_result(raw, template_data, filename, doc_type, confidence, elapsed, extraction, seg_hint=""):
    """
    Process layout-mode extraction result.
    One DocumentResult per call — no repeat row expansion.
    Maps AI-returned cell refs back to label-keyed extracted_data dict.
    """
    from orchestrator import DocumentExtractionResult

    layout = template_data["layout"]
    extracted_fields = raw.get("extracted_fields", {})
    cells = layout.get("cells", {})

    # Build label → value map from cell refs
    # First build a ref → label mapping from the template cells
    ref_to_label = {}
    for key, cell in cells.items():
        if not isinstance(cell, dict):
            continue
        val = cell.get("value", "").strip()
        is_extract = cell.get("extractTarget", False)
        if is_extract and val:
            parts = key.split(",")
            if len(parts) == 2:
                cr, cc = int(parts[0]), int(parts[1])
                ref = _cell_ref(cr, cc)
                ref_to_label[ref] = val

    # Also handle auto-fill mode: map any cell ref the AI returned to its label
    # by looking up adjacent label cells
    for ref, filled_val in extracted_fields.items():
        if ref not in ref_to_label:
            # Try to find the label for this cell from context
            # Parse ref back to r, c
            try:
                col_str = "".join(ch for ch in ref if ch.isalpha()).upper()
                row_str = "".join(ch for ch in ref if ch.isdigit())
                c_idx = 0
                for ch in col_str:
                    c_idx = c_idx * 26 + (ord(ch) - 64)
                c_idx -= 1
                r_idx = int(row_str) - 1
                # Check left cell for label
                left_key = f"{r_idx},{c_idx - 1}" if c_idx > 0 else None
                above_key = f"{r_idx - 1},{c_idx}" if r_idx > 0 else None
                left_val = (cells.get(left_key) or {}).get("value", "").strip() if left_key else ""
                above_val = (cells.get(above_key) or {}).get("value", "").strip() if above_key else ""
                label = left_val or above_val or ref
                ref_to_label[ref] = label
            except Exception:
                ref_to_label[ref] = ref

    # Build extracted_data: label → {value, confidence}
    extracted_data = {}
    for ref, label in ref_to_label.items():
        filled = extracted_fields.get(ref, "")
        extracted_data[label] = {"value": filled, "confidence": "high"}

    # Add static label cells so Excel export can reconstruct the full template
    for key, cell in cells.items():
        if not isinstance(cell, dict):
            continue
        val = cell.get("value", "").strip()
        is_extract = cell.get("extractTarget", False)
        if val and not is_extract:
            parts = key.split(",")
            if len(parts) == 2:
                cr, cc = int(parts[0]), int(parts[1])
                ref = _cell_ref(cr, cc)
                extracted_data[f"_label_{ref}"] = {"value": val, "confidence": "high"}

    r = DocumentExtractionResult(filename=filename)
    r.document_type = doc_type
    r.extracted_data = {
        "document_type": doc_type,
        "overall_confidence": confidence,
        "extracted_data": extracted_data,
        "extracted_fields": extracted_fields,   # raw cell-ref map for Excel export
        "layout_mode": True,
        "segment_hint": seg_hint,
    }
    r.extraction_response = extraction
    r.processing_time_ms = elapsed
    r.success = True

    print(f"[EXTRACT] layout result: {filename} ({seg_hint}), {len(extracted_fields)} fields", flush=True)
    return r


def _process_columns_result(raw, template_data, filename, doc_type, confidence, elapsed, extraction):
    """Process legacy column-list extraction result."""
    from orchestrator import DocumentExtractionResult

    header_data = raw.get("header", raw.get("extracted_data", {}))
    header_cols = template_data.get("header_cols", [])

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

    r = DocumentExtractionResult(filename=filename)
    r.document_type = doc_type
    r.extracted_data = {
        "document_type": doc_type,
        "overall_confidence": confidence,
        "extracted_data": norm_header,
    }
    r.extraction_response = extraction
    r.processing_time_ms = elapsed
    r.success = True

    print(f"[EXTRACT] columns result: {filename}, {len(norm_header)} fields", flush=True)
    return r


def _fail(filename, error):
    from orchestrator import DocumentExtractionResult
    r = DocumentExtractionResult(filename=filename)
    r.error = error
    r.processing_time_ms = 0
    return r


# ─── Job Routes ───────────────────────────────────────────────────────────────

@router.get("/jobs", response_model=list[JobListItem])
def list_jobs(
    limit: int = 50,
    offset: int = 0,
    status_filter: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(ExtractionJob).order_by(ExtractionJob.created_at.desc())
    if current_user.role != "admin":
        q = q.filter(ExtractionJob.user_id == current_user.id)
    if status_filter:
        q = q.filter(ExtractionJob.status == status_filter)
    return q.offset(offset).limit(limit).all()


@router.get("/jobs/{job_id}", response_model=JobStatus)
def get_job(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _get_job_or_404(job_id, current_user, db)


@router.get("/jobs/{job_id}/results", response_model=list[DocumentResultResponse])
def get_job_results(
    job_id: int,
    doc_type: Optional[str] = None,
    needs_review: Optional[bool] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_job_or_404(job_id, current_user, db)
    q = db.query(DocumentResult).filter(DocumentResult.job_id == job_id)
    if doc_type:
        q = q.filter(DocumentResult.document_type == doc_type)
    if needs_review is not None:
        q = q.filter(DocumentResult.needs_review == needs_review)
    docs = q.order_by(DocumentResult.id).all()
    return [
        DocumentResultResponse(
            id=d.id, job_id=d.job_id, filename=d.filename,
            document_type=d.document_type, overall_confidence=d.overall_confidence,
            extracted_data=d.get_extracted_data(),
            validation_errors=d.validation_errors, validation_warnings=d.validation_warnings,
            needs_review=d.needs_review, reviewed=d.reviewed, reviewed_by=d.reviewed_by,
            model_used=d.model_used, tokens_used=d.tokens_used or 0,
            latency_ms=d.latency_ms or 0, created_at=d.created_at,
        )
        for d in docs
    ]


@router.put("/jobs/{job_id}/docs/{doc_id}")
def update_document(
    job_id: int,
    doc_id: int,
    payload: DocumentUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_job_or_404(job_id, current_user, db)
    doc = db.query(DocumentResult).filter(
        DocumentResult.id == doc_id, DocumentResult.job_id == job_id
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    doc.set_extracted_data(payload.extracted_data)
    doc.reviewed = True
    doc.reviewed_by = current_user.username
    doc.needs_review = False
    db.commit()
    return {"message": "Updated", "doc_id": doc_id}


@router.post("/jobs/{job_id}/docs/{doc_id}/approve")
def approve_document(
    job_id: int,
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_job_or_404(job_id, current_user, db)
    doc = db.query(DocumentResult).filter(
        DocumentResult.id == doc_id, DocumentResult.job_id == job_id
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    doc.reviewed = True
    doc.reviewed_by = current_user.username
    doc.needs_review = False
    db.commit()
    return {"message": "Approved", "doc_id": doc_id}


@router.delete("/jobs/{job_id}")
def cancel_job(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = _get_job_or_404(job_id, current_user, db)
    if job.status not in ("pending", "processing"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel job with status '{job.status}'"
        )
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


# ─── Excel Export ─────────────────────────────────────────────────────────────

@router.get("/jobs/{job_id}/export")
def export_job_excel(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Export all DocumentResults for a job as a single .xlsx file.

    Layout:
      - One filled table block per document result, stacked vertically.
      - One blank row between blocks.
      - Each block reproduces the template grid exactly, with AI-extracted
        values filled into the appropriate cells.
      - Cell styles (bold, italic, font size, colors, borders, merges,
        column widths) are applied from the saved SheetSaveData.

    Requires the job to have been run with a template (schema_id must be set).
    Falls back to a flat key-value table if no template layout is available.
    """
    try:
        import openpyxl
        from openpyxl.styles import (
            Font, PatternFill, Alignment, Border, Side,
        )
        from openpyxl.utils import get_column_letter
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="openpyxl is not installed. Add it to requirements.txt and redeploy.",
        )

    job = _get_job_or_404(job_id, current_user, db)

    # Load all results ordered by id (insertion order = document order)
    doc_results = (
        db.query(DocumentResult)
        .filter(DocumentResult.job_id == job_id)
        .order_by(DocumentResult.id)
        .all()
    )
    if not doc_results:
        raise HTTPException(status_code=404, detail="No results found for this job.")

    # Try to load template layout from ColumnTemplate
    sheet_data = None
    if job.schema_id:
        try:
            tpl_id = int(job.schema_id)
            tpl = db.query(ColumnTemplate).filter(ColumnTemplate.id == tpl_id).first()
            if tpl and tpl.description:
                raw = json.loads(tpl.description)
                if isinstance(raw, dict) and "cells" in raw:
                    sheet_data = raw
        except Exception as e:
            print(f"[EXPORT] Template load error: {e}", flush=True)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Results"

    if sheet_data:
        _write_template_blocks(ws, doc_results, sheet_data, openpyxl)
    else:
        _write_flat_table(ws, doc_results, openpyxl)

    # Stream the workbook back
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    filename = f"job_{job_id}_results.xlsx"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
    return StreamingResponse(buf, headers=headers)


# ─── Excel helpers ────────────────────────────────────────────────────────────

def _col_letter(c: int) -> str:
    """0-based column index → Excel column letter (A, B, ... Z, AA, ...)."""
    letter = ""
    n = c
    while True:
        letter = chr(65 + (n % 26)) + letter
        n = n // 26 - 1
        if n < 0:
            break
    return letter


def _parse_hex_color(hex_color: Optional[str]) -> Optional[str]:
    """Normalise a CSS hex color (#rrggbb or #rgb) to openpyxl ARGB (FFRRGGBB)."""
    if not hex_color:
        return None
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    if len(h) == 6:
        return f"FF{h.upper()}"
    return None


def _apply_cell_style(xl_cell, style: dict, openpyxl_mod) -> None:
    """
    Apply a SheetSaveData CellStyle dict to an openpyxl cell.

    CellStyle fields: bold, italic, underline, strike, fontSize, fontFamily,
                      fontColor, bgColor, align, wrap, borderAll, borderOuter.
    """
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    # Font
    font_kwargs: dict = {}
    if style.get("bold"):
        font_kwargs["bold"] = True
    if style.get("italic"):
        font_kwargs["italic"] = True
    if style.get("underline"):
        font_kwargs["underline"] = "single"
    if style.get("strike"):
        font_kwargs["strike"] = True
    if style.get("fontSize"):
        font_kwargs["size"] = style["fontSize"]
    if style.get("fontFamily"):
        font_kwargs["name"] = style["fontFamily"]
    fc = _parse_hex_color(style.get("fontColor"))
    if fc:
        font_kwargs["color"] = fc
    if font_kwargs:
        xl_cell.font = Font(**font_kwargs)

    # Fill
    bg = _parse_hex_color(style.get("bgColor"))
    if bg:
        xl_cell.fill = PatternFill(fill_type="solid", fgColor=bg)

    # Alignment
    align_map = {"left": "left", "center": "center", "right": "right"}
    h_align = align_map.get(style.get("align", ""), "left")
    xl_cell.alignment = Alignment(
        horizontal=h_align,
        wrap_text=bool(style.get("wrap")),
        vertical="center",
    )

    # Borders
    if style.get("borderAll"):
        thin = Side(style="thin")
        xl_cell.border = Border(left=thin, right=thin, top=thin, bottom=thin)
    elif style.get("borderOuter"):
        medium = Side(style="medium")
        xl_cell.border = Border(left=medium, right=medium, top=medium, bottom=medium)


def _find_template_dimensions(cells: dict) -> tuple[int, int]:
    """Return (max_row, max_col) used by the template, 0-based."""
    max_r, max_c = 0, 0
    for key in cells:
        parts = key.split(",")
        if len(parts) == 2:
            r, c = int(parts[0]), int(parts[1])
            max_r = max(max_r, r)
            max_c = max(max_c, c)
    return max_r, max_c


def _write_template_blocks(ws, doc_results, sheet_data: dict, openpyxl_mod) -> None:
    """
    Write one filled template block per DocumentResult, stacked vertically
    with one blank row between blocks.

    Each block:
      - Reproduces the full template grid (label cells + filled value cells).
      - Applies all cell styles from SheetSaveData.
      - Handles merged cells.
      - Sets column widths from SheetSaveData.colWidths (applied once, first block).
    """
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter

    cells_tpl = sheet_data.get("cells", {})
    merges_tpl = sheet_data.get("merges", {})
    col_widths = sheet_data.get("colWidths", [])

    max_r, max_c = _find_template_dimensions(cells_tpl)
    template_rows = max_r + 1   # number of rows in the template
    block_height = template_rows + 1  # +1 blank row between blocks

    # Apply column widths once (based on first block)
    for c_idx, width_px in enumerate(col_widths):
        if width_px and c_idx <= max_c:
            # openpyxl column width is in characters (~7px each)
            char_width = max(8, round(width_px / 7))
            ws.column_dimensions[get_column_letter(c_idx + 1)].width = char_width

    for block_idx, doc_result in enumerate(doc_results):
        row_offset = block_idx * block_height  # 0-based row offset in worksheet

        # Build cell-ref → extracted value map for this document
        extracted_data = doc_result.get_extracted_data()
        extracted_fields: dict = extracted_data.get("extracted_fields", {})
        # Also build label → value map for fallback lookup
        label_to_value: dict = {}
        for k, v in extracted_data.get("extracted_data", {}).items():
            if not k.startswith("_label_"):
                if isinstance(v, dict):
                    label_to_value[k] = v.get("value", "")
                else:
                    label_to_value[k] = str(v) if v is not None else ""

        # Write each cell in the template
        for key, cell_def in cells_tpl.items():
            if not isinstance(cell_def, dict):
                continue

            # Skip cells that are children of a merge (they have mergeParent)
            if cell_def.get("mergeParent"):
                continue

            parts = key.split(",")
            if len(parts) != 2:
                continue
            tr, tc = int(parts[0]), int(parts[1])

            # Worksheet row/col (1-based)
            ws_row = row_offset + tr + 1
            ws_col = tc + 1

            xl_cell = ws.cell(row=ws_row, column=ws_col)

            # Determine cell value
            tpl_value = cell_def.get("value", "").strip()
            is_extract = cell_def.get("extractTarget", False)

            if is_extract:
                # Look up by cell ref first (most reliable)
                ref = f"{_col_letter(tc)}{tr + 1}"
                filled = extracted_fields.get(ref)
                if filled is None:
                    # Fall back to label lookup
                    filled = label_to_value.get(tpl_value, "")
                xl_cell.value = filled if filled is not None else ""
            else:
                # Static label cell
                xl_cell.value = tpl_value

            # Apply style
            style = cell_def.get("style", {})
            if style:
                _apply_cell_style(xl_cell, style, openpyxl_mod)

            # Handle merge spans
            merge_span = cell_def.get("mergeSpan") or merges_tpl.get(key)
            if merge_span:
                span_rows = merge_span.get("rows", 1)
                span_cols = merge_span.get("cols", 1)
                if span_rows > 1 or span_cols > 1:
                    end_row = ws_row + span_rows - 1
                    end_col = ws_col + span_cols - 1
                    ws.merge_cells(
                        start_row=ws_row, start_column=ws_col,
                        end_row=end_row, end_column=end_col,
                    )

        # Add a small filename label above each block (row just before the block)
        if block_idx > 0:
            label_row = row_offset  # the blank separator row — put filename here
            label_cell = ws.cell(row=label_row, column=1)
            label_cell.value = f"▶  {doc_result.filename}"
            from openpyxl.styles import Font as XLFont
            label_cell.font = XLFont(bold=True, color="FF4F46E5", size=10)
        else:
            # First block: put filename in a row above row 1 if possible
            # Just annotate at column max_c+2 in row 1 to avoid disturbing layout
            note_cell = ws.cell(row=1, column=max_c + 3)
            note_cell.value = doc_result.filename
            from openpyxl.styles import Font as XLFont
            note_cell.font = XLFont(color="FF9CA3AF", size=9, italic=True)


def _write_flat_table(ws, doc_results, openpyxl_mod) -> None:
    """
    Fallback: no template available.
    Write a simple flat table — one header row, then one row per DocumentResult.
    Columns are the union of all extracted_data keys across all results.
    """
    from openpyxl.styles import Font, PatternFill, Alignment

    # Collect all unique field names across all results
    all_keys: list[str] = []
    seen: set[str] = set()
    for dr in doc_results:
        ed = dr.get_extracted_data()
        inner = ed.get("extracted_data", ed)
        for k in inner:
            if k not in seen and not k.startswith("_label_"):
                seen.add(k)
                all_keys.append(k)

    # Header row
    header_fill = PatternFill(fill_type="solid", fgColor="FF4F46E5")
    header_font = Font(bold=True, color="FFFFFFFF", size=11)
    ws.cell(row=1, column=1, value="Filename").font = header_font
    ws.cell(row=1, column=1).fill = header_fill
    for col_idx, key in enumerate(all_keys, start=2):
        c = ws.cell(row=1, column=col_idx, value=key)
        c.font = header_font
        c.fill = header_fill

    # Data rows
    for row_idx, dr in enumerate(doc_results, start=2):
        ws.cell(row=row_idx, column=1, value=dr.filename)
        ed = dr.get_extracted_data()
        inner = ed.get("extracted_data", ed)
        for col_idx, key in enumerate(all_keys, start=2):
            v = inner.get(key)
            if isinstance(v, dict):
                v = v.get("value", "")
            ws.cell(row=row_idx, column=col_idx, value=v if v is not None else "")

    # Auto-size columns roughly
    from openpyxl.utils import get_column_letter as _gcl
    ws.column_dimensions["A"].width = 30
    for col_idx in range(2, len(all_keys) + 2):
        ws.column_dimensions[_gcl(col_idx)].width = 20
