"""
DocAgent v2 — Extract Routes
=============================
Option 2 architecture: Template-Driven Routing with Per-Type System Prompts.

How it works:
  1. User selects a template (which carries a document_type).
  2. _parse_template() reads the SheetSaveData grid from ColumnTemplate.description.
  3. _detect_template_mode() decides: TABLE mode or FORM mode.
  4. The prompt registry supplies a domain-expert system prompt for the doc type.
  5. Extraction runs via the best available strategy:
       TABLE mode: pdfplumber direct extraction (fast, 100% accurate for digital PDFs)
                   → AI fallback with registry-enhanced prompt if direct fails
       FORM mode:  AI extraction with registry system prompt + template grid description
  6. Multi-document detection: single PDF containing N separate docs → N results.
  7. Auto-classification: if no template selected, hints + LLM classify then registry.
  8. Excel export: GET /api/jobs/{id}/export reconstructs the template layout exactly.

Adding a new document type:
  - Add an entry to prompt_registry.py — no changes needed here.
"""

import io
import re
import sys
import time
import json
import threading
import traceback
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
    if tpl.description:
        try:
            raw = json.loads(tpl.description)
            if isinstance(raw, dict) and "cells" in raw:
                return {
                    "mode": "layout",
                    "layout": raw,
                    "doc_type": tpl.document_type or "other",
                    "name": tpl.name,
                }
        except Exception as e:
            print(f"[TEMPLATE] description parse error: {e}", flush=True)

    if not tpl.columns_json:
        return None

    try:
        raw = json.loads(tpl.columns_json)
        if isinstance(raw, dict) and "extractTargets" in raw:
            return {
                "mode": "layout",
                "layout": raw,
                "doc_type": tpl.document_type or "other",
                "name": tpl.name,
            }

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
            "doc_type": tpl.document_type or "other",
            "name": tpl.name,
        }
    except Exception as e:
        print(f"[TEMPLATE] columns_json parse error: {e}", flush=True)
        return None


# ─── Registry Loader ──────────────────────────────────────────────────────────

def _load_registry():
    """Load prompt_registry.py once and cache it."""
    if not hasattr(_load_registry, "_cache"):
        try:
            import importlib.util
            # Look in same directory as extract.py
            reg_file = Path(__file__).resolve().parent / "prompt_registry.py"
            if reg_file.exists():
                spec = importlib.util.spec_from_file_location("prompt_registry", reg_file)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                _load_registry._cache = mod
                print(f"[REGISTRY] Loaded from {reg_file}", flush=True)
            else:
                _load_registry._cache = None
                print("[REGISTRY] Not found — using generic prompts", flush=True)
        except Exception as e:
            print(f"[REGISTRY] Load error: {e}", flush=True)
            _load_registry._cache = None
    return _load_registry._cache


def _get_system_prompt(doc_type: str) -> str:
    reg = _load_registry()
    if reg:
        return reg.get_system_prompt(doc_type)
    return f"You are an expert {doc_type} data extraction specialist."


def _get_table_rules(doc_type: str) -> str:
    reg = _load_registry()
    if reg:
        return reg.get_table_rules(doc_type) or ""
    return ""


def _get_numeric_fields(doc_type: str) -> list:
    reg = _load_registry()
    return reg.get_numeric_fields(doc_type) if reg else []


def _get_date_fields(doc_type: str) -> list:
    reg = _load_registry()
    return reg.get_date_fields(doc_type) if reg else []


def _classify_by_hints(text: str) -> Optional[str]:
    reg = _load_registry()
    return reg.classify_by_hints(text) if reg else None


# ─── Cell helpers ─────────────────────────────────────────────────────────────

def _cell_ref(r: int, c: int) -> str:
    col_letter = ""
    n = c
    while True:
        col_letter = chr(65 + (n % 26)) + col_letter
        n = n // 26 - 1
        if n < 0:
            break
    return f"{col_letter}{r + 1}"


def _col_letter(c: int) -> str:
    letter = ""
    n = c
    while True:
        letter = chr(65 + (n % 26)) + letter
        n = n // 26 - 1
        if n < 0:
            break
    return letter


# ─── Template Mode Detection ──────────────────────────────────────────────────

def _detect_template_mode(layout: dict) -> str:
    """
    Return 'table' or 'form'.
    table = header-only (single row, no extract targets, 2+ columns)
    form  = everything else
    """
    cells = layout.get("cells", {})
    if layout.get("extractTargets"):
        return "form"

    row_set, col_set = set(), set()
    for key, cell in cells.items():
        if not isinstance(cell, dict):
            continue
        val = cell.get("value", "").strip()
        if not val:
            continue
        parts = key.split(",")
        if len(parts) == 2:
            row_set.add(int(parts[0]))
            col_set.add(int(parts[1]))

    return "table" if row_set == {0} and len(col_set) >= 2 else "form"


def _get_table_headers(layout: dict) -> list:
    cells = layout.get("cells", {})
    headers = []
    for key, cell in cells.items():
        if not isinstance(cell, dict):
            continue
        val = cell.get("value", "").strip()
        if not val:
            continue
        parts = key.split(",")
        if len(parts) == 2 and int(parts[0]) == 0:
            c = int(parts[1])
            headers.append({"col": c, "label": val, "ref": _cell_ref(0, c), "style": cell.get("style", {})})
    return sorted(headers, key=lambda x: x["col"])


# ─── Direct PDF Table Extraction ─────────────────────────────────────────────

def _extract_pdf_table_direct(file_path: Path, template_data: dict) -> Optional[list]:
    """
    Primary table extraction strategy: read PDF table structure directly
    with pdfplumber. No AI needed. Handles both bordered and borderless tables.
    Returns list of row dicts or None if no table found.
    """
    try:
        import pdfplumber

        headers = _get_table_headers(template_data["layout"])
        col_names = [h["label"] for h in headers]
        if not col_names:
            return None

        skip_kw = {"subtotal", "total", "shipping", "tax", "discount",
                   "charges", "refund", "paid", "free", "balance", "grand total"}
        all_rows = []

        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                # Try line-based strategy first (tables with visible borders)
                tables = page.extract_tables({
                    "vertical_strategy": "lines",
                    "horizontal_strategy": "lines",
                    "snap_tolerance": 4,
                    "join_tolerance": 4,
                    "edge_min_length": 3,
                    "min_words_vertical": 1,
                    "min_words_horizontal": 1,
                })
                # Fallback: text-based (no visible borders)
                if not tables:
                    tables = page.extract_tables({
                        "vertical_strategy": "text",
                        "horizontal_strategy": "text",
                        "snap_tolerance": 6,
                        "join_tolerance": 6,
                    })

                for table in tables:
                    if not table or len(table) < 2:
                        continue
                    header_row_idx = _find_header_row(table, col_names)
                    if header_row_idx is None:
                        continue
                    pdf_headers = [_clean_cell(c) for c in table[header_row_idx]]
                    col_map = _match_columns(col_names, pdf_headers)
                    if not col_map:
                        continue

                    for row in table[header_row_idx + 1:]:
                        if not row or all(not _clean_cell(c) for c in row):
                            continue
                        first_val = _clean_cell(row[0]) if row else ""
                        if not first_val:
                            continue
                        if any(kw in first_val.lower() for kw in skip_kw):
                            continue
                        if re.match(r'^\d{1,4}$', first_val):
                            continue  # orphan digit — skip

                        row_dict = {}
                        for col_name in col_names:
                            pdf_idx = col_map.get(col_name)
                            if pdf_idx is not None and pdf_idx < len(row):
                                val = _clean_cell(row[pdf_idx])
                                val = re.sub(r'^\$', '', val).replace(',', '')
                            else:
                                val = ""
                            row_dict[col_name] = val

                        if any(v for v in row_dict.values()):
                            all_rows.append(row_dict)

        print(f"[DIRECT] {file_path.name}: {len(all_rows)} rows", flush=True)
        return all_rows if all_rows else None

    except Exception as e:
        print(f"[DIRECT] Failed {file_path.name}: {e}", flush=True)
        return None


def _clean_cell(val) -> str:
    if val is None:
        return ""
    return " ".join(str(val).strip().split())


def _find_header_row(table: list, col_names: list) -> Optional[int]:
    col_names_lower = [c.lower() for c in col_names]
    best_idx, best_score = None, 0
    for i, row in enumerate(table[:6]):
        if not row:
            continue
        row_vals = [_clean_cell(c).lower() for c in row]
        score = sum(
            1 for col in col_names_lower
            if any(col in cell or cell in col for cell in row_vals if cell)
        )
        if score > best_score:
            best_score = score
            best_idx = i
    return best_idx if best_score >= max(1, len(col_names) // 2) else None


def _match_columns(col_names: list, pdf_headers: list) -> dict:
    import difflib
    mapping = {}
    pdf_lower = [h.lower() for h in pdf_headers]
    for col in col_names:
        col_lower = col.lower()
        if col_lower in pdf_lower:
            mapping[col] = pdf_lower.index(col_lower)
            continue
        for i, h in enumerate(pdf_lower):
            if col_lower in h or h in col_lower:
                mapping[col] = i
                break
        else:
            matches = difflib.get_close_matches(col_lower, pdf_lower, n=1, cutoff=0.6)
            if matches:
                mapping[col] = pdf_lower.index(matches[0])
    return mapping


def _clean_text_for_table(text: str) -> str:
    """Clean pdfplumber text for AI fallback — reassemble split GTIN lines."""
    # Reassemble GTIN split across lines: 8+ digits + 1-3 digit continuation
    text = re.sub(r'(\d{8,})\n(\d{1,3})\n', lambda m: m.group(1) + m.group(2) + '\n', text)
    text = re.sub(r'(\d{8,})\n(\d{1,3})$', lambda m: m.group(1) + m.group(2), text)
    # Fix item names: "Item name -\n#123456" → "Item name - #123456"
    text = re.sub(r'(-\s*)\n(#\d+)', r'\1 \2', text)
    text = re.sub(r'(-\s*)\n(\d{6})\n', r'\1 #\2\n', text)
    return text


# ─── Prompt Builders ──────────────────────────────────────────────────────────

def _build_table_prompt(template_data: dict, doc_text: str) -> str:
    """AI fallback table extraction prompt with registry system prompt."""
    doc_type = template_data.get("doc_type", "other")
    headers = _get_table_headers(template_data["layout"])
    col_names = [h["label"] for h in headers]
    col_list = "\n".join(f"  - {h['label']}" for h in headers)
    example_row = {h["label"]: "extracted value" for h in headers}
    system_prompt = _get_system_prompt(doc_type)
    table_rules = _get_table_rules(doc_type) or ""

    return f"""{system_prompt}

━━━ TASK ━━━
Extract EVERY data row from the document into the table below.

COLUMN HEADERS:
{col_list}

{table_rules}

PDF ARTEFACT HANDLING:
- GTINs/barcodes split across lines: "790847112284" + next line "5" → "7908471122845"
- Rows containing ONLY 1-3 digits are artefacts — SKIP them
- Item names split across lines: join with a space
- Skip: header row, subtotal, total, tax, shipping, summary rows

━━━ DOCUMENT ━━━
{doc_text[:14000]}

Return ONLY this JSON (no markdown):
{{
  "document_type": "{doc_type}",
  "overall_confidence": "high|medium|low",
  "table_rows": [{json.dumps(example_row)}],
  "row_count": 0,
  "notes": ""
}}

Each object MUST have exactly these keys: {json.dumps(col_names)}
Extract all rows now:"""


def _build_form_prompt(template_data: dict, doc_text: str,
                       doc_index: int = 0, total_docs: int = 1) -> str:
    """Form extraction prompt with registry system prompt."""
    layout = template_data["layout"]
    doc_type = template_data.get("doc_type", "other")
    cells = layout.get("cells", {})
    extract_targets = layout.get("extractTargets", [])
    has_explicit_targets = bool(extract_targets)
    system_prompt = _get_system_prompt(doc_type)

    # Build grid description
    max_r, max_c = 0, 0
    for key in cells:
        parts = key.split(",")
        if len(parts) == 2:
            r, c = int(parts[0]), int(parts[1])
            max_r = max(max_r, r)
            max_c = max(max_c, c)

    grid_lines = []
    empty_cells_near_labels = []

    for r in range(min(max_r + 1, 30)):
        row_cells = []
        for c in range(min(max_c + 1, 26)):
            k = f"{r},{c}"
            cell = cells.get(k, {})
            val = cell.get("value", "").strip() if isinstance(cell, dict) else ""
            is_extract = cell.get("extractTarget", False) if isinstance(cell, dict) else False
            ref = _cell_ref(r, c)

            if has_explicit_targets:
                if is_extract:
                    row_cells.append(f"{ref}=[EXTRACT: {val or 'value'}]")
                elif val:
                    row_cells.append(f"{ref}=\"{val}\"")
            else:
                if val:
                    row_cells.append(f"{ref}=\"{val}\"")
                else:
                    left_key = f"{r},{c-1}" if c > 0 else None
                    above_key = f"{r-1},{c}" if r > 0 else None
                    left_val = (cells.get(left_key) or {}).get("value", "").strip() if left_key else ""
                    above_val = (cells.get(above_key) or {}).get("value", "").strip() if above_key else ""
                    if left_val or above_val:
                        context = left_val or above_val
                        row_cells.append(f"{ref}=[FILL: near \"{context}\"]")
                        empty_cells_near_labels.append({"ref": ref, "context": context})
        if row_cells:
            grid_lines.append(f"  Row {r+1}: {' | '.join(row_cells)}")

    grid_desc = "\n".join(grid_lines) if grid_lines else "  (empty template)"

    if has_explicit_targets:
        fill_list = "\n".join(f"  - {_cell_ref(t['r'], t['c'])}: \"{t['label']}\"" for t in extract_targets)
        fill_instruction = f"CELLS TO FILL (explicitly marked):\n{fill_list}"
        fill_rule = "Fill ONLY the [EXTRACT] cells. Find each value in the document."
    else:
        if empty_cells_near_labels:
            fill_list = "\n".join(f"  - {e['ref']}: (near \"{e['context']}\")" for e in empty_cells_near_labels)
            fill_instruction = f"CELLS TO FILL (auto-detected):\n{fill_list}"
        else:
            fill_instruction = "CELLS TO FILL: Fill any empty cell paired with a label."
        fill_rule = "Fill every empty cell that is semantically paired with a label."

    doc_ctx = ""
    if total_docs > 1:
        doc_ctx = f"\nDOCUMENT CONTEXT: Extracting document {doc_index+1} of {total_docs}.\n"

    return f"""{system_prompt}
{doc_ctx}
━━━ TEMPLATE ━━━
{grid_desc}

{fill_instruction}

RULES:
1. {fill_rule}
2. Missing → ""  (never "N/A" or invented values)
3. Numbers: strip currency symbols, remove commas
4. Dates: YYYY-MM-DD
5. One filled copy — no row expansion

━━━ DOCUMENT ━━━
{doc_text[:10000]}

Return ONLY this JSON (no markdown):
{{
  "document_type": "{doc_type}",
  "overall_confidence": "high|medium|low",
  "extracted_fields": {{"CELL_REF": "value"}},
  "notes": ""
}}
Extract now:"""


def _build_columns_prompt(template_data: dict, doc_text: str) -> str:
    """Legacy columns prompt with registry system prompt."""
    header_cols = template_data.get("header_cols", [])
    doc_type = template_data.get("doc_type", "other")
    system_prompt = _get_system_prompt(doc_type)

    def col_hint(col):
        return {"Number": "number only", "Currency": "number only, no symbols",
                "Date": "YYYY-MM-DD", "Text": "text"}.get(col.get("type", "Text"), "text")

    header_lines = "\n".join(
        f'  - "{c["name"]}": {col_hint(c)}'
        for c in sorted(header_cols, key=lambda x: x.get("order", 0))
        if c.get("name", "").strip()
    )

    return f"""{system_prompt}

━━━ FIELDS TO EXTRACT ━━━
{header_lines}

━━━ DOCUMENT ━━━
{doc_text[:10000]}

Return ONLY this JSON:
{{
  "document_type": "{doc_type}",
  "overall_confidence": "high|medium|low",
  "header": {{}}
}}"""


# ─── Value Normalisation ──────────────────────────────────────────────────────

def _normalise_values(row: dict, doc_type: str) -> dict:
    """Apply registry-driven normalisation: strip currency from numeric fields."""
    numeric_fields = _get_numeric_fields(doc_type)
    cleaned = {}
    for k, v in row.items():
        if v is None:
            cleaned[k] = ""
            continue
        s = str(v).strip()
        k_lower = k.lower().replace(" ", "_")
        if any(k_lower == f or k_lower.endswith(f) for f in numeric_fields):
            s = re.sub(r'[£€$¥₹,\s]', '', s)
            s = re.sub(r'^\((.+)\)$', r'-\1', s)  # accounting negatives
        cleaned[k] = s
    return cleaned


def _filter_ghost_rows(rows: list, col_names: list) -> list:
    """Remove artefact rows from AI table output."""
    if not rows or not col_names:
        return rows
    first_col = col_names[0]
    skip_kw = {"subtotal", "total", "shipping", "tax", "discount",
               "charges", "refund", "paid", "free", "balance", "grand total"}
    clean = []
    for row in rows:
        first_val = str(row.get(first_col, "")).strip()
        if not first_val:
            continue
        if re.match(r'^[\d,.\-\s]{1,6}$', first_val) and not re.search(r'[a-zA-Z]', first_val):
            continue
        if any(kw in first_val.lower() for kw in skip_kw):
            continue
        clean.append(row)
    return clean


# ─── Multi-document Detection ─────────────────────────────────────────────────

def _detect_document_boundaries(orchestrator, doc_text: str, filename: str) -> list:
    if not doc_text or len(doc_text) < 300:
        return [{"index": 0, "text": doc_text, "hint": "full document"}]

    detection_prompt = f"""You are a document analysis agent.
Examine the text and determine if it contains multiple SEPARATE documents.

Return ONLY this JSON:
{{
  "document_count": <integer>,
  "documents": [
    {{"index": 0, "hint": "brief description",
      "start_marker": "first ~20 chars", "end_marker": "last ~20 chars"}}
  ]
}}

Only split on CLEAR document boundaries. If one document: document_count: 1.

TEXT:
{doc_text[:6000]}"""

    try:
        detection = orchestrator.llm.extract(text=doc_text[:6000], prompt=detection_prompt)
        if not detection.success or not detection.parsed_json:
            return [{"index": 0, "text": doc_text, "hint": "full document"}]

        raw = detection.parsed_json
        doc_count = raw.get("document_count", 1)
        if doc_count <= 1 or not raw.get("documents"):
            return [{"index": 0, "text": doc_text, "hint": "full document"}]

        print(f"[DETECT] {filename}: {doc_count} documents", flush=True)
        segments = []
        doc_list = raw["documents"]
        full = doc_text

        for i, meta in enumerate(doc_list):
            start_marker = meta.get("start_marker", "").strip()
            end_marker = meta.get("end_marker", "").strip()
            hint = meta.get("hint", f"doc {i+1}")
            start_pos = full.find(start_marker) if start_marker else -1
            end_pos = full.find(end_marker) if end_marker else -1

            if start_pos == -1:
                chunk = len(full) // doc_count
                start_pos = i * chunk
                end_pos = start_pos + chunk if i < doc_count - 1 else len(full)
            elif end_pos == -1 or end_pos <= start_pos:
                if i + 1 < len(doc_list):
                    nm = doc_list[i+1].get("start_marker", "").strip()
                    np = full.find(nm, start_pos + 1) if nm else -1
                    end_pos = np if np > start_pos else len(full)
                else:
                    end_pos = len(full)
            else:
                end_pos += len(end_marker)

            seg = full[start_pos:end_pos].strip()
            if seg:
                segments.append({"index": i, "text": seg, "hint": hint})

        return segments if segments else [{"index": 0, "text": doc_text, "hint": "full document"}]

    except Exception as e:
        print(f"[DETECT] {filename}: {e}", flush=True)
        return [{"index": 0, "text": doc_text, "hint": "full document"}]


# ─── Result Processors ────────────────────────────────────────────────────────

def _make_table_result(rows: list, template_data: dict, filename: str,
                       doc_type: str, elapsed: float, method: str, extraction=None,
                       confidence: str = "high"):
    from orchestrator import DocumentExtractionResult
    headers = _get_table_headers(template_data["layout"])
    col_names = [h["label"] for h in headers]
    normalised = [_normalise_values(row, doc_type) for row in rows]

    r = DocumentExtractionResult(filename=filename)
    r.document_type = doc_type
    r.extracted_data = {
        "document_type": doc_type,
        "overall_confidence": confidence,
        "table_mode": True,
        "extraction_method": method,
        "table_rows": normalised,
        "column_headers": col_names,
        "row_count": len(normalised),
        "extracted_data": {
            **({col: {"value": normalised[0].get(col, ""), "confidence": "high"}
                for col in col_names} if normalised else {}),
            "_table_row_count": {"value": str(len(normalised)), "confidence": "high"},
        },
    }
    r.extraction_response = extraction
    r.processing_time_ms = elapsed
    r.success = True
    print(f"[EXTRACT] {method}: {filename} → {len(normalised)} rows @ {confidence}", flush=True)
    return r


def _make_form_result(raw: dict, template_data: dict, filename: str,
                      doc_type: str, confidence: str, elapsed: float,
                      extraction, seg_hint: str = ""):
    from orchestrator import DocumentExtractionResult
    layout = template_data["layout"]
    cells = layout.get("cells", {})
    extracted_fields = raw.get("extracted_fields", {})

    ref_to_label = {}
    for key, cell in cells.items():
        if not isinstance(cell, dict):
            continue
        val = cell.get("value", "").strip()
        if cell.get("extractTarget") and val:
            parts = key.split(",")
            if len(parts) == 2:
                ref_to_label[_cell_ref(int(parts[0]), int(parts[1]))] = val

    for ref in extracted_fields:
        if ref not in ref_to_label:
            try:
                col_str = "".join(ch for ch in ref if ch.isalpha()).upper()
                row_str = "".join(ch for ch in ref if ch.isdigit())
                c_idx = sum((ord(ch) - 64) * (26 ** i) for i, ch in enumerate(reversed(col_str))) - 1
                r_idx = int(row_str) - 1
                left_val = (cells.get(f"{r_idx},{c_idx-1}") or {}).get("value", "").strip() if c_idx > 0 else ""
                above_val = (cells.get(f"{r_idx-1},{c_idx}") or {}).get("value", "").strip() if r_idx > 0 else ""
                ref_to_label[ref] = left_val or above_val or ref
            except Exception:
                ref_to_label[ref] = ref

    extracted_data = {}
    for ref, label in ref_to_label.items():
        extracted_data[label] = {"value": extracted_fields.get(ref, ""), "confidence": "high"}

    for key, cell in cells.items():
        if not isinstance(cell, dict):
            continue
        val = cell.get("value", "").strip()
        if val and not cell.get("extractTarget"):
            parts = key.split(",")
            if len(parts) == 2:
                ref = _cell_ref(int(parts[0]), int(parts[1]))
                extracted_data[f"_label_{ref}"] = {"value": val, "confidence": "high"}

    r = DocumentExtractionResult(filename=filename)
    r.document_type = doc_type
    r.extracted_data = {
        "document_type": doc_type,
        "overall_confidence": confidence,
        "extraction_method": "ai_form",
        "extracted_data": extracted_data,
        "extracted_fields": extracted_fields,
        "segment_hint": seg_hint,
    }
    r.extraction_response = extraction
    r.processing_time_ms = elapsed
    r.success = True
    print(f"[EXTRACT] form: {filename} ({seg_hint}) → {len(extracted_fields)} fields @ {confidence}", flush=True)
    return r


def _make_columns_result(raw: dict, template_data: dict, filename: str,
                          doc_type: str, confidence: str, elapsed: float, extraction):
    from orchestrator import DocumentExtractionResult
    header_data = raw.get("header", raw.get("extracted_data", {}))
    header_cols = template_data.get("header_cols", [])
    normalised = {}
    for col in header_cols:
        name = col.get("name", "").strip()
        if not name:
            continue
        fd = header_data.get(name)
        if fd is None:
            normalised[name] = {"value": "", "confidence": "high"}
        elif isinstance(fd, dict):
            normalised[name] = {"value": fd.get("value", ""), "confidence": fd.get("confidence", "high")}
        else:
            normalised[name] = {"value": str(fd) if fd is not None else "", "confidence": "high"}

    r = DocumentExtractionResult(filename=filename)
    r.document_type = doc_type
    r.extracted_data = {
        "document_type": doc_type,
        "overall_confidence": confidence,
        "extraction_method": "legacy_columns",
        "extracted_data": normalised,
    }
    r.extraction_response = extraction
    r.processing_time_ms = elapsed
    r.success = True
    return r


def _fail(filename: str, error: str):
    from orchestrator import DocumentExtractionResult
    r = DocumentExtractionResult(filename=filename)
    r.error = error
    r.processing_time_ms = 0
    r.success = False
    return r


# ─── Main Extraction Engine ───────────────────────────────────────────────────

def _extract_with_template(orchestrator, file_path: Path, template_data: dict):
    """
    Core extraction engine.

    TABLE mode  → pdfplumber direct first, AI with registry prompt as fallback
    FORM mode   → multi-doc detection + AI with registry prompt per segment
    COLUMNS mode → AI with registry prompt (legacy)
    """
    import time as t
    from core.preprocessor import preprocess_file

    doc_type = template_data.get("doc_type", "other")
    mode = template_data.get("mode", "columns")
    start = t.time()
    results = []

    try:
        doc = preprocess_file(file_path)
        doc_text = doc.extracted_text or ""
        use_vision = doc.needs_vision and bool(doc.page_images_b64)

        # Auto-classify if doc_type unknown
        if doc_type in ("other", "", None) and doc_text:
            hint = _classify_by_hints(doc_text)
            if hint:
                doc_type = hint
                template_data = {**template_data, "doc_type": doc_type}
                print(f"[EXTRACT] {file_path.name}: auto-classified → {doc_type}", flush=True)

        # ── LAYOUT MODE ───────────────────────────────────────────────────────
        if mode == "layout":
            layout = template_data["layout"]
            template_mode = _detect_template_mode(layout)

            # ── TABLE MODE ───────────────────────────────────────────────────
            if template_mode == "table":
                print(f"[EXTRACT] {file_path.name}: TABLE/{doc_type}", flush=True)

                direct_rows = _extract_pdf_table_direct(file_path, template_data)
                elapsed = (t.time() - start) * 1000

                if direct_rows:
                    results.append(_make_table_result(
                        direct_rows, template_data, file_path.name,
                        doc_type, elapsed, "direct_pdf_table"
                    ))
                else:
                    print(f"[EXTRACT] {file_path.name}: direct failed → AI fallback", flush=True)
                    clean_text = _clean_text_for_table(doc_text)
                    prompt = _build_table_prompt(template_data, clean_text)

                    if use_vision:
                        extraction = orchestrator.llm.extract(image_b64=doc.page_images_b64[0], prompt=prompt)
                    else:
                        extraction = orchestrator.llm.extract(text=clean_text, prompt=prompt)

                    elapsed = (t.time() - start) * 1000

                    if not extraction.success or not extraction.parsed_json:
                        r = _fail(file_path.name, f"Table extraction failed: {extraction.error}")
                        r.processing_time_ms = elapsed
                        results.append(r)
                    else:
                        raw = extraction.parsed_json
                        table_rows = _filter_ghost_rows(
                            raw.get("table_rows", []),
                            [h["label"] for h in _get_table_headers(layout)]
                        )
                        normalised = []
                        for row in table_rows:
                            if isinstance(row, dict):
                                clean = {col: str(row.get(col, "") or "").strip()
                                         for col in [h["label"] for h in _get_table_headers(layout)]}
                                normalised.append(_normalise_values(clean, doc_type))
                        results.append(_make_table_result(
                            normalised, template_data, file_path.name, doc_type,
                            elapsed, "ai_table", extraction,
                            raw.get("overall_confidence", "medium")
                        ))

            # ── FORM MODE ────────────────────────────────────────────────────
            else:
                print(f"[EXTRACT] {file_path.name}: FORM/{doc_type}", flush=True)
                segments = _detect_document_boundaries(orchestrator, doc_text, file_path.name)
                total_docs = len(segments)

                for segment in segments:
                    seg_text = segment["text"]
                    seg_index = segment["index"]
                    seg_hint = segment.get("hint", f"doc {seg_index+1}")

                    prompt = _build_form_prompt(template_data, seg_text, seg_index, total_docs)

                    if use_vision and seg_index == 0:
                        extraction = orchestrator.llm.extract(image_b64=doc.page_images_b64[0], prompt=prompt)
                    else:
                        extraction = orchestrator.llm.extract(text=seg_text, prompt=prompt)

                    elapsed = (t.time() - start) * 1000
                    seg_fn = (file_path.name if total_docs == 1
                              else f"{file_path.stem}_doc{seg_index+1}{file_path.suffix}")

                    if not extraction.success or not extraction.parsed_json:
                        r = _fail(seg_fn, f"Extraction failed: {extraction.error}")
                        r.processing_time_ms = elapsed
                        results.append(r)
                    else:
                        raw = extraction.parsed_json
                        results.append(_make_form_result(
                            raw, template_data, seg_fn, doc_type,
                            raw.get("overall_confidence", "medium"), elapsed, extraction, seg_hint
                        ))

        # ── COLUMNS MODE (legacy) ─────────────────────────────────────────────
        else:
            print(f"[EXTRACT] {file_path.name}: COLUMNS/{doc_type}", flush=True)
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
                results.append(_make_columns_result(
                    raw, template_data, file_path.name, doc_type,
                    raw.get("overall_confidence", "medium"), elapsed, extraction
                ))

    except Exception as e:
        print(f"[EXTRACT] Error {file_path.name}: {e}", flush=True)
        traceback.print_exc()
        r = _fail(file_path.name, str(e))
        r.processing_time_ms = (time.time() - start) * 1000
        results.append(r)

    return results if results else [_fail(file_path.name, "No data extracted")]


# ─── Background Thread ────────────────────────────────────────────────────────

def _run_extraction_sync(job_id, file_paths, schema_path, db_url, template_data,
                          project_dir, backend_dir, engine_dir):
    import os
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
                        model_used=(result.extraction_response.model_used
                                    if result.extraction_response else "direct_pdf"),
                        tokens_used=(result.extraction_response.tokens_used
                                     if result.extraction_response else 0),
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


# ─── Excel Export ─────────────────────────────────────────────────────────────

@router.get("/jobs/{job_id}/export")
def export_job_excel(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        import openpyxl
    except ImportError:
        raise HTTPException(status_code=500, detail="openpyxl not installed.")

    job = _get_job_or_404(job_id, current_user, db)
    doc_results = (
        db.query(DocumentResult)
        .filter(DocumentResult.job_id == job_id)
        .order_by(DocumentResult.id)
        .all()
    )
    if not doc_results:
        raise HTTPException(status_code=404, detail="No results found.")

    sheet_data = None
    if job.schema_id:
        try:
            tpl = db.query(ColumnTemplate).filter(
                ColumnTemplate.id == int(job.schema_id)
            ).first()
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
        _write_excel(ws, doc_results, sheet_data, openpyxl)
    else:
        _write_flat_table(ws, doc_results, openpyxl)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    return StreamingResponse(buf, headers={
        "Content-Disposition": f'attachment; filename="job_{job_id}_results.xlsx"',
        "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    })


# ─── Excel Writers ────────────────────────────────────────────────────────────

def _write_excel(ws, doc_results, sheet_data, openpyxl_mod):
    from openpyxl.utils import get_column_letter
    cells_tpl = sheet_data.get("cells", {})
    col_widths = sheet_data.get("colWidths", [])
    max_r, max_c = _find_template_dimensions(cells_tpl)

    for c_idx, width_px in enumerate(col_widths):
        if width_px and c_idx <= max_c:
            ws.column_dimensions[get_column_letter(c_idx + 1)].width = max(8, round(width_px / 7))

    first_data = doc_results[0].get_extracted_data() if doc_results else {}
    if first_data.get("table_mode"):
        _write_table_excel(ws, doc_results, sheet_data, cells_tpl, openpyxl_mod)
    else:
        _write_form_excel(ws, doc_results, sheet_data, cells_tpl, max_r, max_c, openpyxl_mod)


def _write_table_excel(ws, doc_results, sheet_data, cells_tpl, openpyxl_mod):
    # Write header row with original styles
    for key, cell_def in cells_tpl.items():
        if not isinstance(cell_def, dict):
            continue
        parts = key.split(",")
        if len(parts) != 2 or int(parts[0]) != 0:
            continue
        tc = int(parts[1])
        xl_cell = ws.cell(row=1, column=tc + 1)
        xl_cell.value = cell_def.get("value", "").strip()
        if cell_def.get("style"):
            _apply_cell_style(xl_cell, cell_def["style"], openpyxl_mod)

    headers = _get_table_headers(sheet_data)
    col_indices = {h["label"]: h["col"] for h in headers}
    current_row = 2

    for doc_result in doc_results:
        extracted = doc_result.get_extracted_data()
        for row_data in extracted.get("table_rows", []):
            for col_name, c_idx in col_indices.items():
                val = row_data.get(col_name, "")
                xl_cell = ws.cell(row=current_row, column=c_idx + 1)
                try:
                    xl_cell.value = (float(val) if "." in str(val) else int(val)) if val else val
                except (ValueError, TypeError):
                    xl_cell.value = val
            current_row += 1

    print(f"[EXPORT] table: {current_row - 2} data rows written", flush=True)


def _write_form_excel(ws, doc_results, sheet_data, cells_tpl, max_r, max_c, openpyxl_mod):
    from openpyxl.styles import Font
    merges_tpl = sheet_data.get("merges", {})
    block_height = max_r + 2  # template rows + 1 blank separator

    for block_idx, doc_result in enumerate(doc_results):
        row_offset = block_idx * block_height
        extracted_data = doc_result.get_extracted_data()
        extracted_fields = extracted_data.get("extracted_fields", {})
        label_to_value = {
            k: (v.get("value", "") if isinstance(v, dict) else str(v or ""))
            for k, v in extracted_data.get("extracted_data", {}).items()
            if not k.startswith("_label_")
        }

        for key, cell_def in cells_tpl.items():
            if not isinstance(cell_def, dict) or cell_def.get("mergeParent"):
                continue
            parts = key.split(",")
            if len(parts) != 2:
                continue
            tr, tc = int(parts[0]), int(parts[1])
            xl_cell = ws.cell(row=row_offset + tr + 1, column=tc + 1)

            tpl_value = cell_def.get("value", "").strip()
            if cell_def.get("extractTarget"):
                ref = f"{_col_letter(tc)}{tr + 1}"
                xl_cell.value = extracted_fields.get(ref) or label_to_value.get(tpl_value, "")
            else:
                xl_cell.value = tpl_value

            if cell_def.get("style"):
                _apply_cell_style(xl_cell, cell_def["style"], openpyxl_mod)

            merge_span = cell_def.get("mergeSpan") or merges_tpl.get(key)
            if merge_span:
                sr, sc = merge_span.get("rows", 1), merge_span.get("cols", 1)
                if sr > 1 or sc > 1:
                    ws.merge_cells(
                        start_row=row_offset + tr + 1, start_column=tc + 1,
                        end_row=row_offset + tr + sr, end_column=tc + sc,
                    )

        if block_idx > 0:
            lc = ws.cell(row=row_offset, column=1)
            lc.value = f"▶  {doc_result.filename}"
            lc.font = Font(bold=True, color="FF4F46E5", size=10)
        else:
            nc = ws.cell(row=1, column=max_c + 3)
            nc.value = doc_result.filename
            nc.font = Font(color="FF9CA3AF", size=9, italic=True)


def _write_flat_table(ws, doc_results, openpyxl_mod):
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    all_keys, seen = [], set()
    for dr in doc_results:
        for k in (dr.get_extracted_data().get("extracted_data") or {}):
            if k not in seen and not k.startswith("_label_"):
                seen.add(k)
                all_keys.append(k)

    hf = PatternFill(fill_type="solid", fgColor="FF4F46E5")
    hfont = Font(bold=True, color="FFFFFFFF", size=11)
    c = ws.cell(row=1, column=1, value="Filename")
    c.font = hfont
    c.fill = hf
    for ci, key in enumerate(all_keys, 2):
        c = ws.cell(row=1, column=ci, value=key)
        c.font = hfont
        c.fill = hf

    for ri, dr in enumerate(doc_results, 2):
        ws.cell(row=ri, column=1, value=dr.filename)
        inner = dr.get_extracted_data().get("extracted_data") or {}
        for ci, key in enumerate(all_keys, 2):
            v = inner.get(key)
            ws.cell(row=ri, column=ci, value=(v.get("value", "") if isinstance(v, dict) else (v or "")))

    ws.column_dimensions["A"].width = 30
    for ci in range(2, len(all_keys) + 2):
        ws.column_dimensions[get_column_letter(ci)].width = 20


# ─── Style helpers ────────────────────────────────────────────────────────────

def _parse_hex_color(hex_color: Optional[str]) -> Optional[str]:
    if not hex_color:
        return None
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    return f"FF{h.upper()}" if len(h) == 6 else None


def _apply_cell_style(xl_cell, style: dict, _openpyxl_mod) -> None:
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    fk = {}
    if style.get("bold"):      fk["bold"] = True
    if style.get("italic"):    fk["italic"] = True
    if style.get("underline"): fk["underline"] = "single"
    if style.get("fontSize"):  fk["size"] = style["fontSize"]
    if style.get("fontFamily"):fk["name"] = style["fontFamily"]
    fc = _parse_hex_color(style.get("fontColor"))
    if fc: fk["color"] = fc
    if fk: xl_cell.font = Font(**fk)

    bg = _parse_hex_color(style.get("bgColor"))
    if bg: xl_cell.fill = PatternFill(fill_type="solid", fgColor=bg)

    xl_cell.alignment = Alignment(
        horizontal={"left": "left", "center": "center", "right": "right"}.get(style.get("align", ""), "left"),
        wrap_text=bool(style.get("wrap")), vertical="center"
    )
    if style.get("borderAll"):
        t = Side(style="thin")
        xl_cell.border = Border(left=t, right=t, top=t, bottom=t)
    elif style.get("borderOuter"):
        m = Side(style="medium")
        xl_cell.border = Border(left=m, right=m, top=m, bottom=m)


def _find_template_dimensions(cells: dict) -> tuple:
    max_r, max_c = 0, 0
    for key in cells:
        parts = key.split(",")
        if len(parts) == 2:
            r, c = int(parts[0]), int(parts[1])
            max_r = max(max_r, r)
            max_c = max(max_c, c)
    return max_r, max_c


# ─── Job Routes ───────────────────────────────────────────────────────────────

@router.get("/jobs", response_model=list[JobListItem])
def list_jobs(
    limit: int = 50, offset: int = 0, status_filter: Optional[str] = None,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
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
def get_job_results(
    job_id: int, doc_type: Optional[str] = None, needs_review: Optional[bool] = None,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
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
    job_id: int, doc_id: int, payload: DocumentUpdateRequest,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
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
    job_id: int, doc_id: int,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
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
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
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
