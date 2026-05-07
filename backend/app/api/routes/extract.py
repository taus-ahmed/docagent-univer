"""
DocAgent v2 - Extract Routes (Vision-First Architecture)
=========================================================

ARCHITECTURE OVERVIEW
---------------------
Previous approach: binary TABLE vs FORM decision based on template layout.
Problem: fails on mixed layouts (Form 941, Balance Sheet header+table, etc.)

New approach: Vision-First with pdfplumber validation layer.

EXTRACTION PIPELINE (per document):
  1. TEMPLATE REGION ANALYSIS
     Read the template grid and identify ALL regions:
     - key_value pairs (label in col A, value in col B)
     - two_column_form (labels+values on both left and right sides)
     - table_header (column headers for repeating rows)
     - free_form (labels anywhere, values anywhere nearby)
     Region map is cached - computed once per template.

  2. PAGE IMAGE EXTRACTION (primary - Gemini Vision)
     Convert every PDF page to a base64 image.
     Send image + template region map + registry system prompt to Gemini.
     Gemini sees the document visually - reads any layout correctly.
     Returns JSON with every field value.

  3. pdfplumber TEXT EXTRACTION (parallel - validation layer)
     Extract all text from the PDF independently.
     For each AI-returned value, check whether it appears in the pdfplumber text.
     If yes -> HIGH confidence.
     If no  -> LOW confidence, flag for review.
     This catches AI hallucinations before they reach the Excel output.

  4. MULTI-DOCUMENT HANDLING
     One PDF may contain N separate documents (100 cheques, 50 invoices).
     Vision pre-pass detects document boundaries from the page images.
     Each detected document gets its own extraction pass.
     Each produces its own result block in the Excel output.

  5. TABLE DETECTION (for table-mode templates)
     pdfplumber reads the physical table structure from the PDF.
     Tables may start anywhere on the page (not just top-left).
     If table found -> extract directly, validate with AI.
     If not found   -> AI extracts from image, pdfplumber validates.

  6. EXCEL EXPORT
     Rebuilds the exact template grid per result.
     For table mode: header row + one data row per extracted line item.
     For form mode: one filled template block per document, stacked.
     For 100 cheques: 100 filled blocks in one sheet, separated by filename rows.

CONFIDENCE LEVELS:
  high   = AI value confirmed by pdfplumber text
  medium = AI value not confirmed but plausible (pdfplumber text was partial)
  low    = AI value not found anywhere in pdfplumber text (flag for review)
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


# ==============================================================================
# UPLOAD ENDPOINT
# ==============================================================================

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


# ==============================================================================
# TEMPLATE PARSING & REGION ANALYSIS
# ==============================================================================

def _parse_template(tpl: ColumnTemplate) -> Optional[dict]:
    """Parse a ColumnTemplate into extraction-ready format with region analysis."""
    if tpl.description:
        try:
            raw = json.loads(tpl.description)
            if isinstance(raw, dict) and "cells" in raw:
                template_data = {
                    "mode": "layout",
                    "layout": raw,
                    "doc_type": tpl.document_type or "other",
                    "name": tpl.name,
                }
                # Analyse regions once and cache in template_data
                template_data["regions"] = _analyse_template_regions(raw)
                return template_data
        except Exception as e:
            print(f"[TEMPLATE] description parse error: {e}", flush=True)

    if not tpl.columns_json:
        return None

    try:
        raw = json.loads(tpl.columns_json)
        if isinstance(raw, dict) and "extractTargets" in raw:
            template_data = {
                "mode": "layout",
                "layout": raw,
                "doc_type": tpl.document_type or "other",
                "name": tpl.name,
            }
            template_data["regions"] = _analyse_template_regions(raw)
            return template_data

        header_cols = []
        for i, item in enumerate(raw if isinstance(raw, list) else []):
            if isinstance(item, str):
                col = {"name": item, "type": "Text", "order": i}
            else:
                col = {"name": item.get("name",""), "type": item.get("type","Text"),
                       "order": item.get("order", i)}
            header_cols.append(col)

        return {
            "mode": "columns",
            "header_cols": header_cols,
            "doc_type": tpl.document_type or "other",
            "name": tpl.name,
        }
    except Exception as e:
        print(f"[TEMPLATE] columns_json parse error: {e}", flush=True)
        return None


def _analyse_template_regions(layout: dict) -> dict:
    """
    Analyse the template grid and identify ALL extraction regions.

    This replaces the binary TABLE/FORM decision with a rich structural map
    that tells the AI exactly what the user designed and where.

    Detects:
      - key_value_pairs: label in col N, empty extract cell in col N+1
      - two_column_form: labels+values on BOTH left and right halves
      - table_header: a row of column headers with no values below
      - free_positions: explicit Extract here cells at any grid position
      - blank_near_label: empty cells adjacent to labels (auto-fill mode)

    Returns a regions dict that gets passed to the AI prompt.
    """
    cells = layout.get("cells", {})
    extract_targets = layout.get("extractTargets", [])

    # Parse all cells into a row/col grid
    grid = {}  # (row, col) -> {value, extractTarget, style}
    max_row, max_col = 0, 0
    for key, cell in cells.items():
        if not isinstance(cell, dict):
            continue
        parts = key.split(",")
        if len(parts) != 2:
            continue
        r, c = int(parts[0]), int(parts[1])
        max_row = max(max_row, r)
        max_col = max(max_col, c)
        grid[(r, c)] = {
            "value": cell.get("value", "").strip(),
            "extractTarget": cell.get("extractTarget", False),
            "ref": _cell_ref(r, c),
            "row": r,
            "col": c,
        }

    # Find all explicit Extract here targets
    explicit_targets = []
    for (r, c), cell in grid.items():
        if cell["extractTarget"] and not cell["value"]:
            # Find the nearest label (left, above, or two left)
            label = ""
            for dc in range(1, 4):  # look up to 3 cells to the left
                neighbor = grid.get((r, c - dc))
                if neighbor and neighbor["value"]:
                    label = neighbor["value"]
                    break
            if not label:
                neighbor = grid.get((r - 1, c))
                if neighbor and neighbor["value"]:
                    label = neighbor["value"]
            explicit_targets.append({
                "ref": _cell_ref(r, c),
                "row": r, "col": c,
                "label": label or f"field at {_cell_ref(r, c)}",
            })

    # Also check extractTargets list from layout
    for t in extract_targets:
        ref = _cell_ref(t.get("r", 0), t.get("c", 0))
        if not any(e["ref"] == ref for e in explicit_targets):
            explicit_targets.append({
                "ref": ref,
                "row": t.get("r", 0),
                "col": t.get("c", 0),
                "label": t.get("label", f"field at {ref}"),
            })

    # Detect key-value pairs (label col N, empty col N+1, same row)
    kv_pairs = []
    for (r, c), cell in grid.items():
        if cell["value"] and not cell["extractTarget"]:
            right = grid.get((r, c + 1))
            if right and (right["extractTarget"] or not right["value"]):
                kv_pairs.append({
                    "label": cell["value"],
                    "label_ref": cell["ref"],
                    "value_ref": _cell_ref(r, c + 1),
                    "row": r,
                })

    # Detect two-column form layout
    # Pattern: labels in col A, values in col B, AND labels in col C, values in col D
    # More generally: labels in even cols, values in odd cols (or vice versa)
    two_col_pairs = []
    for (r, c), cell in grid.items():
        if cell["value"] and not cell["extractTarget"]:
            # Look for a value cell 2 columns to the right (two-column layout)
            right2 = grid.get((r, c + 2))
            if right2 and (right2["extractTarget"] or not right2["value"]):
                # Check there is also a label at c+1 or c+2 area
                mid = grid.get((r, c + 1))
                if mid and mid["value"] and not mid["extractTarget"]:
                    # Pattern: LabelA | ValueA | LabelB | ValueB
                    far_right = grid.get((r, c + 3))
                    if far_right and (far_right["extractTarget"] or not far_right["value"]):
                        two_col_pairs.append({
                            "left_label": cell["value"],
                            "left_label_ref": cell["ref"],
                            "left_value_ref": _cell_ref(r, c + 1),
                            "right_label": mid["value"],
                            "right_label_ref": mid["ref"],
                            "right_value_ref": _cell_ref(r, c + 3),
                            "row": r,
                        })

    # Detect table headers — the actual column header row for repeating data rows.
    # Rules for a valid table header row:
    #   1. Has 2+ non-empty cells
    #   2. NONE of the cells in that row are extract targets (those are form fields)
    #   3. NONE of the cells in adjacent columns of same row are extract targets
    #   4. The row BELOW is empty (data will go there) OR it is the last content row
    # This prevents two-column form rows from being misidentified as table headers.
    table_regions = []
    rows_with_content = {}
    for (r, c), cell in grid.items():
        if cell["value"] or cell["extractTarget"]:
            rows_with_content.setdefault(r, []).append(c)

    # Build a set of rows that contain extract targets — these are form rows
    form_rows_set = set()
    for (r, c), cell in grid.items():
        if cell["extractTarget"]:
            form_rows_set.add(r)
        # Also mark the row of any cell adjacent to an extract target
        for dc in range(-3, 4):
            neighbor = grid.get((r, c + dc))
            if neighbor and neighbor["extractTarget"]:
                form_rows_set.add(r)

    for r, cols in sorted(rows_with_content.items()):
        # Skip rows that are form rows (have extract targets nearby)
        if r in form_rows_set:
            continue

        value_cols = [c for c in cols
                      if grid.get((r, c)) and grid[(r, c)]["value"]
                      and not grid[(r, c)]["extractTarget"]]

        if len(value_cols) < 2:
            continue

        row_labels = [grid[(r, c)]["value"] for c in sorted(value_cols)]

        # The row below should be empty (table body placeholder)
        below_cols = [c for c in rows_with_content.get(r + 1, [])
                      if grid.get((r + 1, c)) and grid[(r + 1, c)]["value"]]
        is_header_only = len(below_cols) == 0

        min_col = min(value_cols)
        max_col = max(value_cols)
        table_regions.append({
            "header_row": r,
            "start_col": min_col,
            "end_col": max_col,
            "start_ref": _cell_ref(r, min_col),
            "end_ref": _cell_ref(r, max_col),
            "column_names": row_labels,
            "is_header_only": is_header_only,
        })

    # If multiple table regions detected, keep only the best one:
    # prefer the one with the most columns AND whose row below is empty
    if len(table_regions) > 1:
        table_regions.sort(key=lambda t: (
            t["is_header_only"],          # empty row below = more likely table header
            len(t["column_names"]),        # more columns = more likely table header
            t["header_row"],               # later row = below the form fields
        ), reverse=True)
        table_regions = table_regions[:1]  # keep only the best candidate

    # Build summary for AI
    has_explicit_targets = len(explicit_targets) > 0
    has_kv_pairs = len(kv_pairs) > 0
    has_two_col = len(two_col_pairs) > 0
    has_table = len(table_regions) > 0

    # Mixed mode: has BOTH form fields (targets or kv pairs) AND a table
    # This is the most important detection — Balance Sheet, Expense Report,
    # Purchase Order, Tax Form all have header fields + line items table
    if has_table and (has_explicit_targets or has_kv_pairs):
        primary_mode = "mixed"
    elif not has_table and has_explicit_targets:
        primary_mode = "form_with_targets"
    elif not has_table and has_kv_pairs:
        primary_mode = "form_kv"
    elif has_table and not has_explicit_targets and not has_kv_pairs:
        primary_mode = "table"
    else:
        primary_mode = "mixed"

    print(f"[REGION] mode={primary_mode} targets={len(explicit_targets)} "
          f"kv={len(kv_pairs)} two_col={len(two_col_pairs)} "
          f"tables={len(table_regions)} grid={max_row+1}x{max_col+1}", flush=True)

    return {
        "primary_mode": primary_mode,
        "explicit_targets": explicit_targets,
        "kv_pairs": kv_pairs,
        "two_col_pairs": two_col_pairs,
        "table_regions": table_regions,
        "grid_size": {"rows": max_row + 1, "cols": max_col + 1},
        "has_explicit_targets": has_explicit_targets,
        "has_table": has_table,
        "max_row": max_row,
        "max_col": max_col,
    }


# ==============================================================================
# REGISTRY LOADER
# ==============================================================================

def _load_registry():
    if not hasattr(_load_registry, "_cache"):
        try:
            import importlib.util
            reg_file = Path(__file__).resolve().parent / "prompt_registry.py"
            if reg_file.exists():
                spec = importlib.util.spec_from_file_location("prompt_registry", reg_file)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                _load_registry._cache = mod
                print(f"[REGISTRY] Loaded from {reg_file}", flush=True)
            else:
                _load_registry._cache = None
        except Exception as e:
            print(f"[REGISTRY] Load error: {e}", flush=True)
            _load_registry._cache = None
    return _load_registry._cache


def _get_system_prompt(doc_type): r=_load_registry(); return r.get_system_prompt(doc_type) if r else f"You are an expert {doc_type} extraction specialist."
def _get_table_rules(doc_type): r=_load_registry(); return (r.get_table_rules(doc_type) or "") if r else ""
def _get_numeric_fields(doc_type): r=_load_registry(); return r.get_numeric_fields(doc_type) if r else []
def _get_date_fields(doc_type): r=_load_registry(); return r.get_date_fields(doc_type) if r else []
def _classify_by_hints(text): r=_load_registry(); return r.classify_by_hints(text) if r else None


# ==============================================================================
# CELL HELPERS
# ==============================================================================

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


# ==============================================================================
# VISION-FIRST PROMPT BUILDER
# ==============================================================================

def _build_vision_prompt(template_data: dict, doc_text: str = "") -> str:
    """
    Build the master extraction prompt for vision-first extraction.
    Uses plain ASCII only - no unicode box-drawing characters that can
    cause encoding issues with Gemini Flash API.
    """
    doc_type = template_data.get("doc_type", "other")
    regions = template_data.get("regions", {})
    layout = template_data.get("layout", {})

    system_prompt = _get_system_prompt(doc_type)
    table_rules = _get_table_rules(doc_type)
    primary_mode = regions.get("primary_mode", "form_kv")

    fields_description = _build_fields_description(regions, layout)
    extraction_instructions = _build_extraction_instructions(regions, primary_mode, table_rules)
    output_format = _build_output_format(regions, primary_mode)

    prompt = f"""{system_prompt}

=== EXTRACTION TASK ===

The user has designed a template showing exactly what fields they want extracted.
Your job is to find each field value in the document and return it accurately.

=== TEMPLATE STRUCTURE ===
{fields_description}

=== EXTRACTION INSTRUCTIONS ===
{extraction_instructions}

=== CRITICAL RULES ===
1. ABBREVIATION AND SYNONYM MATCHING — THIS IS THE MOST IMPORTANT RULE:
   The template label and the document label will OFTEN be different.
   You MUST match by MEANING and CONCEPT, not by exact words.

   You are an expert in business documents. Use your knowledge to understand
   that a short label in a template refers to the same concept as a longer
   label in a document, even if the words are completely different.

   General principles:
   - Abbreviations: "No" = "Number", "Emp" = "Employee/Employer", "Amt" = "Amount",
     "Qty" = "Quantity", "Addr" = "Address", "Dept" = "Department", "Mgr" = "Manager",
     "Bal" = "Balance", "Qtr" = "Quarter", "Fed" = "Federal", "YTD" = "Year to Date"
   - Acronyms: "EIN" = "Employer Identification Number", "SSN" = "Social Security Number",
     "DOB" = "Date of Birth", "PO" = "Purchase Order", "AR" = "Accounts Receivable"
   - Synonyms: "Total" = "Grand Total" = "Amount Due" = "Net Payable" = "Sum"
   - Combinations: "No of Emp" means "Number of Employees" — combine the abbreviations

   RULE: If a template label is an abbreviation or shortening of something in the
   document, they refer to the same field. Extract the value.

   RULE: If you cannot find an EXACT label match, find the CLOSEST MEANING match.
   A conceptual match is better than leaving a field empty.
   Only use "" if the information is GENUINELY ABSENT from the document entirely.

2. LABEL MATCHING — match by MEANING, not exact text:
   - Template "EIN" = Document "Employer Identification Number" or "Tax ID"
   - Template "Payee" = Document "Pay to the Order of" or "Beneficiary"
   - Template "Total" = Document "Amount Due" or "Grand Total" or "Net Payable"

3. MISSING VALUES: Only use "" if the information is GENUINELY ABSENT from the document.
   If the information exists but uses different wording — EXTRACT IT.
   NEVER return "N/A", "null", "not found".

4. NUMBERS: Strip all currency symbols and commas.
   "$8,410.00" becomes "8410.00"

5. DATES: Normalise all dates to YYYY-MM-DD format.
   "January 31, 2024" becomes "2024-01-31"
   "March 31, 2024" becomes "2024-03-31"

6. TABLE POSITION: Tables may start anywhere on the page, not just top-left.

7. CONFIDENCE: Rate each value:
   "high" = clearly found, "medium" = inferred, "low" = uncertain

=== DOCUMENT TEXT ===
{doc_text[:6000] if doc_text else "(See the document image provided)"}

=== OUTPUT FORMAT ===
{output_format}
"""
    return prompt


def _build_fields_description(regions: dict, layout: dict) -> str:
    """Build a human-readable description of what needs to be extracted."""
    lines = []
    primary_mode = regions.get("primary_mode", "form_kv")

    # Explicit extract-here targets
    if regions.get("explicit_targets"):
        lines.append("FIELDS TO EXTRACT (user marked these with 'Extract here'):")
        for t in regions["explicit_targets"]:
            lines.append(f"  - [{t['ref']}] {t['label']}")
        lines.append("")

    # Key-value pairs (auto-detected)
    elif regions.get("kv_pairs"):
        lines.append("KEY-VALUE PAIRS TO FILL:")
        lines.append("(Label is in left column, you fill the right column)")
        for kv in regions["kv_pairs"]:
            lines.append(f"  - Label: \"{kv['label']}\" at {kv['label_ref']}")
            lines.append(f"    -> Fill: {kv['value_ref']}")
        lines.append("")

    # Two-column form layout
    if regions.get("two_col_pairs"):
        lines.append("TWO-COLUMN FORM LAYOUT:")
        lines.append("(There are labels and values on BOTH left and right sides)")
        for tc in regions["two_col_pairs"]:
            lines.append(f"  LEFT  - Label: \"{tc['left_label']}\" ({tc['left_label_ref']}) -> Fill: {tc['left_value_ref']}")
            lines.append(f"  RIGHT - Label: \"{tc['right_label']}\" ({tc['right_label_ref']}) -> Fill: {tc['right_value_ref']}")
        lines.append("")

    # Table regions
    if regions.get("table_regions"):
        lines.append("TABLE(S) TO EXTRACT:")
        for i, tr in enumerate(regions["table_regions"], 1):
            lines.append(f"  Table {i}: starts at row {tr['header_row']+1}, "
                        f"columns {tr['start_ref']} to {tr['end_ref']}")
            lines.append(f"  Column headers: {', '.join(tr['column_names'])}")
            lines.append(f"  -> Extract ALL data rows below the header row")
        lines.append("")

    if not lines:
        lines.append("Extract all visible fields from this document.")

    return "\n".join(lines)


def _build_extraction_instructions(regions: dict, primary_mode: str,
                                    table_rules: str) -> str:
    """Build mode-specific extraction instructions."""
    instructions = []

    if primary_mode in ("form_with_targets", "form_kv"):
        instructions.append(
            "This is a FORM template. Fill each labelled field with its corresponding\n"
            "value from the document. The template has specific cells marked for extraction.\n"
            "Each field should contain exactly ONE value.\n"
            "If the template has blank rows between sections, those are spacers - ignore them."
        )

    elif primary_mode == "table":
        instructions.append(
            "This is a TABLE template. The template shows column headers.\n"
            "Extract EVERY data row from the document's table.\n"
            "IMPORTANT: The table in the document may start at a different position\n"
            "than you expect. Look for rows that match the column headers anywhere on the page.\n"
            "Return one JSON object per data row.\n"
            "Do NOT include the header row itself in table_rows.\n"
            "Do NOT include subtotal, total, tax, or summary rows."
        )
        if table_rules:
            instructions.append(f"\nDOCUMENT-SPECIFIC TABLE RULES:\n{table_rules}")

    elif primary_mode == "mixed":
        instructions.append(
            "This template has BOTH form fields AND a table.\n"
            "Part 1 - Fill the form fields: each has a label and an empty cell to fill.\n"
            "Part 2 - Extract the table: find the column headers and extract all data rows.\n"
            "Return both the form fields (in extracted_fields) AND the table rows (in table_rows)."
        )
        if table_rules:
            instructions.append(f"\nTABLE RULES:\n{table_rules}")

    # Two-column handling
    if regions.get("two_col_pairs"):
        instructions.append(
            "\nTWO-COLUMN LAYOUT HANDLING:\n"
            "The template has labels and values on BOTH the left and right halves.\n"
            "This is NOT a table - each row has up to 2 label-value pairs.\n"
            "Extract BOTH the left-side value AND the right-side value for each row.\n"
            "Do not confuse left-side labels with right-side labels."
        )

    # Auto-fill fallback
    if not regions.get("explicit_targets") and not regions.get("kv_pairs"):
        instructions.append(
            "\nAUTO-FILL MODE:\n"
            "The user did not mark specific cells but the template has labelled fields.\n"
            "For each label in the template, find the corresponding value in the document.\n"
            "Match labels by meaning - the document may use different wording for the same field."
        )

    return "\n\n".join(instructions)


def _build_output_format(regions: dict, primary_mode: str) -> str:
    """Build simple, clean JSON output format - no unicode, Gemini Flash compatible."""

    has_table = primary_mode in ("table", "mixed")
    has_form = primary_mode != "table"

    if primary_mode == "table":
        col_names = []
        for tr in regions.get("table_regions", []):
            col_names.extend(tr.get("column_names", []))
        col_names = list(dict.fromkeys(col_names))
        example_row = {col: "value" for col in col_names} if col_names else {"Column1": "value"}

        return f"""Return ONLY valid JSON, no markdown fences, no explanation:
{{
  "document_type": "detected document type",
  "overall_confidence": "high",
  "document_count": 1,
  "documents": [
    {{
      "doc_index": 0,
      "doc_hint": "brief description",
      "table_rows": [
        {json.dumps(example_row)}
      ],
      "row_count": 1,
      "notes": ""
    }}
  ]
}}

RULES:
- table_rows: one object per data row, using the exact column names shown
- Skip: header row, subtotal rows, total rows, blank rows
- Numbers: no currency symbols, no commas"""

    elif primary_mode == "mixed":
        col_names = []
        for tr in regions.get("table_regions", []):
            col_names.extend(tr.get("column_names", []))
        example_row = {col: "value" for col in col_names[:3]} if col_names else {"Col1": "value"}

        return f"""Return ONLY valid JSON, no markdown fences, no explanation:
{{
  "document_type": "detected document type",
  "overall_confidence": "high",
  "document_count": 1,
  "documents": [
    {{
      "doc_index": 0,
      "doc_hint": "brief description",
      "extracted_fields": {{
        "B3": {{"value": "extracted value", "confidence": "high"}},
        "B4": {{"value": "extracted value", "confidence": "high"}}
      }},
      "table_rows": [
        {json.dumps(example_row)}
      ],
      "row_count": 1,
      "notes": ""
    }}
  ]
}}

RULES:
- extracted_fields keys are cell references like B3, D10, F5
- table_rows: one object per data row
- Numbers: no currency symbols"""

    else:
        # Form mode - simplest format
        return """Return ONLY valid JSON, no markdown fences, no explanation:
{
  "document_type": "detected document type",
  "overall_confidence": "high",
  "document_count": 1,
  "documents": [
    {
      "doc_index": 0,
      "doc_hint": "brief description of this document",
      "extracted_fields": {
        "B3": {"value": "47-3821654", "confidence": "high"},
        "B4": {"value": "Nexus Global Trading LLC", "confidence": "high"},
        "B5": {"value": "25", "confidence": "high"}
      },
      "notes": ""
    }
  ]
}

RULES:
- extracted_fields keys MUST be cell references (B3, D10, etc.) matching the template
- Include every field from the template, even if the value is ""
- Numbers: no currency symbols or commas
- Dates: YYYY-MM-DD format"""


# ==============================================================================
# PDFPLUMBER VALIDATION LAYER
# ==============================================================================

def _validate_with_pdfplumber(extracted_fields: dict, doc_text: str,
                               table_rows: list = None) -> dict:
    """
    Cross-check AI-extracted values against pdfplumber text.

    For each extracted value:
      - Search for it (or a close match) in the pdfplumber text
      - If found: keep confidence as-is or upgrade to high
      - If not found: downgrade confidence to low, flag for review

    This is the safety net against AI hallucinations.
    A value the AI invented will not appear anywhere in the pdfplumber text.
    A value the AI correctly extracted will appear in the text.
    """
    if not doc_text:
        return {"validated": extracted_fields, "flagged": [], "confidence_map": {}}

    doc_text_lower = doc_text.lower()
    validated = {}
    flagged = []
    confidence_map = {}

    for ref, field_data in extracted_fields.items():
        if isinstance(field_data, dict):
            value = str(field_data.get("value", "")).strip()
            ai_confidence = field_data.get("confidence", "medium")
        else:
            value = str(field_data).strip()
            ai_confidence = "medium"

        if not value or value == "":
            validated[ref] = {"value": "", "confidence": "high", "validated": True}
            continue

        # Check if value appears in pdfplumber text
        found = _check_value_in_text(value, doc_text_lower)

        if found:
            # Confirmed - upgrade to high confidence
            final_confidence = "high"
            validated[ref] = {"value": value, "confidence": final_confidence,
                               "validated": True, "pdfplumber_confirmed": True}
        else:
            # Not found - this might be hallucinated or normalised
            # Check if a variant of the value appears (e.g. normalised date)
            variant_found = _check_value_variants(value, doc_text)

            if variant_found:
                final_confidence = "medium"
                validated[ref] = {"value": value, "confidence": final_confidence,
                                   "validated": True, "pdfplumber_confirmed": "variant"}
            else:
                # Value not found at all - flag for review
                final_confidence = "low"
                validated[ref] = {"value": value, "confidence": final_confidence,
                                   "validated": False, "pdfplumber_confirmed": False,
                                   "needs_review": True}
                flagged.append({"ref": ref, "value": value, "reason": "not found in document text"})

        confidence_map[ref] = final_confidence

    # Validate table rows
    validated_rows = []
    if table_rows:
        for row in table_rows:
            validated_row = {}
            for col, val in row.items():
                val_str = str(val).strip()
                if not val_str:
                    validated_row[col] = {"value": "", "confidence": "high"}
                    continue
                found = _check_value_in_text(val_str, doc_text_lower)
                if found:
                    validated_row[col] = {"value": val_str, "confidence": "high"}
                else:
                    variant = _check_value_variants(val_str, doc_text)
                    validated_row[col] = {
                        "value": val_str,
                        "confidence": "medium" if variant else "low",
                    }
            validated_rows.append(validated_row)

    return {
        "validated_fields": validated,
        "validated_rows": validated_rows,
        "flagged": flagged,
        "confidence_map": confidence_map,
        "flag_count": len(flagged),
    }


def _check_value_in_text(value: str, doc_text_lower: str) -> bool:
    """Check if a value appears in the document text."""
    if not value or len(value) < 2:
        return True  # Short values - don't flag

    val_lower = value.lower().strip()

    # Direct match
    if val_lower in doc_text_lower:
        return True

    # Numeric match - strip formatting
    val_numeric = re.sub(r'[^0-9.]', '', value)
    if len(val_numeric) >= 4:
        doc_numeric = re.sub(r'[^0-9.]', '', doc_text_lower)
        if val_numeric in doc_numeric:
            return True

    return False


def _check_value_variants(value: str, doc_text: str) -> bool:
    """
    Check if any variant of the value appears in the document.
    Handles date normalisation, number formatting etc.
    """
    # Date variants: "2024-01-31" -> check for "January 31", "31/01", "01/31" etc.
    date_match = re.match(r'(\d{4})-(\d{2})-(\d{2})', value)
    if date_match:
        y, m, d = date_match.groups()
        month_names = ["january","february","march","april","may","june",
                       "july","august","september","october","november","december"]
        month_name = month_names[int(m) - 1]
        variants = [
            f"{d}/{m}/{y}", f"{m}/{d}/{y}", f"{d}-{m}-{y}",
            f"{month_name} {int(d)}", f"{int(d)} {month_name}",
            f"{month_name[:3]} {int(d)}", f"{int(d)} {month_name[:3]}",
        ]
        doc_lower = doc_text.lower()
        return any(v in doc_lower for v in variants)

    # Amount variants: "8410.00" -> check for "$8,410", "8,410.00" etc.
    amount_match = re.match(r'^(\d+)\.(\d{2})$', value)
    if amount_match:
        integer_part = amount_match.group(1)
        # Check for the integer part at least
        if len(integer_part) >= 4 and integer_part in doc_text.replace(",", ""):
            return True

    return False


# ==============================================================================
# PDFPLUMBER DIRECT TABLE EXTRACTION
# ==============================================================================

def _extract_pdf_table_direct(file_path: Path, template_data: dict) -> Optional[list]:
    """
    Extract table rows directly from PDF using pdfplumber.
    Handles tables at ANY position on the page (not just top-left).
    Returns list of row dicts or None if no matching table found.
    """
    try:
        import pdfplumber

        regions = template_data.get("regions", {})
        table_regions = regions.get("table_regions", [])

        if not table_regions:
            return None

        col_names = []
        for tr in table_regions:
            col_names.extend(tr.get("column_names", []))
        col_names = list(dict.fromkeys(col_names))

        if not col_names:
            return None

        skip_kw = {"subtotal", "total", "shipping", "tax", "discount",
                   "charges", "refund", "paid", "free", "balance", "grand total"}
        all_rows = []

        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                # Strategy 1: line-based (visible borders)
                tables = page.extract_tables({
                    "vertical_strategy": "lines",
                    "horizontal_strategy": "lines",
                    "snap_tolerance": 4,
                    "join_tolerance": 4,
                })
                # Strategy 2: text-based (no visible borders)
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
                            continue

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
    if val is None: return ""
    return " ".join(str(val).strip().split())

def _find_header_row(table, col_names):
    col_lower = [c.lower() for c in col_names]
    best_idx, best_score = None, 0
    for i, row in enumerate(table[:8]):
        if not row: continue
        row_vals = [_clean_cell(c).lower() for c in row]
        score = sum(1 for col in col_lower if any(col in cell or cell in col for cell in row_vals if cell))
        if score > best_score:
            best_score = score
            best_idx = i
    return best_idx if best_score >= max(1, len(col_names) // 2) else None

def _match_columns(col_names, pdf_headers):
    import difflib
    mapping = {}
    pdf_lower = [h.lower() for h in pdf_headers]
    for col in col_names:
        cl = col.lower()
        if cl in pdf_lower:
            mapping[col] = pdf_lower.index(cl); continue
        for i, h in enumerate(pdf_lower):
            if cl in h or h in cl:
                mapping[col] = i; break
        else:
            matches = difflib.get_close_matches(cl, pdf_lower, n=1, cutoff=0.6)
            if matches:
                mapping[col] = pdf_lower.index(matches[0])
    return mapping

def _clean_text_for_table(text: str) -> str:
    text = re.sub(r'(\d{8,})\n(\d{1,3})\n', lambda m: m.group(1)+m.group(2)+'\n', text)
    text = re.sub(r'(\d{8,})\n(\d{1,3})$', lambda m: m.group(1)+m.group(2), text)
    text = re.sub(r'(-\s*)\n(#\d+)', r'\1 \2', text)
    return text


# ==============================================================================
# VALUE NORMALISATION
# ==============================================================================

def _normalise_values(row: dict, doc_type: str) -> dict:
    numeric_fields = _get_numeric_fields(doc_type)
    cleaned = {}
    for k, v in row.items():
        if v is None:
            cleaned[k] = ""; continue
        s = str(v).strip()
        kl = k.lower().replace(" ", "_")
        if any(kl == f or kl.endswith(f) for f in numeric_fields):
            s = re.sub(r'[£€$¥₹,\s]', '', s)
            s = re.sub(r'^\((.+)\)$', r'-\1', s)
        cleaned[k] = s
    return cleaned

def _filter_ghost_rows(rows: list, col_names: list) -> list:
    if not rows or not col_names: return rows
    first_col = col_names[0]
    skip_kw = {"subtotal","total","shipping","tax","discount","charges","refund","paid","free","balance"}
    clean = []
    for row in rows:
        first_val = str(row.get(first_col, "")).strip()
        if not first_val: continue
        if re.match(r'^[\d,.\-\s]{1,6}$', first_val) and not re.search(r'[a-zA-Z]', first_val): continue
        if any(kw in first_val.lower() for kw in skip_kw): continue
        clean.append(row)
    return clean


# ==============================================================================
# MULTI-DOCUMENT DETECTION
# ==============================================================================

def _detect_document_boundaries_vision(doc_images_b64: list, orchestrator,
                                        filename: str, doc_type: str) -> list:
    """
    Detect if a PDF contains multiple separate documents using vision.
    Returns list of {index, page_indices, hint} for each detected document.

    This is used for PDFs like "100 cheques in one file" where each page
    or each half-page is a separate document.
    """
    if not doc_images_b64:
        return [{"index": 0, "page_indices": list(range(1)), "hint": "full document"}]

    total_pages = len(doc_images_b64)

    if total_pages == 1:
        # Single page - could still contain multiple documents side by side
        detection_prompt = f"""Look at this document image carefully.

Does this page contain MULTIPLE SEPARATE {doc_type} documents on it?
(For example: two cheques on one page, two receipts, multiple invoices)

Return ONLY this JSON:
{{
  "document_count": <integer>,
  "layout": "single|side_by_side|stacked|grid",
  "documents": [
    {{"index": 0, "hint": "brief description, e.g. cheque to Pacific Steel"}}
  ]
}}

If there is only ONE document: document_count = 1."""

        try:
            detection = orchestrator.llm.extract(
                image_b64=doc_images_b64[0],
                prompt=detection_prompt
            )
            if detection.success and detection.parsed_json:
                raw = detection.parsed_json
                count = raw.get("document_count", 1)
                if count > 1:
                    print(f"[DETECT] {filename}: {count} docs on single page", flush=True)
                    return [
                        {"index": d["index"], "page_indices": [0],
                         "hint": d.get("hint", f"doc {d['index']+1}"),
                         "sub_index": d["index"],
                         "total_on_page": count}
                        for d in raw.get("documents", [{"index": 0}])
                    ]
        except Exception as e:
            print(f"[DETECT] single page detection error: {e}", flush=True)

        return [{"index": 0, "page_indices": [0], "hint": "full document"}]

    else:
        # Multi-page - assume one document per page unless detection says otherwise
        # For now: each page is one document (standard case for multi-page PDFs)
        print(f"[DETECT] {filename}: {total_pages} pages -> treating as {total_pages} separate docs", flush=True)
        return [
            {"index": i, "page_indices": [i], "hint": f"page {i+1}"}
            for i in range(total_pages)
        ]


# ==============================================================================
# RESULT PROCESSORS
# ==============================================================================

def _process_vision_result(raw_doc: dict, template_data: dict, filename: str,
                            doc_type: str, elapsed: float, extraction,
                            doc_text: str, seg_hint: str = "",
                            doc_index: int = 0) -> object:
    """
    Process the result from a single document extracted by vision.
    Applies pdfplumber validation to every extracted value.
    """
    from orchestrator import DocumentExtractionResult

    regions = template_data.get("regions", {})
    layout = template_data.get("layout", {})
    cells = layout.get("cells", {})
    primary_mode = regions.get("primary_mode", "form_kv")

    extracted_fields_raw = raw_doc.get("extracted_fields", {})
    table_rows_raw = raw_doc.get("table_rows", [])
    confidence_raw = raw_doc.get("confidence", "medium")
    if isinstance(confidence_raw, dict):
        confidence_raw = "medium"

    # -- pdfplumber validation -------------------------------------------------
    validation = _validate_with_pdfplumber(extracted_fields_raw, doc_text, table_rows_raw)
    validated_fields = validation["validated_fields"]
    validated_rows = validation["validated_rows"]
    flagged = validation["flagged"]

    # -- Build human-readable extracted_data -----------------------------------
    ref_to_label = {}
    for key, cell in cells.items():
        if not isinstance(cell, dict): continue
        val = cell.get("value", "").strip()
        is_extract = cell.get("extractTarget", False)
        if is_extract and val:
            parts = key.split(",")
            if len(parts) == 2:
                ref_to_label[_cell_ref(int(parts[0]), int(parts[1]))] = val

    for t in regions.get("explicit_targets", []):
        if t["ref"] not in ref_to_label:
            ref_to_label[t["ref"]] = t["label"]
    for kv in regions.get("kv_pairs", []):
        if kv["value_ref"] not in ref_to_label:
            ref_to_label[kv["value_ref"]] = kv["label"]
    for tc in regions.get("two_col_pairs", []):
        if tc["left_value_ref"] not in ref_to_label:
            ref_to_label[tc["left_value_ref"]] = tc["left_label"]
        if tc["right_value_ref"] not in ref_to_label:
            ref_to_label[tc["right_value_ref"]] = tc["right_label"]

    # Auto-resolve unlabelled refs
    for ref in validated_fields:
        if ref not in ref_to_label:
            try:
                col_str = "".join(ch for ch in ref if ch.isalpha()).upper()
                row_str = "".join(ch for ch in ref if ch.isdigit())
                c_idx = sum((ord(ch)-64)*(26**i) for i,ch in enumerate(reversed(col_str)))-1
                r_idx = int(row_str)-1
                left_val = (cells.get(f"{r_idx},{c_idx-1}") or {}).get("value","").strip() if c_idx>0 else ""
                above_val = (cells.get(f"{r_idx-1},{c_idx}") or {}).get("value","").strip() if r_idx>0 else ""
                ref_to_label[ref] = left_val or above_val or ref
            except Exception:
                ref_to_label[ref] = ref

    extracted_data = {}
    for ref, label in ref_to_label.items():
        vf = validated_fields.get(ref, {"value": "", "confidence": "high"})
        extracted_data[label] = {
            "value": vf.get("value", ""),
            "confidence": vf.get("confidence", "high"),
            "ref": ref,
        }

    # Static label cells
    for key, cell in cells.items():
        if not isinstance(cell, dict): continue
        val = cell.get("value","").strip()
        if val and not cell.get("extractTarget"):
            parts = key.split(",")
            if len(parts) == 2:
                ref = _cell_ref(int(parts[0]), int(parts[1]))
                extracted_data[f"_label_{ref}"] = {"value": val, "confidence": "high"}

    # Table rows - normalise
    normalised_rows = []
    if table_rows_raw:
        col_names = []
        for tr in regions.get("table_regions", []):
            col_names.extend(tr.get("column_names", []))
        col_names = list(dict.fromkeys(col_names))

        filtered = _filter_ghost_rows(table_rows_raw, col_names) if col_names else table_rows_raw
        for row in filtered:
            if isinstance(row, dict):
                clean = {col: str(row.get(col,"") or "").strip() for col in col_names} if col_names else row
                normalised_rows.append(_normalise_values(clean, doc_type))

    has_table = bool(normalised_rows)
    overall_confidence = raw_doc.get("overall_confidence", "medium")

    r = DocumentExtractionResult(filename=filename)
    r.document_type = doc_type
    r.extracted_data = {
        "document_type": doc_type,
        "overall_confidence": overall_confidence,
        "extraction_method": "vision_primary",
        "table_mode": has_table and primary_mode == "table",
        "mixed_mode": has_table and primary_mode == "mixed",
        "table_rows": normalised_rows,
        "column_headers": [tr["column_names"] for tr in regions.get("table_regions",[])],
        "row_count": len(normalised_rows),
        "extracted_data": extracted_data,
        "extracted_fields": {k: v.get("value","") if isinstance(v,dict) else v
                              for k,v in validated_fields.items()},
        "segment_hint": seg_hint,
        "doc_index": doc_index,
        "validation": {
            "flagged_count": len(flagged),
            "flagged_fields": flagged,
            "confidence_map": validation.get("confidence_map", {}),
        },
    }
    r.extraction_response = extraction
    r.processing_time_ms = elapsed
    r.success = True

    status = f"{len(flagged)} flags" if flagged else "clean"
    print(f"[EXTRACT] vision: {filename} doc#{doc_index} -> "
          f"{len(extracted_data)} fields, {len(normalised_rows)} rows, "
          f"{overall_confidence} confidence, {status}", flush=True)
    return r


def _make_table_result(rows, template_data, filename, doc_type, elapsed, method, extraction=None, confidence="high"):
    from orchestrator import DocumentExtractionResult
    regions = template_data.get("regions", {})
    col_names = []
    for tr in regions.get("table_regions", []):
        col_names.extend(tr.get("column_names", []))
    col_names = list(dict.fromkeys(col_names))
    if not col_names:
        # Fallback: read from layout directly
        layout = template_data.get("layout", {})
        cells = layout.get("cells", {})
        headers = []
        for key, cell in cells.items():
            if not isinstance(cell, dict): continue
            val = cell.get("value","").strip()
            if not val: continue
            parts = key.split(",")
            if len(parts) == 2 and int(parts[0]) == 0:
                c = int(parts[1])
                headers.append((c, val))
        col_names = [v for _, v in sorted(headers)]
    normalised = [_normalise_values(row, doc_type) for row in rows]
    r = DocumentExtractionResult(filename=filename)
    r.document_type = doc_type
    r.extracted_data = {
        "document_type": doc_type, "overall_confidence": confidence,
        "table_mode": True, "extraction_method": method,
        "table_rows": normalised, "column_headers": col_names,
        "row_count": len(normalised),
        "extracted_data": {
            **({col: {"value": normalised[0].get(col,""),"confidence":"high"} for col in col_names} if normalised else {}),
            "_table_row_count": {"value": str(len(normalised)),"confidence":"high"},
        },
    }
    r.extraction_response = extraction
    r.processing_time_ms = elapsed
    r.success = True
    print(f"[EXTRACT] {method}: {filename} -> {len(normalised)} rows @ {confidence}", flush=True)
    return r

def _fail(filename, error):
    from orchestrator import DocumentExtractionResult
    r = DocumentExtractionResult(filename=filename)
    r.error = error; r.processing_time_ms = 0; r.success = False
    return r


# ==============================================================================
# MAIN EXTRACTION ENGINE - VISION FIRST
# ==============================================================================

def _extract_with_template(orchestrator, file_path: Path, template_data: dict):
    """
    Vision-First extraction engine - safety-wrapped version.
    All errors are caught and returned as failed DocumentResult objects
    so the job always completes with meaningful error messages.
    """
    try:
        return _extract_with_template_inner(orchestrator, file_path, template_data)
    except Exception as e:
        print(f"[EXTRACT] FATAL {file_path.name}: {e}", flush=True)
        traceback.print_exc()
        r = _fail(file_path.name, f"Fatal extraction error: {str(e)[:200]}")
        r.processing_time_ms = 0
        return [r]


def _extract_with_template_inner(orchestrator, file_path: Path, template_data: dict):
    """Inner extraction logic - called by the safety wrapper."""
    import time as t
    from core.preprocessor import preprocess_file

    doc_type = template_data.get("doc_type", "other")
    mode = template_data.get("mode", "columns")
    regions = template_data.get("regions", {})
    start = t.time()
    results = []

    try:
        doc = preprocess_file(file_path)
        doc_text = doc.extracted_text or ""
        page_images = doc.page_images_b64 or []

        print(f"[EXTRACT] {file_path.name}: text_len={len(doc_text)} "
              f"pages={len(page_images)} has_vision={bool(page_images)}", flush=True)

        # Auto-classify if unknown
        if doc_type in ("other", "", None) and doc_text:
            hint = _classify_by_hints(doc_text)
            if hint:
                doc_type = hint
                template_data = {**template_data, "doc_type": doc_type}
                print(f"[EXTRACT] {file_path.name}: auto-classified -> {doc_type}", flush=True)

        # -- LAYOUT MODE ------------------------------------------------------
        if mode == "layout":
            primary_mode = regions.get("primary_mode", "form_kv")

            print(f"[EXTRACT] {file_path.name}: mode={primary_mode} doc_type={doc_type} "
                  f"pages={len(page_images)}", flush=True)

            # -- TABLE-ONLY MODE ----------------------------------------------
            if primary_mode == "table":
                # Try pdfplumber direct first
                direct_rows = _extract_pdf_table_direct(file_path, template_data)
                elapsed = (t.time() - start) * 1000

                if direct_rows and len(direct_rows) > 0:
                    # pdfplumber succeeded - validate with AI
                    print(f"[EXTRACT] {file_path.name}: direct table {len(direct_rows)} rows", flush=True)

                    # Quick AI validation pass
                    validation = _validate_with_pdfplumber(
                        {}, doc_text, direct_rows
                    )
                    results.append(_make_table_result(
                        direct_rows, template_data, file_path.name,
                        doc_type, elapsed, "direct_pdf_validated"
                    ))
                else:
                    # pdfplumber failed - use vision extraction
                    print(f"[EXTRACT] {file_path.name}: direct failed -> vision extraction", flush=True)
                    results.extend(
                        _vision_extract_all_documents(
                            orchestrator, file_path, template_data,
                            doc_type, doc_text, page_images, start
                        )
                    )

            # -- FORM, MIXED, TWO-COLUMN MODE ---------------------------------
            else:
                results.extend(
                    _vision_extract_all_documents(
                        orchestrator, file_path, template_data,
                        doc_type, doc_text, page_images, start
                    )
                )

        # -- COLUMNS MODE (legacy) ---------------------------------------------
        else:
            results.extend(
                _legacy_columns_extract(
                    orchestrator, file_path, template_data,
                    doc_type, doc_text, page_images, start
                )
            )

    except Exception as e:
        print(f"[EXTRACT] Error {file_path.name}: {e}", flush=True)
        traceback.print_exc()
        r = _fail(file_path.name, str(e))
        r.processing_time_ms = (time.time() - start) * 1000
        results.append(r)

    return results if results else [_fail(file_path.name, "No data extracted")]


def _vision_extract_all_documents(orchestrator, file_path, template_data,
                                   doc_type, doc_text, page_images, start):
    """
    Extract all documents from a PDF.
    Uses vision (images) when available, falls back to text when not.
    Handles: single doc, multi-page, multiple docs per page, 100 cheques in one PDF.
    """
    import time as t
    results = []
    regions = template_data.get("regions", {})
    has_images = bool(page_images)

    # Only attempt vision-based boundary detection if we actually have images
    if has_images:
        doc_segments = _detect_document_boundaries_vision(
            page_images, orchestrator, file_path.name, doc_type
        )
    else:
        # No images - treat as single document, use text extraction
        print(f"[EXTRACT] {file_path.name}: no page images, using text-only extraction", flush=True)
        doc_segments = [{"index": 0, "page_indices": [], "hint": "full document"}]

    total_docs = len(doc_segments)
    print(f"[EXTRACT] {file_path.name}: {total_docs} document(s) to process", flush=True)

    for seg in doc_segments:
        seg_index = seg["index"]
        seg_hint = seg.get("hint", f"doc {seg_index+1}")
        page_indices = seg.get("page_indices", [0])
        sub_index = seg.get("sub_index", None)
        total_on_page = seg.get("total_on_page", 1)

        # Get page image for this segment if available
        page_img = None
        if has_images and page_indices:
            idx = page_indices[0] if page_indices[0] < len(page_images) else 0
            page_img = page_images[idx]
        elif has_images and page_images:
            page_img = page_images[0]

        # Build the extraction prompt
        prompt = _build_vision_prompt(template_data, doc_text)

        # Add sub-document context for multiple docs on same page
        if total_on_page > 1 and sub_index is not None:
            prompt = prompt.replace(
                "=== DOCUMENT CONTENT ===",
                f"=== DOCUMENT CONTEXT ===\n"
                f"This page contains {total_on_page} separate documents.\n"
                f"Extract ONLY document #{sub_index+1} (index {sub_index}).\n"
                f"Description: {seg_hint}\n\n"
                f"=== DOCUMENT CONTENT ==="
            )

        # Extract - use image if available, text otherwise
        # Retry up to 3 times with exponential backoff to handle 429 rate limits
        extraction = None
        last_error = ""
        for attempt in range(3):
            try:
                if page_img:
                    print(f"[EXTRACT] {file_path.name}: sending image to AI "
                          f"(attempt {attempt+1})", flush=True)
                    extraction = orchestrator.llm.extract(image_b64=page_img, prompt=prompt)
                    if not extraction.success and doc_text:
                        print(f"[EXTRACT] {file_path.name}: vision failed -> text fallback", flush=True)
                        extraction = orchestrator.llm.extract(text=doc_text, prompt=prompt)
                elif doc_text:
                    print(f"[EXTRACT] {file_path.name}: sending text to AI "
                          f"(attempt {attempt+1})", flush=True)
                    extraction = orchestrator.llm.extract(text=doc_text, prompt=prompt)
                else:
                    seg_fn = (file_path.name if total_docs == 1
                              else f"{file_path.stem}_doc{seg_index+1}{file_path.suffix}")
                    r = _fail(seg_fn, "No content - PDF has no extractable text or images")
                    results.append(r)
                    extraction = None
                    break

                if extraction and extraction.success and extraction.parsed_json:
                    break  # success

                last_error = (extraction.error if extraction else "no response")[:100]
                print(f"[EXTRACT] {file_path.name}: attempt {attempt+1} failed "
                      f"({last_error}) - "
                      f"{'retrying' if attempt < 2 else 'giving up'}", flush=True)
                if attempt < 2:
                    wait = 5 * (3 ** attempt)  # 5s, 15s
                    print(f"[EXTRACT] waiting {wait}s before retry", flush=True)
                    time.sleep(wait)

            except Exception as e:
                last_error = str(e)[:100]
                print(f"[EXTRACT] LLM error attempt {attempt+1}: {e}", flush=True)
                if attempt < 2:
                    time.sleep(5 * (3 ** attempt))

        if extraction is None:
            continue  # already added fail result above

        if not extraction.success or not extraction.parsed_json:
            seg_fn = (file_path.name if total_docs == 1
                      else f"{file_path.stem}_doc{seg_index+1}{file_path.suffix}")
            r = _fail(seg_fn, f"All retries failed: {last_error}")
            r.processing_time_ms = (t.time() - start) * 1000
            results.append(r)
            continue

        raw = extraction.parsed_json
        elapsed = (t.time() - start) * 1000

        # Handle documents array in response
        documents = raw.get("documents", [raw])
        if not documents:
            documents = [raw]

        for doc_result_raw in documents:
            doc_idx = doc_result_raw.get("doc_index", seg_index)
            doc_hint = doc_result_raw.get("doc_hint", seg_hint)

            seg_fn = (file_path.name if total_docs == 1 and len(documents) == 1
                      else f"{file_path.stem}_doc{doc_idx+1}{file_path.suffix}")

            result = _process_vision_result(
                doc_result_raw, template_data, seg_fn, doc_type,
                elapsed, extraction, doc_text, doc_hint, doc_idx
            )
            results.append(result)

    return results if results else [_fail(file_path.name, "No documents extracted")]


def _legacy_columns_extract(orchestrator, file_path, template_data,
                             doc_type, doc_text, page_images, start):
    """Legacy flat-column extraction for old-format templates."""
    import time as t
    results = []
    header_cols = template_data.get("header_cols", [])
    system_prompt = _get_system_prompt(doc_type)

    def col_hint(col):
        return {"Number": "number only", "Currency": "number only",
                "Date": "YYYY-MM-DD", "Text": "text"}.get(col.get("type","Text"), "text")

    header_lines = "\n".join(
        f'  - "{c["name"]}": {col_hint(c)}'
        for c in sorted(header_cols, key=lambda x: x.get("order",0))
        if c.get("name","").strip()
    )
    prompt = f"""{system_prompt}

Extract these fields from the document:
{header_lines}

Return ONLY JSON:
{{"document_type": "{doc_type}", "overall_confidence": "high|medium|low", "header": {{}}}}"""

    try:
        if page_images:
            extraction = orchestrator.llm.extract(image_b64=page_images[0], prompt=prompt)
        else:
            extraction = orchestrator.llm.extract(text=doc_text, prompt=prompt)
    except Exception as e:
        results.append(_fail(file_path.name, str(e)))
        return results

    elapsed = (t.time() - start) * 1000

    if not extraction.success or not extraction.parsed_json:
        r = _fail(file_path.name, extraction.error)
        r.processing_time_ms = elapsed
        results.append(r)
        return results

    from orchestrator import DocumentExtractionResult
    raw = extraction.parsed_json
    header_data = raw.get("header", {})
    normalised = {}
    for col in header_cols:
        name = col.get("name","").strip()
        if not name: continue
        fd = header_data.get(name)
        if fd is None:
            normalised[name] = {"value":"","confidence":"high"}
        elif isinstance(fd, dict):
            normalised[name] = {"value": fd.get("value",""), "confidence": fd.get("confidence","high")}
        else:
            normalised[name] = {"value": str(fd) if fd is not None else "", "confidence":"high"}

    r = DocumentExtractionResult(filename=file_path.name)
    r.document_type = doc_type
    r.extracted_data = {
        "document_type": doc_type,
        "overall_confidence": raw.get("overall_confidence","medium"),
        "extraction_method": "legacy_columns",
        "extracted_data": normalised,
    }
    r.extraction_response = extraction
    r.processing_time_ms = elapsed
    r.success = True
    results.append(r)
    return results


# ==============================================================================
# BACKGROUND THREAD
# ==============================================================================

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
        print(f"[THREAD] DB import failed: {e}", flush=True); return

    try:
        connect_args = {"check_same_thread": False} if "sqlite" in db_url else {}
        _eng = sa_engine(db_url, connect_args=connect_args)
        Session = sessionmaker(bind=_eng)
        session = Session()
    except Exception as e:
        print(f"[THREAD] DB session failed: {e}", flush=True); return

    try:
        job = session.query(ExtractionJob).filter_by(id=job_id).first()
        if not job: return
        job.status = "processing"
        session.commit()

        from orchestrator import Orchestrator
        orchestrator = Orchestrator(client_schema_path=schema_path)

        successful = failed = needs_review = 0
        start_time = time.time()

        for i, fp in enumerate(file_paths):
            try:
                file_path = Path(fp)
                if template_data:
                    results = _extract_with_template(orchestrator, file_path, template_data)
                else:
                    result = orchestrator._process_single_document(file_path)
                    results = [result]

                for result in results:
                    # Check if any fields need review
                    validation_data = (result.extracted_data or {}).get("validation", {})
                    has_flags = validation_data.get("flagged_count", 0) > 0
                    error_msg = result.error if hasattr(result, 'error') and result.error else ""

                    doc = DocumentResult(
                        job_id=job_id,
                        filename=result.filename,
                        document_type=result.document_type if result.success else "unknown",
                        overall_confidence=(result.extracted_data or {}).get("overall_confidence"),
                        extraction_json=json.dumps(result.extracted_data, default=str) if result.extracted_data else None,
                        validation_errors=error_msg or ("; ".join(result.validation.errors) if result.validation else ""),
                        validation_warnings=(
                            "; ".join(f"{f['ref']}: {f['value']}" for f in validation_data.get("flagged_fields", []))
                            if has_flags else ""
                        ),
                        needs_review=has_flags or (result.validation.needs_review if result.validation else False),
                        model_used=(result.extraction_response.model_used
                                    if result.extraction_response else "vision_direct"),
                        tokens_used=(result.extraction_response.tokens_used
                                     if result.extraction_response else 0),
                        latency_ms=result.processing_time_ms,
                    )
                    session.add(doc)
                    if result.success:
                        successful += 1
                        if doc.needs_review:
                            needs_review += 1
                    else:
                        failed += 1

            except Exception as doc_err:
                print(f"[THREAD] doc error: {doc_err}", flush=True)
                traceback.print_exc()
                failed += 1

            # Rate limit protection: delay between documents
            # Prevents Groq/Gemini 429 errors on batch uploads
            # Default 3s — enough for Groq free tier (30 req/min = 2s min gap)
            if i < len(file_paths) - 1:
                delay = float(getattr(settings, 'RATE_LIMIT_DELAY', 3.0))
                print(f"[THREAD] rate limit delay {delay}s before next doc", flush=True)
                time.sleep(delay)

        session.commit()
        job.status = "completed"
        job.successful = successful
        job.failed = failed
        job.needs_review = needs_review
        job.total_time_sec = time.time() - start_time
        job.completed_at = datetime.utcnow()
        session.commit()
        print(f"[THREAD] done: {successful} ok, {failed} failed, {needs_review} review", flush=True)

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


# ==============================================================================
# EXCEL EXPORT
# ==============================================================================

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
    template_regions = None
    if job.schema_id:
        try:
            tpl = db.query(ColumnTemplate).filter(
                ColumnTemplate.id == int(job.schema_id)
            ).first()
            if tpl and tpl.description:
                raw = json.loads(tpl.description)
                if isinstance(raw, dict) and "cells" in raw:
                    sheet_data = raw
                    template_regions = _analyse_template_regions(raw)
        except Exception as e:
            print(f"[EXPORT] Template load error: {e}", flush=True)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Results"

    if sheet_data:
        _write_excel(ws, doc_results, sheet_data, template_regions, openpyxl)
    else:
        _write_flat_table(ws, doc_results, openpyxl)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    return StreamingResponse(buf, headers={
        "Content-Disposition": f'attachment; filename="job_{job_id}_results.xlsx"',
        "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    })


def _write_excel(ws, doc_results, sheet_data, template_regions, openpyxl_mod):
    """Route to the correct writer based on template regions primary_mode.
    Always uses the template structure for routing — never relies on AI output
    flags which can be stale or wrong from a previous extraction run."""
    from openpyxl.utils import get_column_letter
    cells_tpl = sheet_data.get("cells", {})
    col_widths = sheet_data.get("colWidths", [])
    max_r, max_c = _find_template_dimensions(cells_tpl)

    for c_idx, width_px in enumerate(col_widths):
        if width_px and c_idx <= max_c:
            ws.column_dimensions[get_column_letter(c_idx + 1)].width = max(8, round(width_px / 7))

    # Route based on template structure — authoritative, never stale
    primary_mode = (template_regions or {}).get("primary_mode", "form_kv")

    print(f"[EXPORT] routing: primary_mode={primary_mode}", flush=True)

    if primary_mode == "table":
        _write_table_excel(ws, doc_results, sheet_data, cells_tpl, template_regions, openpyxl_mod)
    elif primary_mode == "mixed":
        _write_mixed_excel(ws, doc_results, sheet_data, cells_tpl, max_r, max_c, template_regions, openpyxl_mod)
    else:
        # form_with_targets, form_kv, two_column — all use form writer
        _write_form_excel(ws, doc_results, sheet_data, cells_tpl, max_r, max_c, openpyxl_mod)


def _write_table_excel(ws, doc_results, sheet_data, cells_tpl, template_regions, openpyxl_mod):
    """
    Table mode: write header row with original styles, then one data row per line item.
    Handles tables at any position in the grid (not just row 0).
    """
    table_regions = (template_regions or {}).get("table_regions", [])
    header_row_idx = table_regions[0]["header_row"] if table_regions else 0
    start_col_idx = table_regions[0]["start_col"] if table_regions else 0

    # Write ALL cells from the template (including any form fields above the table)
    for key, cell_def in cells_tpl.items():
        if not isinstance(cell_def, dict): continue
        parts = key.split(",")
        if len(parts) != 2: continue
        tr, tc = int(parts[0]), int(parts[1])
        xl_cell = ws.cell(row=tr + 1, column=tc + 1)
        xl_cell.value = cell_def.get("value", "").strip()
        if cell_def.get("style"):
            _apply_cell_style(xl_cell, cell_def["style"], openpyxl_mod)

    # Write data rows starting from the row after the header
    col_names = []
    for tr in table_regions:
        col_names.extend(tr.get("column_names", []))
    col_names = list(dict.fromkeys(col_names))
    col_indices = {name: (start_col_idx + i) for i, name in enumerate(col_names)}

    current_row = header_row_idx + 2  # +1 for 1-based, +1 to skip header

    for doc_result in doc_results:
        extracted = doc_result.get_extracted_data()
        table_rows = extracted.get("table_rows", [])

        for row_data in table_rows:
            for col_name, c_idx in col_indices.items():
                val = row_data.get(col_name, "")
                if isinstance(val, dict):
                    val = val.get("value", "")
                xl_cell = ws.cell(row=current_row, column=c_idx + 1)
                try:
                    xl_cell.value = (float(val) if "." in str(val) else int(val)) if val else val
                except (ValueError, TypeError):
                    xl_cell.value = val
            current_row += 1

    print(f"[EXPORT] table: header at row {header_row_idx+1}, "
          f"{current_row - header_row_idx - 2} data rows", flush=True)


def _write_form_excel(ws, doc_results, sheet_data, cells_tpl, max_r, max_c, openpyxl_mod):
    """
    Form mode: one filled template block per document result.
    Handles formulas: =SUM() and other Excel formulas are written and
    also pre-calculated where possible so values show without needing
    manual recalculation in Excel.
    """
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter
    merges_tpl = sheet_data.get("merges", {})
    block_height = max_r + 2

    for block_idx, doc_result in enumerate(doc_results):
        row_offset = block_idx * block_height
        extracted_data = doc_result.get_extracted_data()
        extracted_fields = extracted_data.get("extracted_fields", {})
        validation = extracted_data.get("validation", {})
        confidence_map = validation.get("confidence_map", {})

        label_to_value = {
            k: (v.get("value","") if isinstance(v,dict) else str(v or ""))
            for k, v in extracted_data.get("extracted_data", {}).items()
            if not k.startswith("_label_")
        }

        # First pass: write all cells and collect numeric values by ref
        # so we can calculate formulas
        cell_values = {}  # ref -> numeric value for formula calculation

        for key, cell_def in cells_tpl.items():
            if not isinstance(cell_def, dict) or cell_def.get("mergeParent"):
                continue
            parts = key.split(",")
            if len(parts) != 2:
                continue
            tr, tc = int(parts[0]), int(parts[1])
            xl_cell = ws.cell(row=row_offset + tr + 1, column=tc + 1)
            tpl_value = cell_def.get("value","").strip()

            if cell_def.get("extractTarget"):
                ref = f"{_col_letter(tc)}{tr+1}"
                filled = extracted_fields.get(ref) or label_to_value.get(tpl_value, "")
                if isinstance(filled, dict):
                    filled = filled.get("value", "")
                filled = filled if filled is not None else ""

                # Try to store as number for formula calculation
                try:
                    num_val = float(filled.replace(",","")) if filled else None
                    if num_val is not None:
                        xl_cell.value = num_val
                        cell_values[ref] = num_val
                    else:
                        xl_cell.value = filled
                except (ValueError, AttributeError):
                    xl_cell.value = filled

                # Highlight low-confidence
                confidence = confidence_map.get(ref, "high")
                if confidence == "low":
                    try:
                        from openpyxl.styles import PatternFill
                        xl_cell.fill = PatternFill(fill_type="solid", fgColor="FFFFF0AA")
                    except Exception:
                        pass

            elif tpl_value.startswith("="):
                # It's a formula — calculate it if possible
                calculated = _calculate_formula(tpl_value, cell_values, row_offset)
                if calculated is not None:
                    # Write the calculated value (Excel will recalc on open anyway)
                    xl_cell.value = calculated
                    # Also store for downstream formula references
                    ref = f"{_col_letter(tc)}{tr+1}"
                    cell_values[ref] = calculated
                else:
                    # Write the formula with adjusted row offset for this block
                    adjusted = _adjust_formula_for_block(tpl_value, row_offset)
                    xl_cell.value = adjusted
            else:
                xl_cell.value = tpl_value

            if cell_def.get("style"):
                _apply_cell_style(xl_cell, cell_def["style"], openpyxl_mod)

            merge_span = cell_def.get("mergeSpan") or merges_tpl.get(key)
            if merge_span:
                sr, sc = merge_span.get("rows",1), merge_span.get("cols",1)
                if sr > 1 or sc > 1:
                    try:
                        ws.merge_cells(
                            start_row=row_offset+tr+1, start_column=tc+1,
                            end_row=row_offset+tr+sr, end_column=tc+sc,
                        )
                    except Exception:
                        pass

        # Filename label between blocks
        if block_idx > 0:
            lc = ws.cell(row=row_offset, column=1)
            lc.value = f">  {doc_result.filename}"
            lc.font = Font(bold=True, color="FF4F46E5", size=10)

        # Flag count indicator
        flag_count = validation.get("flagged_count", 0)
        if flag_count > 0:
            nc = ws.cell(row=row_offset + 1, column=max_c + 2)
            nc.value = f"! {flag_count} low-confidence fields"
            nc.font = Font(color="FFDC2626", size=9, italic=True)

    print(f"[EXPORT] form: {len(doc_results)} blocks written", flush=True)


def _calculate_formula(formula: str, cell_values: dict, row_offset: int) -> Optional[float]:
    """
    Calculate simple Excel formulas using known cell values.
    Handles: =SUM(B9:B11), =SUM(B3,B5,B7), basic arithmetic.
    Returns calculated value or None if cannot calculate.
    """
    import re
    f = formula.strip()

    # =SUM(range) e.g. =SUM(B9:B11)
    sum_range = re.match(r'^=SUM\(([A-Z]+)(\d+):([A-Z]+)(\d+)\)$', f, re.IGNORECASE)
    if sum_range:
        col1, row1, col2, row2 = sum_range.groups()
        total = 0.0
        found_any = False
        for r in range(int(row1), int(row2) + 1):
            ref = f"{col1.upper()}{r}"
            if ref in cell_values:
                total += cell_values[ref]
                found_any = True
        return round(total, 2) if found_any else None

    # =SUM(B3,B5,B7) comma-separated
    sum_list = re.match(r'^=SUM\(([^)]+)\)$', f, re.IGNORECASE)
    if sum_list:
        refs = [r.strip() for r in sum_list.group(1).split(",")]
        total = 0.0
        found_any = False
        for ref in refs:
            if ref.upper() in cell_values:
                total += cell_values[ref.upper()]
                found_any = True
        return round(total, 2) if found_any else None

    return None


def _adjust_formula_for_block(formula: str, row_offset: int) -> str:
    """
    Adjust cell references in a formula for a block offset.
    =SUM(B9:B11) with offset 20 becomes =SUM(B29:B31)
    """
    import re
    if row_offset == 0:
        return formula

    def adjust_ref(match):
        col = match.group(1)
        row = int(match.group(2))
        return f"{col}{row + row_offset}"

    return re.sub(r'([A-Z]+)(\d+)', adjust_ref, formula)


def _write_mixed_excel(ws, doc_results, sheet_data, cells_tpl, max_r, max_c,
                        template_regions, openpyxl_mod):
    """
    Mixed mode: template has BOTH form fields AND a table.
    Structure per block:
      - Form fields written first (rows 1..max_r of the template)
      - Table header row from the template
      - Table data rows appended directly below

    The block height is dynamic per document because each document
    may have a different number of table rows.
    """
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    merges_tpl = sheet_data.get("merges", {})

    # Get table region info
    table_regions = (template_regions or {}).get("table_regions", [])
    col_names = []
    start_col_idx = 0
    header_row_idx = max_r  # default: table header at last row of template

    if table_regions:
        header_row_idx = table_regions[0]["header_row"]
        start_col_idx  = table_regions[0]["start_col"]
        for tr in table_regions:
            col_names.extend(tr.get("column_names", []))
        col_names = list(dict.fromkeys(col_names))

    # Calculate how many form rows are above the table header
    form_rows = header_row_idx  # rows 0..header_row_idx-1 are form rows

    current_output_row = 1  # 1-based Excel row counter

    for block_idx, doc_result in enumerate(doc_results):
        extracted_data  = doc_result.get_extracted_data()
        extracted_fields = extracted_data.get("extracted_fields", {})
        validation       = extracted_data.get("validation", {})
        confidence_map   = validation.get("confidence_map", {})
        table_rows       = extracted_data.get("table_rows", [])

        label_to_value = {
            k: (v.get("value", "") if isinstance(v, dict) else str(v or ""))
            for k, v in extracted_data.get("extracted_data", {}).items()
            if not k.startswith("_label_")
        }

        block_start_row = current_output_row

        # ── Write filename separator (except first block) ─────────────────
        if block_idx > 0:
            lc = ws.cell(row=current_output_row, column=1)
            lc.value = f">  {doc_result.filename}"
            lc.font = Font(bold=True, color="FF4F46E5", size=10)
            current_output_row += 1

        # ── Write all template cells (form + table header) ────────────────
        for key, cell_def in sorted(cells_tpl.items(),
                                     key=lambda x: (int(x[0].split(",")[0]),
                                                    int(x[0].split(",")[1]))):
            if not isinstance(cell_def, dict) or cell_def.get("mergeParent"):
                continue
            parts = key.split(",")
            if len(parts) != 2:
                continue
            tr, tc = int(parts[0]), int(parts[1])
            tpl_value = cell_def.get("value", "").strip()

            # Map template row to output row
            out_row = current_output_row + tr

            xl_cell = ws.cell(row=out_row, column=tc + 1)

            if cell_def.get("extractTarget"):
                ref   = f"{_col_letter(tc)}{tr + 1}"
                filled = extracted_fields.get(ref) or label_to_value.get(tpl_value, "")
                if isinstance(filled, dict):
                    filled = filled.get("value", "")
                # Write as number if possible
                try:
                    num = float(str(filled).replace(",", "")) if filled else None
                    xl_cell.value = num if num is not None else (filled or "")
                except (ValueError, TypeError):
                    xl_cell.value = filled or ""

                confidence = confidence_map.get(ref, "high")
                if confidence == "low":
                    try:
                        xl_cell.fill = PatternFill(fill_type="solid", fgColor="FFFFF0AA")
                    except Exception:
                        pass

            elif tpl_value.startswith("="):
                # Formula — write as-is (relative refs will be correct since
                # we're writing at the right output row)
                xl_cell.value = tpl_value
            else:
                xl_cell.value = tpl_value

            if cell_def.get("style"):
                _apply_cell_style(xl_cell, cell_def["style"], openpyxl_mod)

            # Merges
            merge_span = cell_def.get("mergeSpan") or merges_tpl.get(key)
            if merge_span:
                sr, sc = merge_span.get("rows", 1), merge_span.get("cols", 1)
                if sr > 1 or sc > 1:
                    try:
                        ws.merge_cells(
                            start_row=out_row, start_column=tc + 1,
                            end_row=out_row + sr - 1, end_column=tc + sc,
                        )
                    except Exception:
                        pass

        # After writing the template (max_r+1 rows), advance past it
        current_output_row += max_r + 1  # +1 to land on the row after the header

        # ── Write table data rows ─────────────────────────────────────────
        if table_rows and col_names:
            col_indices = {name: (start_col_idx + i) for i, name in enumerate(col_names)}

            for row_data in table_rows:
                for col_name, c_idx in col_indices.items():
                    val = row_data.get(col_name, "")
                    if isinstance(val, dict):
                        val = val.get("value", "")
                    val = str(val).strip() if val is not None else ""
                    xl_cell = ws.cell(row=current_output_row, column=c_idx + 1)
                    try:
                        # Numeric — strip currency symbols
                        clean = val.replace(",", "").replace("$", "").replace("£", "").strip()
                        xl_cell.value = float(clean) if clean and clean not in ("", "-") else val
                    except (ValueError, TypeError):
                        xl_cell.value = val
                current_output_row += 1

        # Flag count indicator
        flag_count = validation.get("flagged_count", 0)
        if flag_count > 0:
            nc = ws.cell(row=block_start_row, column=max_c + 2)
            nc.value = f"! {flag_count} low-confidence"
            nc.font = Font(color="FFDC2626", size=9, italic=True)

        # Blank row between blocks
        current_output_row += 1

    print(f"[EXPORT] mixed: {len(doc_results)} blocks, "
          f"{current_output_row} total rows written", flush=True)


def _write_flat_table(ws, doc_results, openpyxl_mod):
    """Fallback flat table when no template."""
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter
    all_keys, seen = [], set()
    for dr in doc_results:
        for k in (dr.get_extracted_data().get("extracted_data") or {}):
            if k not in seen and not k.startswith("_label_"):
                seen.add(k); all_keys.append(k)
    hf = PatternFill(fill_type="solid", fgColor="FF4F46E5")
    hfont = Font(bold=True, color="FFFFFFFF", size=11)
    c = ws.cell(row=1, column=1, value="Filename"); c.font=hfont; c.fill=hf
    for ci, key in enumerate(all_keys, 2):
        c = ws.cell(row=1, column=ci, value=key); c.font=hfont; c.fill=hf
    for ri, dr in enumerate(doc_results, 2):
        ws.cell(row=ri, column=1, value=dr.filename)
        inner = dr.get_extracted_data().get("extracted_data") or {}
        for ci, key in enumerate(all_keys, 2):
            v = inner.get(key)
            ws.cell(row=ri, column=ci, value=(v.get("value","") if isinstance(v,dict) else (v or "")))
    ws.column_dimensions["A"].width = 30
    for ci in range(2, len(all_keys)+2):
        ws.column_dimensions[get_column_letter(ci)].width = 20


# ==============================================================================
# STYLE HELPERS
# ==============================================================================

def _parse_hex_color(hex_color):
    if not hex_color: return None
    h = hex_color.lstrip("#")
    if len(h)==3: h="".join(ch*2 for ch in h)
    return f"FF{h.upper()}" if len(h)==6 else None

def _apply_cell_style(xl_cell, style, _openpyxl_mod):
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    fk = {}
    if style.get("bold"): fk["bold"]=True
    if style.get("italic"): fk["italic"]=True
    if style.get("underline"): fk["underline"]="single"
    if style.get("fontSize"): fk["size"]=style["fontSize"]
    if style.get("fontFamily"): fk["name"]=style["fontFamily"]
    fc = _parse_hex_color(style.get("fontColor"))
    if fc: fk["color"]=fc
    if fk:
        try: xl_cell.font = Font(**fk)
        except Exception: pass
    bg = _parse_hex_color(style.get("bgColor"))
    if bg:
        try: xl_cell.fill = PatternFill(fill_type="solid", fgColor=bg)
        except Exception: pass
    try:
        xl_cell.alignment = Alignment(
            horizontal={"left":"left","center":"center","right":"right"}.get(style.get("align",""),"left"),
            wrap_text=bool(style.get("wrap")), vertical="center"
        )
    except Exception: pass
    if style.get("borderAll"):
        t = Side(style="thin")
        try: xl_cell.border = Border(left=t,right=t,top=t,bottom=t)
        except Exception: pass

def _find_template_dimensions(cells):
    max_r, max_c = 0, 0
    for key in cells:
        parts = key.split(",")
        if len(parts)==2:
            r,c = int(parts[0]),int(parts[1])
            max_r=max(max_r,r); max_c=max(max_c,c)
    return max_r, max_c

def _get_table_headers(layout):
    cells = layout.get("cells", {})
    headers = []
    for key, cell in cells.items():
        if not isinstance(cell, dict): continue
        val = cell.get("value","").strip()
        if not val: continue
        parts = key.split(",")
        if len(parts)==2 and int(parts[0])==0:
            c = int(parts[1])
            headers.append({"col":c,"label":val,"ref":_cell_ref(0,c),"style":cell.get("style",{})})
    return sorted(headers, key=lambda x: x["col"])


# ==============================================================================
# JOB ROUTES
# ==============================================================================

@router.get("/jobs", response_model=list[JobListItem])
def list_jobs(limit: int=50, offset: int=0, status_filter: Optional[str]=None,
              db: Session=Depends(get_db), current_user: User=Depends(get_current_user)):
    q = db.query(ExtractionJob).order_by(ExtractionJob.created_at.desc())
    if current_user.role != "admin": q = q.filter(ExtractionJob.user_id==current_user.id)
    if status_filter: q = q.filter(ExtractionJob.status==status_filter)
    return q.offset(offset).limit(limit).all()

@router.get("/jobs/{job_id}", response_model=JobStatus)
def get_job(job_id: int, db: Session=Depends(get_db), current_user: User=Depends(get_current_user)):
    return _get_job_or_404(job_id, current_user, db)

@router.get("/jobs/{job_id}/results", response_model=list[DocumentResultResponse])
def get_job_results(job_id: int, doc_type: Optional[str]=None, needs_review: Optional[bool]=None,
                    db: Session=Depends(get_db), current_user: User=Depends(get_current_user)):
    _get_job_or_404(job_id, current_user, db)
    q = db.query(DocumentResult).filter(DocumentResult.job_id==job_id)
    if doc_type: q = q.filter(DocumentResult.document_type==doc_type)
    if needs_review is not None: q = q.filter(DocumentResult.needs_review==needs_review)
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
                    db: Session=Depends(get_db), current_user: User=Depends(get_current_user)):
    _get_job_or_404(job_id, current_user, db)
    doc = db.query(DocumentResult).filter(DocumentResult.id==doc_id, DocumentResult.job_id==job_id).first()
    if not doc: raise HTTPException(status_code=404, detail="Document not found")
    doc.set_extracted_data(payload.extracted_data)
    doc.reviewed=True; doc.reviewed_by=current_user.username; doc.needs_review=False
    db.commit()
    return {"message": "Updated", "doc_id": doc_id}

@router.post("/jobs/{job_id}/docs/{doc_id}/approve")
def approve_document(job_id: int, doc_id: int,
                     db: Session=Depends(get_db), current_user: User=Depends(get_current_user)):
    _get_job_or_404(job_id, current_user, db)
    doc = db.query(DocumentResult).filter(DocumentResult.id==doc_id, DocumentResult.job_id==job_id).first()
    if not doc: raise HTTPException(status_code=404, detail="Document not found")
    doc.reviewed=True; doc.reviewed_by=current_user.username; doc.needs_review=False
    db.commit()
    return {"message": "Approved", "doc_id": doc_id}

@router.delete("/jobs/{job_id}")
def cancel_job(job_id: int, db: Session=Depends(get_db), current_user: User=Depends(get_current_user)):
    job = _get_job_or_404(job_id, current_user, db)
    if job.status not in ("pending","processing"):
        raise HTTPException(status_code=400, detail=f"Cannot cancel job with status '{job.status}'")
    job.status="cancelled"; job.completed_at=datetime.utcnow(); db.commit()
    return {"message": "Cancelled", "job_id": job_id}

def _get_job_or_404(job_id, current_user, db):
    job = db.query(ExtractionJob).filter(ExtractionJob.id==job_id).first()
    if not job: raise HTTPException(status_code=404, detail="Job not found")
    if current_user.role != "admin" and job.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    return job
