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
import warnings
from pathlib import Path
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.core.auth import get_current_user
from app.core.demo import (check_upload_file, check_upload_quota,
                           check_uploads_enabled, filter_demo_history,
                           filter_options, is_demo_user, job_hidden_by_cutoff)
from app.core import demo_audit
from app.core.confidence import UNVERIFIED
from app.core.storage import get_storage
from app.models import get_db, User, ExtractionJob, DocumentResult, ColumnTemplate
from app.schemas.schemas import (
    JobStatus, JobListItem, DocumentResultResponse,
    DocumentUpdateRequest, ExtractUploadResponse, FieldEditRequest,
)

router = APIRouter(prefix="/api", tags=["extract"])

_backend_dir = Path(__file__).resolve().parent.parent.parent.parent
_project_dir = _backend_dir.parent
_engine_dir  = _backend_dir / "engine"

# The log policy's helpers live with the engine, which logs the most. Appended,
# not inserted: nothing on the path is shadowed before the routes insert the
# engine directory themselves.
if str(_engine_dir) not in sys.path:
    sys.path.append(str(_engine_dir))
from log_safety import doc_ref, exc_brief, print_safe_traceback  # noqa: E402
from cancellation import Cancelled, watching  # noqa: E402
# --split-reexports--
from app.services.excel_slot import (  # noqa: E402,F401  moved, re-exported
    _write_excel,
    _write_inferred_sheets,
    _write_slot_excel,
)
from app.services.excel_legacy import (  # noqa: E402,F401  moved, re-exported
    _adjust_formula_for_block,
    _calculate_formula,
    _write_flat_table,
    _write_form_excel,
    _write_layout_excel,
    _write_mixed_excel,
    _write_table_excel,
    _write_table_rows_fallback,
)
from app.services.excel_cells import (  # noqa: E402,F401  moved, re-exported
    _EDITOR_DEFAULT_COL_PX,
    _EXCEL_COMMENT_MAX,
    _FMT_PLAIN,
    _ID_LABEL,
    _MAX_COL_WIDTH,
    _MIN_COL_WIDTH,
    _QTY_LABEL,
    _add_review_legend,
    _apply_cell_style,
    _apply_template_merges,
    _calculate_layout,
    _find_template_dimensions,
    _fit_columns,
    _marks_or_off,
    _parse_hex_color,
    _ref_to_rowcol,
    _review_status_unknown,
    cell_format,
    coerce_cell_value,
    labels_an_identifier,
    provenance_edited_note,
    provenance_note,
    provenance_note_size,
)
from app.services.result_processing import (  # noqa: E402,F401  moved, re-exported
    _check_value_in_text,
    _check_value_variants,
    _clean_cell,
    _coerce_extracted_fields,
    _fail,
    _find_header_row,
    _fix_split_decimals,
    _fix_split_decimals_row,
    _job_error_message,
    _match_columns,
    _normalise_values,
    _normalize_field_values,
    _normalize_row_values,
    _normalize_value,
    _process_vision_result,
    _regions_to_jsonable,
    _validate_row_alignment,
    _validate_with_pdfplumber,
)
from app.services.vision_prompts import (  # noqa: E402,F401  moved, re-exported
    _CBM_FIELD_ALIASES,
    _TEMPLATE_UNDERSTANDING_SYSTEM,
    _build_extraction_instructions,
    _build_fields_description,
    _build_layout_prompt_parts,
    _build_output_format,
    _build_page_anchor_map,
    _build_verification_block,
    _build_vision_prompt,
    _smart_truncate,
)
from app.services.template_parsing import (  # noqa: E402,F401  moved, re-exported
    _FINANCIAL_SECTIONED_TYPES,
    _GENERIC_FINANCIAL_COL_WORDS,
    _analyse_template_regions,
    _cell_ref,
    _classify_by_hints,
    _col_letter,
    _compute_shape_for_grid,
    _detect_parallel_column_groups,
    _detect_section_context_risk,
    _detect_transposed_table,
    _get_numeric_fields,
    _get_system_prompt,
    _get_table_rules,
    _get_unguided_prompt,
    _load_registry,
    _parse_template,
)
from app.services.uploads import (  # noqa: E402,F401  moved, re-exported
    _IMAGE_EXTENSIONS,
    _IncomingUpload,
    _UPLOAD_IMAGE_FORMATS,
    _is_image_file,
    _load_image_as_png_bytes,
    _parse_selected_pages,
    _safe_upload_name,
    _unique_upload_name,
    _validate_upload_content,
)


# ==============================================================================
# PAGE COUNT ENDPOINT
# ==============================================================================


# ==============================================================================
# TENANCY — who a request is allowed to act as, and what it may use
# ==============================================================================
#
# Both helpers exist because the upload endpoint trusted the request body for
# two things it must not: which tenant the job belongs to, and which template
# it may extract with. They are shared with drive.py, which had the same two
# holes at its own doors.

def resolve_client_id(current_user, requested: Optional[str]) -> str:
    """The tenant a request acts as. From the token, not the body.

    A user with a client_id acts as that client, full stop — whatever the form
    says. The form value is not rejected, only ignored, and the difference is
    logged. Rejecting would be stricter but would break the app today: the
    Extract page derives its client_id from `schemas[0].client_id`, which is
    the first schema in a list, not the signed-in user's tenant. A 403 there
    would lock out exactly the tenanted users this is meant to protect.

    A super-admin (role=admin with NO client_id of their own) is the one case
    that may act for another tenant — they have no tenant to be pinned to, and
    operating on behalf of a client is their job. Their body value is honoured.
    """
    own = getattr(current_user, "client_id", None)
    if own:
        if requested and requested != own:
            print(f"[TENANCY] user {current_user.id} requested client_id="
                  f"{requested!r}; using own {own!r} from token", flush=True)
        return own
    from app.core.permissions import PLATFORM_ADMIN, role_of
    if role_of(current_user) == PLATFORM_ADMIN:
        if not requested:
            raise HTTPException(
                status_code=400,
                detail="client_id is required: a super-admin has no tenant of "
                       "their own, so the request must name the client it is for.")
        return requested
    raise HTTPException(status_code=403,
                        detail="This account is not assigned to a client.")


def load_template_for_user(db: Session, template_id: Optional[int], current_user):
    """A template the user is allowed to extract with, or an error.

    Previously the upload endpoint loaded any template by id with no check at
    all, and silently continued with NO template when the id did not exist —
    so a wrong id quietly changed the extraction mode instead of failing.

    Visibility matches GET /api/templates/{id} exactly, so a template usable
    here is one the user can already see: their own, a default, or one shared
    inside their own client.
    """
    if not template_id:
        return None
    tpl = db.query(ColumnTemplate).filter(ColumnTemplate.id == template_id).first()
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")
    from app.core.permissions import can
    # super-admin, owner, a default (not offered to a demo), or shared inside
    # the user's own client — permissions.can("template.view")
    if can(current_user, "template.view", tpl):
        return tpl
    raise HTTPException(status_code=403, detail="Not your template")


# ==============================================================================
# UPLOAD ENDPOINT
# ==============================================================================


async def _start_extraction_job(
    sources: list["_IncomingUpload"],
    *,
    requested_client_id: Optional[str],
    template_id: Optional[int],
    options: Optional[str],
    selected_pages: Optional[str],
    db: Session,
    current_user: User,
    storage,
    audit_event: str = demo_audit.UPLOAD,
) -> ExtractUploadResponse:
    """Validate, persist and start one extraction job. The whole upload path.

    It was the body of `POST /api/extract/upload`. It is a function so that the
    demo's "use this sample document" button cannot become a second, thinner
    pipeline that forgets a check - it runs the ordinary one, as the ordinary
    user, with the same limits and the same tenant resolution.
    """
    if len(sources) > settings.MAX_FILES_PER_BATCH:
        raise HTTPException(status_code=400, detail=f"Max {settings.MAX_FILES_PER_BATCH} files.")

    # The demo's own ceiling on how many jobs this account may start, asked
    # before anything is read. A no-op for every non-demo tenant.
    try:
        check_upload_quota(db, current_user)
    except HTTPException as exc:
        if getattr(exc, "demo_reason", None):
            demo_audit.record(db, current_user, demo_audit.UPLOAD_REFUSED,
                              detail=demo_audit.refusal_detail(exc))
        raise

    # ONE FILE'S BYTES AT A TIME. `content` is rebound each iteration and the
    # previous file's bytes become collectable, exactly as before this path was
    # shared, so peak memory is one file and not the batch. Both checks are per
    # file and neither needs to see the others: `validate_upload` is the
    # product's (extension, size) and `check_upload_file` is the demo's (PDF
    # only, DEMO_MAX_MB, and a document that is nothing but a scan refused with
    # an explanation instead of being OCR'd). Both run BEFORE the job row
    # exists, so a refused upload leaves nothing behind and costs no model call.
    sizes: list[tuple[str, int]] = []
    page_counts: list[tuple[str, int]] = []
    used_names: set[str] = set()
    refused_name: Optional[str] = None
    try:
        for src in sources:
            refused_name = src.filename
            content = await src.read()
            error = storage.validate_upload(src.filename, len(content))
            if error:
                raise HTTPException(status_code=400, detail=f"{src.filename}: {error}")
            # YAML used to be a product-supported extension but the demo's
            # PDF-only policy refused it with a demo notice. Preserve that
            # established demo response; arbitrary unsupported content (for
            # example .exe) remains a product refusal and is not demo-audited.
            if (is_demo_user(current_user)
                    and Path(src.filename or "").suffix.lower()
                    in (".yaml", ".yml")):
                check_upload_file(current_user, src.filename, content)
            safe_name, _kind, page_count = _validate_upload_content(
                src.filename, content)
            src.filename = _unique_upload_name(safe_name, used_names)
            check_upload_file(current_user, src.filename, content)
            sizes.append((src.original_filename, len(content)))
            page_counts.append((src.original_filename, page_count))
    except HTTPException as exc:
        # Only a DEMO refusal goes in the trail, and `demo_reason` is what says
        # it is one — the product's own "file type not supported" is not a demo
        # rule and is not this table's business.
        if getattr(exc, "demo_reason", None):
            demo_audit.record(db, current_user, demo_audit.UPLOAD_REFUSED,
                              detail=demo_audit.refusal_detail(exc, refused_name))
        raise

    selected_pages_list = _parse_selected_pages(selected_pages, page_counts)

    # The tenant and the template both come from the token's authority, never
    # from the multipart body.
    client_id = resolve_client_id(current_user, requested_client_id)

    # A configured demo account intentionally uses the bundled demo schema.
    # Every other tenant must have its own schema; borrowing demo_001 here
    # silently extracts real customer documents against another field set.
    schema_client_id = "demo_001" if is_demo_user(current_user) else client_id
    schema_path = storage.get_schema_path(schema_client_id)
    if schema_path is None:
        raise HTTPException(
            status_code=404,
            detail="No extraction schema is configured for this client.")

    # The thread owns the schema copy once it has started; until then a
    # refused or failed request must hand it back itself (an object-store temp
    # copy of the client's schema).
    try:
        tpl = load_template_for_user(db, template_id, current_user)
        template_data = _parse_template(tpl) if tpl else None

        # Parse options
        selected_options: list = []
        if options:
            try:
                selected_options = json.loads(options)
            except Exception:
                selected_options = [o.strip() for o in options.split(",") if o.strip()]

        # Categorisation, charts, summary and anomalies are not part of the demo.
        # Forced off here rather than at the two doors, so the sample-document
        # route cannot be the one that forgets. A no-op for everyone else.
        selected_options = filter_options(current_user, selected_options)

        job = ExtractionJob(
            user_id=current_user.id,
            client_id=client_id,
            status="pending",
            total_docs=len(sources),
            input_source="upload",
            started_at=datetime.utcnow(),
            schema_id=str(template_id) if template_id else None,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        job_id = job.id

        # The worker is handed KEYS, not paths. A local absolute path is
        # meaningless to a separate worker process or an object store, and passing
        # one is what tied extraction to this container's own disk.
        saved_keys = []
        for src in sources:
            content = await src.read()
            key, _ = storage.save_upload(content, src.filename, job_id,
                                         client_id=client_id)
            saved_keys.append(key)

        thread = threading.Thread(
            target=_run_extraction_sync,
            args=(job_id, saved_keys, str(schema_path), settings.DATABASE_URL,
                  template_data, str(_project_dir), str(_backend_dir), str(_engine_dir)),
            kwargs={"options": selected_options,
                    "selected_pages": selected_pages_list,
                    "original_filenames": [src.original_filename for src in sources]},
            daemon=True,
        )
        thread.start()
    except BaseException:
        _release_copy(storage, schema_path)
        raise

    # The trail. Filenames, byte sizes and the template's NAME — never a
    # document's contents. Last, so it cannot affect the job it describes.
    demo_audit.record(
        db, current_user, audit_event, job_id=job_id,
        detail={"files": [{"filename": n, "size_bytes": b} for n, b in sizes],
                "template": getattr(tpl, "name", None),
                "template_id": template_id,
                "options_requested": selected_options or []})

    return ExtractUploadResponse(
        job_id=job_id,
        message=f"Extraction started for {len(sources)} file(s)",
        total_files=len(sources),
        status="processing",
    )


@router.post("/extract/upload", response_model=ExtractUploadResponse, status_code=202)
async def upload_and_extract(
    files: list[UploadFile] = File(...),
    client_id: Optional[str] = Form(None),
    template_id: Optional[int] = Form(None),
    options: Optional[str] = Form(None),  # JSON array: ["categorize","summary","anomaly","graphs"]
    selected_pages: Optional[str] = Form(None),  # JSON array of 1-based page numbers e.g. "[1,2,5]"
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    storage=Depends(get_storage),
):
    # The demo's kill switch, checked HERE and not in `_start_extraction_job`:
    # it closes this door and leaves the sample documents open. A no-op for
    # every non-demo tenant, and for a demo tenant while the switch is true.
    try:
        check_uploads_enabled(current_user)
    except HTTPException as exc:
        demo_audit.record(db, current_user, demo_audit.UPLOAD_REFUSED,
                          detail=demo_audit.refusal_detail(exc))
        raise
    return await _start_extraction_job(
        [_IncomingUpload.from_upload(f) for f in files],
        requested_client_id=client_id,
        template_id=template_id,
        options=options,
        selected_pages=selected_pages,
        db=db,
        current_user=current_user,
        storage=storage,
    )


# ==============================================================================
# TEMPLATE PARSING & REGION ANALYSIS
# ==============================================================================


# ==============================================================================
# REGISTRY LOADER
# ==============================================================================


# ==============================================================================
# FINANCIAL SECTION CONTEXT RISK DETECTION  (Bug 5)
# ==============================================================================


# ==============================================================================
# CELL HELPERS
# ==============================================================================


# ==============================================================================
# VISION-FIRST PROMPT BUILDER
# ==============================================================================


# ==============================================================================
# NEIGHBOR-MATRIX BINDING MAP  (layout-based extraction for unlabeled templates)
# ==============================================================================


# ==============================================================================
# GEMINI-BASED TEMPLATE UNDERSTANDING (computed once at SAVE time)
# ==============================================================================


# ==============================================================================
# PDFPLUMBER VALIDATION LAYER
# ==============================================================================


# ==============================================================================
# PDFPLUMBER DIRECT TABLE EXTRACTION
# ==============================================================================


# ==============================================================================
# VALUE NORMALISATION
# ==============================================================================


# ==============================================================================
# MULTI-DOCUMENT DETECTION
# ==============================================================================


# ==============================================================================
# VALUE NORMALIZATION
# ==============================================================================


# ==============================================================================
# RESULT PROCESSORS
# ==============================================================================


# ==============================================================================
# MAIN EXTRACTION ENGINE - VISION FIRST
# ==============================================================================

def _extract_with_template(orchestrator, file_path: Path, template_data: dict,
                            selected_pages: Optional[list] = None,
                            batch_schemas: Optional[dict] = None):
    """
    Vision-First extraction engine - safety-wrapped version.
    All errors are caught and returned as failed DocumentResult objects
    so the job always completes with meaningful error messages.

    `batch_schemas` is the per-job dict that lets no-template documents of the
    same kind share one inferred schema. See engine/extractor.py.
    """
    try:
        return _extract_with_template_inner(orchestrator, file_path, template_data,
                                            selected_pages=selected_pages,
                                            batch_schemas=batch_schemas)
    except Exception as e:
        print(f"[EXTRACT] FATAL {doc_ref(file_path)}: {exc_brief(e)}", flush=True)
        print_safe_traceback()
        r = _fail(file_path.name, f"Fatal extraction error: {str(e)[:200]}")
        r.processing_time_ms = 0
        return [r]


def _extract_image_with_template(orchestrator, file_path: Path,
                                  template_data: Optional[dict]) -> list:
    """
    Extract from a single image file (JPG/PNG/WEBP/TIFF/BMP).
    Sends the image directly to Gemini Vision — no pdfplumber layer.

    Every value here is UNVERIFIED, and that is the honest word for it: an
    image has no text layer, so no span can be checked against anything and
    no grounding runs at all. These cells were reported as "medium" before
    Phase 8, which implied a measurement had been made and had come out
    middling. Nothing was measured. Always sets needs_review=True.
    """
    import base64 as _b64
    import time as t

    start = t.time()
    doc_type = (template_data or {}).get("doc_type", "other")

    try:
        image_data = _load_image_as_png_bytes(file_path)
        image_b64  = _b64.b64encode(image_data).decode("utf-8")

        if template_data:
            system_instruction, prompt = _build_vision_prompt(template_data, "")
        else:
            system_instruction = _get_unguided_prompt()
            prompt = (
                "Extract every key data field visible in this document image.\n"
                "Return ONLY JSON:\n"
                '{"document_type": "...", "overall_confidence": "unverified", '
                '"extracted_fields": {"field_name": "value"}, "table_rows": []}'
            )

        extraction = orchestrator.llm.extract(
            image_b64=image_b64,
            prompt=prompt,
            system_instruction=system_instruction,
        )
        elapsed = (t.time() - start) * 1000

        if not extraction.success or not extraction.parsed_json:
            r = _fail(file_path.name,
                      f"Image extraction failed: {extraction.error}")
            r.processing_time_ms = elapsed
            return [r]

        raw = extraction.parsed_json

        if template_data:
            result = _process_vision_result(
                raw, template_data, file_path.name, doc_type,
                elapsed, extraction,
                "",          # no doc_text — image has no text layer
                "image upload", 0,
            )
        else:
            from orchestrator import DocumentExtractionResult
            result = DocumentExtractionResult(filename=file_path.name)
            result.document_type = raw.get("document_type", doc_type)
            result.extracted_data = {
                "document_type":    raw.get("document_type", doc_type),
                "overall_confidence": UNVERIFIED,
                "extraction_method": "image_upload",
                "extracted_data": {
                    k: {"value": str(v) if v is not None else "", "confidence": UNVERIFIED}
                    for k, v in raw.get("extracted_fields", {}).items()
                },
                "table_rows": raw.get("table_rows", []),
                "validation": {
                    "flagged_count": 1,
                    "flagged_fields": [],
                    "confidence_map": {},
                    "alignment_misaligned": False,
                    "alignment_warning": "",
                },
            }
            result.extraction_response = extraction
            result.processing_time_ms  = elapsed
            result.success             = True

        # UNVERIFIED + needs_review for ALL image uploads. No text layer exists,
        # so nothing was checked — see the docstring.
        if result.success and result.extracted_data:
            result.extracted_data["overall_confidence"] = UNVERIFIED
            result.extracted_data["image_upload"] = True
            inner = result.extracted_data.get("extracted_data", {})
            for key in inner:
                if isinstance(inner[key], dict):
                    inner[key]["confidence"] = UNVERIFIED
            # Inject a validation flag so _run_extraction_sync sets needs_review=True
            val = result.extracted_data.setdefault("validation", {})
            val["flagged_count"] = max(1, val.get("flagged_count", 0))
            # `reason`, not `issue`: one key name across every producer, which
            # is what the review panel reads. Spelling it `issue` here made
            # this flag render as a blank row.
            val.setdefault("flagged_fields", []).append({
                "ref": "image_upload",
                "value": "",
                "reason": (
                    "Image upload — no text layer, so no value could be "
                    "verified against the document; please check manually"
                ),
            })

        print(
            f"[IMAGE] {doc_ref(file_path)}: extracted "
            f"{len(result.extracted_data.get('extracted_data', {}))} fields",
            flush=True,
        )
        return [result]

    except Exception as e:
        print(f"[IMAGE] Error {doc_ref(file_path)}: {exc_brief(e)}", flush=True)
        print_safe_traceback()
        r = _fail(file_path.name, str(e))
        r.processing_time_ms = (t.time() - start) * 1000
        return [r]


def _extract_with_template_inner(orchestrator, file_path: Path, template_data: dict,
                                  selected_pages: Optional[list] = None,
                                  batch_schemas: Optional[dict] = None):
    """Run the extraction engine. One pipeline, no flag, no fallback.

    Phase 2d: `USE_NEW_EXTRACTOR` and the legacy inline pipeline are gone. The
    flag guarded a bare `except Exception` that caught ANY error from the
    engine — including a bug just introduced — logged one stdout line, and
    silently completed the request on a different engine that produced a
    differently-shaped result and therefore a different spreadsheet. Nothing in
    the database or the API recorded which engine had run. A failure is now a
    failure, and it is visible.
    """
    from extractor import run_extraction
    return run_extraction(orchestrator, file_path, template_data,
                          selected_pages=selected_pages,
                          batch_schemas=batch_schemas)


# ==============================================================================
# SECTIONED MULTI-PASS EXTRACTION (parallel column templates)
# ==============================================================================


# ==============================================================================
# BACKGROUND THREAD
# ==============================================================================

def _post_categorize(extracted: dict, orchestrator, doc_type: str) -> dict:
    """
    Second-pass categorization when the extraction didn't produce Category values.
    Sends only the table rows to Gemini for categorization — minimal tokens.
    """
    try:
        table_rows = extracted.get("table_rows", [])
        if not table_rows:
            return extracted

        rows_text = "\n".join(
            f"Row {i+1}: {json.dumps(row)}"
            for i, row in enumerate(table_rows[:50])  # max 50 rows
        )
        prompt = (
            f"Assign a business category to each row below.\n"
            f"Use these categories: Travel, Meals, Lodging, Office Supplies, "
            f"Software, Marketing, Professional Fees, Utilities, Salary, "
            f"Rent, Insurance, Equipment, Tax, Bank Charges, Other.\n\n"
            f"Return ONLY a JSON object: {{\"categories\": [\"cat1\", \"cat2\", ...]}}\n"
            f"One category per row in the same order.\n\n"
            f"Rows:\n{rows_text}"
        )
        result = orchestrator.llm.extract(text=rows_text, prompt=prompt)
        if result.success and result.parsed_json:
            cats = result.parsed_json.get("categories", [])
            for i, row in enumerate(table_rows):
                if i < len(cats) and not row.get("Category"):
                    row["Category"] = cats[i]
            extracted["table_rows"] = table_rows
            print(f"[OPTIONS] categorized {len(cats)} rows", flush=True)
    except Exception as e:
        print(f"[OPTIONS] categorize failed: {exc_brief(e)}", flush=True)
    return extracted


def _post_summarize(extracted: dict, orchestrator, doc_type: str) -> dict:
    """
    Generate a 2-3 sentence plain English summary of the extracted document.
    Uses Gemini — stored in extracted['summary'].
    """
    try:
        inner = extracted.get("extracted_data", {})
        fields = {k: (v.get("value", "") if isinstance(v, dict) else v)
                  for k, v in inner.items() if not k.startswith("_label_")}
        if not fields:
            return extracted

        field_str = "\n".join(f"{k}: {v}" for k, v in list(fields.items())[:20])
        table_rows = extracted.get("table_rows", [])
        table_str = f"\n{len(table_rows)} line items." if table_rows else ""

        prompt = (
            f"Summarise this {doc_type} document in 2-3 plain English sentences. "
            f"Be specific about key values. No bullet points.\n\n"
            f"Fields:\n{field_str}{table_str}\n\n"
            f"Return ONLY a JSON object: {{\"summary\": \"your summary here\"}}"
        )
        result = orchestrator.llm.extract(text=field_str, prompt=prompt)
        if result.success and result.parsed_json:
            summary = result.parsed_json.get("summary", "")
            if summary:
                extracted["summary"] = summary
                print(f"[OPTIONS] summary generated: {len(summary)} chars", flush=True)
    except Exception as e:
        print(f"[OPTIONS] summary failed: {exc_brief(e)}", flush=True)
    return extracted


def _post_anomaly(extracted: dict, orchestrator, doc_type: str) -> dict:
    """
    Detect anomalies in extracted data — duplicate values, unusual amounts,
    missing required fields, outliers.
    Stored in extracted['anomalies'] as a list of strings.
    """
    try:
        inner = extracted.get("extracted_data", {})
        fields = {k: (v.get("value", "") if isinstance(v, dict) else v)
                  for k, v in inner.items() if not k.startswith("_label_")}
        table_rows = extracted.get("table_rows", [])[:30]

        field_str = "\n".join(f"{k}: {v}" for k, v in list(fields.items())[:15])
        row_str   = "\n".join(f"Row {i+1}: {json.dumps(r)}"
                               for i, r in enumerate(table_rows))

        prompt = (
            f"Analyse this extracted {doc_type} data for anomalies: "
            f"unusual values, duplicates, outliers, or missing required fields.\n"
            f"Return ONLY a JSON object: {{\"anomalies\": [\"issue1\", \"issue2\"]}}\n"
            f"Maximum 5 items. If nothing unusual return {{\"anomalies\": []}}\n\n"
            f"Fields:\n{field_str}\n\nRows:\n{row_str}"
        )
        result = orchestrator.llm.extract(text=field_str, prompt=prompt)
        if result.success and result.parsed_json:
            anomalies = result.parsed_json.get("anomalies", [])
            extracted["anomalies"] = anomalies if isinstance(anomalies, list) else []
            print(f"[OPTIONS] anomalies: {len(extracted['anomalies'])} found", flush=True)
    except Exception as e:
        print(f"[OPTIONS] anomaly failed: {exc_brief(e)}", flush=True)
    return extracted


_FINANCIAL_CRITICAL_TYPES = frozenset({
    "balance_sheet", "income_statement", "payslip", "sales_invoice",
})


def _cross_validate_section_totals(extracted_data: dict, doc_type: str) -> Optional[str]:
    """
    H2: For balance sheets and income statements, cross-check whether the sum of
    line-item amounts roughly matches any declared section total.
    Returns a human-readable warning string if a mismatch > 1% is found, else None.
    """
    if doc_type not in ("balance_sheet", "income_statement"):
        return None

    table_rows = extracted_data.get("table_rows", [])
    if len(table_rows) < 2:
        return None

    inner = extracted_data.get("extracted_data", {})

    # Collect declared totals from extracted_data (form fields)
    declared_totals = {}
    for label, field in inner.items():
        label_lower = label.lower().strip()
        if label_lower.startswith("_label_"):
            continue
        if any(t in label_lower for t in ("total", "grand total", "net total")):
            raw_val = field.get("value", "") if isinstance(field, dict) else str(field)
            try:
                declared_totals[label] = abs(float(
                    re.sub(r'[,$£€₹()\s]', '', str(raw_val)).replace(")", "")
                ))
            except (ValueError, TypeError):
                pass

    if not declared_totals:
        return None

    # Sum numeric columns across table rows
    numeric_cols = set()
    for row in table_rows[:5]:
        for k, v in row.items():
            if k.startswith("_"):
                continue
            try:
                float(re.sub(r'[,$£€₹()\s]', '', str(v)))
                numeric_cols.add(k)
            except (ValueError, TypeError):
                pass

    for col in numeric_cols:
        row_sum = 0.0
        for row in table_rows:
            try:
                row_sum += abs(float(
                    re.sub(r'[,$£€₹()\s]', '', str(row.get(col, "") or ""))
                ))
            except (ValueError, TypeError):
                pass

        for label, declared in declared_totals.items():
            if declared > 0 and abs(row_sum - declared) / declared > 0.01:
                return (
                    f"H2 section-total mismatch: sum of '{col}' column = {row_sum:.2f}, "
                    f"declared '{label}' = {declared:.2f} "
                    f"(diff {abs(row_sum - declared) / declared * 100:.1f}%)"
                )
    return None


def _is_storage_key(value) -> bool:
    """A storage key, as opposed to a filesystem path.

    Jobs recorded before Phase 8 hold absolute paths; jobs after it hold keys.
    Both have to keep working, and the difference is visible: a key is
    relative, uses forward slashes, and has no drive letter.
    """
    v = str(value or "")
    if not v or v.startswith(("/", "\\", "~")) or re.match(r"^[A-Za-z]:", v):
        return False
    return "\\" not in v


def _resolve_source(storage, ref):
    """A readable path for a source document, or None if it is gone.

    Takes either a storage key (Phase 8 onward) or an absolute path (jobs
    submitted before it), so a queue drained across the upgrade still runs.
    """
    if _is_storage_key(ref):
        return storage.get_local_path(ref)
    p = Path(ref)
    return p if p.exists() else None


def _flag_batch_duplicates(session, job_id) -> int:
    """Flag possible duplicates among a job's stored records; returns how many
    records newly need review. Records are compared as stored, so a record
    split from a multi-cheque file is compared like any other."""
    from duplicates import flag_possible_duplicates
    docs = (session.query(DocumentResult)
            .filter(DocumentResult.job_id == job_id)
            .order_by(DocumentResult.id).all())
    eds = [d.get_extracted_data() for d in docs]
    usable = [(d, ed) for d, ed in zip(docs, eds) if isinstance(ed, dict) and ed]
    hit = flag_possible_duplicates([ed for _d, ed in usable],
                                   names=[d.filename for d, _ed in usable])
    newly = 0
    for k in hit:
        d, ed = usable[k]
        d.set_extracted_data(ed)
        if not d.needs_review:
            newly += 1
        d.needs_review = True
        d.validation_warnings = _flag_summary(
            (ed.get("validation") or {}).get("flagged_fields") or [])
    if hit:
        print(f"[DUPLICATES] job {job_id}: {len(hit)} record(s) flagged as "
              f"possible duplicates", flush=True)
        session.commit()
    return newly


def _flag_summary(flagged) -> str:
    """`validation.flagged_fields` rendered as one line for the results row.

    Tolerant of a bare string on purpose. The engine now emits one shape
    (`{ref, value, reason}`, built by `slot_extractor._flag`), but this
    function is on the SAVE path: the previous version indexed `f['ref']`
    unconditionally, a string entry raised TypeError, and the per-document
    handler recorded the whole document as failed. A summary line is not worth
    losing a document over, so an unexpected entry is stringified rather than
    fatal.
    """
    out = []
    for f in flagged or []:
        if isinstance(f, dict):
            ref = f.get("ref") or f.get("label") or ""
            value = f.get("value", "")
            reason = f.get("reason") or f.get("issue") or ""
            out.append(f"{ref}: {value}" + (f" ({reason})" if reason else ""))
        else:
            out.append(str(f))
    return "; ".join(out)


_MULTI_RECORD_SUFFIX_RE = re.compile(r"\s+\[\d+\s+of\s+\d+\]$")


def _result_display_name(engine_name: str, original_name: str) -> str:
    """Put an engine record suffix onto the safe, user-facing upload name."""
    match = _MULTI_RECORD_SUFFIX_RE.search(str(engine_name or ""))
    return original_name + (match.group(0) if match else "")


def _document_index(document: DocumentResult) -> int:
    """Stable sort key for one-file/many-record route responses."""
    try:
        return int(document.get_extracted_data().get("document_index", 1))
    except (AttributeError, TypeError, ValueError):
        return 1


def _value_requires_review(value) -> bool:
    """Whether any extracted field or row carries the engine review gate.

    Field metadata uses ``review_required``; table-row metadata historically
    used ``_review_required``. Walk the saved payload so either representation
    enforces the same document-level invariant without projecting away any of
    the engine's metadata.
    """
    if isinstance(value, dict):
        if (value.get("review_required") is True
                or value.get("_review_required") is True):
            return True
        return any(_value_requires_review(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_value_requires_review(item) for item in value)
    return False


def _persist_failure(session_factory, job_id, ref, error) -> None:
    """Record a document that failed BEFORE it could produce a result.

    A failed document must leave a row. Counting the failure and moving on is
    exactly what hid the Phase 8 `storage` NameError: five documents failed,
    the job reported `completed`, `GET /results` returned `[]`, the export
    answered 404, and the only trace of the cause was one line on the
    container's stdout. Nobody reads a container's stdout for a job that says
    it worked.

    A row costs nothing and turns a silent total failure into a diagnosable
    one — the filename and the exception are where the user is already
    looking. `extraction_json` stays NULL, which is what every reader already
    treats as "no values", and the writers skip it rather than emitting an
    empty block.

    Written on its OWN session. The caller's session is a unit of work holding
    flushed-but-uncommitted results from earlier documents in the same batch;
    rolling it back or committing it here to record one failure would take
    those with it.
    """
    from app.models.models import DocumentResult

    s = session_factory()
    try:
        s.add(DocumentResult(
            job_id=job_id,
            filename=Path(str(ref)).name or str(ref),
            document_type="unknown",
            overall_confidence="low",
            extraction_json=None,
            validation_errors=f"{type(error).__name__}: {error}"[:2000],
            needs_review=True,
            latency_ms=0,
            tokens_used=0,
        ))
        s.commit()
    except Exception as e:
        s.rollback()
        print(f"[THREAD] could not record the failure of {doc_ref(ref)}: {exc_brief(e)}", flush=True)
    finally:
        s.close()


#: How often, at most, the job thread asks the database whether its job was
#: cancelled while a document is being read (between pages).
CANCEL_POLL_SEC = 1.0

#: The text a cancelled file's row carries, and the job's reason prefix.
CANCELLED_FILE_MSG = ("Cancelled: this document was not processed (the job was "
                      "cancelled before it finished). Upload it again to extract it.")


def _cancel_probe(session_factory, job_id):
    """A callable answering "was this job cancelled?", read on its OWN short
    session (the job thread's session holds uncommitted results). Between
    pages it asks at most every CANCEL_POLL_SEC; `force=True` always asks."""
    import time as _t
    from app.models.models import ExtractionJob
    state = {"at": 0.0, "answer": False}

    def probe(force=False):
        if state["answer"]:
            return True
        now = _t.monotonic()
        if not force and now - state["at"] < CANCEL_POLL_SEC:
            return False
        state["at"] = now
        s = session_factory()
        try:
            row = s.query(ExtractionJob.status).filter(ExtractionJob.id == job_id).first()
            state["answer"] = bool(row) and row[0] == "cancelled"
        except Exception as e:
            print(f"[THREAD] cancel check failed: {exc_brief(e)}", flush=True)
        finally:
            s.close()
        return state["answer"]
    return probe


def _persist_cancelled(session_factory, job_id, names) -> None:
    """One row per file that did not finish, saying it was cancelled — never a
    row that looks like a result (no extraction_json, needs_review)."""
    from app.models.models import DocumentResult
    if not names:
        return
    s = session_factory()
    try:
        for name in names:
            s.add(DocumentResult(
                job_id=job_id, filename=Path(str(name)).name or str(name),
                original_filename=Path(str(name)).name or str(name),
                document_type="cancelled", overall_confidence="low",
                extraction_json=None, validation_errors=CANCELLED_FILE_MSG,
                needs_review=True, latency_ms=0, tokens_used=0))
        s.commit()
    except Exception as e:
        s.rollback()
        print(f"[THREAD] could not record {len(names)} cancelled file(s): {exc_brief(e)}",
              flush=True)
    finally:
        s.close()


def _finish_cancelled(session, job, done, total, successful, failed,
                      needs_review, elapsed=0.0) -> None:
    """Close a cancelled job: status stays `cancelled`, counts are what
    finished, and the message says how far it got."""
    session.refresh(job)
    job.status = "cancelled"
    job.successful = successful
    job.failed = failed
    job.needs_review = needs_review
    job.total_time_sec = elapsed
    job.completed_at = job.completed_at or datetime.utcnow()
    left = total - done
    job.progress_message = (
        f"Cancelled after {done} of {total} file(s); "
        + (f"{left} not processed (listed as cancelled)." if left
           else "every file had already finished, and its results are kept."))
    if not job.status_reason:
        job.set_mark("status_reason", "Cancelled")
    session.commit()
    print(f"[THREAD] CANCELLED job {job.id}: {done}/{total} files finished", flush=True)


def _release_copy(storage, path):
    """Hand a temp copy back to storage (`StorageService.release`). A no-op for
    the local store's own files and for a storage without temp copies; never
    raises, because cleanup must not be the reason a job is lost."""
    release = getattr(storage, "release", None)
    if release is None or not path:
        return
    try:
        release(path)
    except Exception as e:
        print(f"[THREAD] temp copy release failed: {type(e).__name__}", flush=True)


def _run_extraction_sync(job_id, file_keys, schema_path, db_url, template_data,
                          project_dir, backend_dir, engine_dir, options=None,
                          selected_pages=None, original_filenames=None):
    """The job thread. The schema copy the route fetched is released here,
    whatever happens inside — success, a failed document, a cancelled job, or
    a failure before the first document."""
    try:
        _run_extraction_job(job_id, file_keys, schema_path, db_url, template_data,
                            project_dir, backend_dir, engine_dir, options=options,
                            selected_pages=selected_pages,
                            original_filenames=original_filenames)
    finally:
        _release_copy(get_storage(), schema_path)


def _run_extraction_job(job_id, file_keys, schema_path, db_url, template_data,
                        project_dir, backend_dir, engine_dir, options=None,
                        selected_pages=None, original_filenames=None):
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
        print(f"[THREAD] DB import failed: {exc_brief(e)}", flush=True); return

    try:
        connect_args = {"check_same_thread": False} if "sqlite" in db_url else {}
        _eng = sa_engine(db_url, connect_args=connect_args)
        Session = sessionmaker(bind=_eng)
        session = Session()
    except Exception as e:
        print(f"[THREAD] DB session failed: {exc_brief(e)}", flush=True); return

    try:
        job = session.query(ExtractionJob).filter_by(id=job_id).first()
        if not job: return
        names = [(original_filenames[i] if original_filenames and i < len(original_filenames)
                  else Path(str(fp)).name or str(fp)) for i, fp in enumerate(file_keys)]
        if job.status == "cancelled":
            # Cancelled while it was still pending: nothing ran, say so per file.
            _persist_cancelled(Session, job_id, names)
            _finish_cancelled(session, job, 0, len(names), 0, 0, 0)
            return
        job.status = "processing"
        session.commit()
        is_cancelled = _cancel_probe(Session, job_id)
        cancelled_at = None

        from orchestrator import Orchestrator
        orchestrator = Orchestrator(client_schema_path=schema_path)

        # The worker builds its OWN storage handle. `storage` in the upload
        # route is a request dependency (`Depends(get_storage)`) and does not
        # exist in this thread: referencing it here raised NameError on the
        # FIRST line of every document's try block, and the per-document
        # `except` turned that into "this document failed" — for every
        # document, of every upload, while the job still reported `completed`.
        # Pinned by tests/http/test_batch_end_to_end.py and by the pyflakes
        # gate in tests/test_no_undefined_names.py.
        storage = get_storage()

        successful = failed = needs_review = 0
        total_tokens_used = 0
        total_cost_usd = 0.0
        start_time = time.time()

        # One schema cache per JOB, for documents extracted without a template.
        # Inference names the columns and does not name them the same way twice,
        # and the exporter groups sheets by a signature over those names — so
        # fifty invoices of one design used to produce up to fifty sheets with
        # slightly different headings instead of one sheet with fifty rows.
        # Inferring once per document KIND and reusing the answer makes
        # within-batch variance exactly zero: the schema is not re-derived, so
        # it cannot differ. Scoped to this job and discarded with it — nothing
        # is persisted, and nothing leaks between clients or jobs.
        batch_schemas: dict = {}

        for i, fp in enumerate(file_keys):
            if is_cancelled(force=True):
                cancelled_at = i
                break
            display_filename = (
                original_filenames[i]
                if original_filenames and i < len(original_filenames)
                else Path(str(fp)).name or str(fp)
            )
            print(f"[THREAD] processing file {i+1}/{len(file_keys)}: {doc_ref(fp)}", flush=True)

            # Issue 2: update job progress so the UI can poll live status
            try:
                job.progress_message = (
                    f"Processing document {i+1} of {len(file_keys)}..."
                )
                session.commit()
            except Exception:
                pass

            file_path = None
            try:
                # `fp` is a storage KEY. Resolving it is what makes the worker
                # independent of which machine received the upload: local
                # returns the path under the storage root, the object store
                # fetches to a temp file.
                with watching(is_cancelled):
                    file_path = _resolve_source(storage, fp)
                    if file_path is None:
                        # The source document is gone — an ephemeral disk lost it
                        # between upload and processing, or retention deleted it.
                        # That is an ordinary state, not a crash: it fails THIS
                        # document with a message saying what happened, and the
                        # result travels the same persistence path as any other, so
                        # the job still completes and still reports.
                        print(f"[THREAD] source missing: {doc_ref(fp)}", flush=True)
                        results = [_fail(display_filename,
                                         "Source document is no longer in storage "
                                         "— upload it again to re-run this job.")]
                    elif _is_image_file(file_path):
                        # Images now enter the same engine seam as PDFs. That path
                        # preprocesses them with OCR, retains geometry/origin, and
                        # applies the same grounding and review rules. The direct
                        # vision path remains only as a compatibility fallback for
                        # an engine failure.
                        if template_data:
                            results = _extract_with_template(
                                orchestrator, file_path, template_data,
                                selected_pages=selected_pages,
                            )
                        else:
                            results = _extract_with_template(
                                orchestrator, file_path, None,
                                selected_pages=selected_pages,
                                batch_schemas=batch_schemas,
                            )
                        if not results or not any(
                                getattr(r, "success", False) for r in results):
                            results = _extract_image_with_template(
                                orchestrator, file_path, template_data)
                    elif template_data:
                        results = _extract_with_template(
                            orchestrator, file_path, template_data,
                            selected_pages=selected_pages,
                        )
                    else:
                        # Phase 3 — no template: the engine infers one and runs the
                        # same slot pipeline. Previously this went to the
                        # orchestrator's schema path, which was bounded to the 6
                        # document types in demo_accounting.yaml and dropped line
                        # items entirely.
                        results = _extract_with_template(
                            orchestrator, file_path, None,
                            selected_pages=selected_pages,
                            batch_schemas=batch_schemas,
                        )
                # A cancel that landed while this document was being read:
                # its results are discarded, never stored as if final.
                if is_cancelled(force=True):
                    raise Cancelled()

                for result in results:
                    result.filename = _result_display_name(
                        getattr(result, "filename", ""), display_filename)
                    try:
                        validation_data = (result.extracted_data or {}).get("validation", {})
                        flagged_fields = validation_data.get("flagged_fields", []) or []
                        # The list is the evidence. Keep the count as a
                        # backwards-compatible escalation signal, but never
                        # let a stale zero suppress real flagged fields.
                        has_flags = bool(flagged_fields) or (
                            validation_data.get("flagged_count", 0) > 0)
                        error_msg      = result.error if hasattr(result, 'error') and result.error else ""

                        # H1: for financial doc types, any low-confidence numeric field
                        #     escalates the entire document to needs_review=True
                        doc_type_str = (result.document_type or "").lower()
                        if not has_flags and doc_type_str in _FINANCIAL_CRITICAL_TYPES:
                            conf_map = validation_data.get("confidence_map", {})
                            if "low" in conf_map.values():
                                has_flags = True
                                print(
                                    f"[H1] {doc_ref(result.filename)}: financial doc "
                                    f"({doc_type_str}) has low-confidence field "
                                    f"— needs_review escalated",
                                    flush=True,
                                )

                        # Bug 6: misaligned rows also escalate to needs_review
                        if not has_flags and validation_data.get("alignment_misaligned"):
                            has_flags = True

                        # H2: section-total cross-validation for balance sheets / income statements
                        if result.success and doc_type_str in ("balance_sheet", "income_statement"):
                            section_warn = _cross_validate_section_totals(
                                result.extracted_data or {}, doc_type_str
                            )
                            if section_warn:
                                print(f"[H2] {doc_ref(result.filename)}: section warning recorded as a flag", flush=True)
                                has_flags = True
                                error_msg = (error_msg + "; " if error_msg else "") + section_warn

                        # ── Post-extraction processing based on selected options ──
                        extracted = result.extracted_data or {}

                        if result.success and options:
                            # --- CATEGORIZATION ---
                            # Category is already embedded by the AI in table_rows
                            # via the extraction prompt (bank_statement taxonomy,
                            # expense_report Category column etc.)
                            # If categorize option is on and Category is missing from
                            # table rows, inject it via a second Gemini call
                            if "categorize" in options:
                                table_rows = extracted.get("table_rows", [])
                                missing_cat = table_rows and not table_rows[0].get("Category")
                                if missing_cat:
                                    extracted = _post_categorize(
                                        extracted, orchestrator, result.document_type or ""
                                    )

                            # --- AI SUMMARY ---
                            # Gemini generates a 2-3 sentence plain English summary
                            # stored in extraction_json.summary
                            if "summary" in options and not extracted.get("summary"):
                                extracted = _post_summarize(
                                    extracted, orchestrator, result.document_type or ""
                                )

                            # --- ANOMALY DETECTION ---
                            # Gemini flags unusual values, stored in extraction_json.anomalies
                            if "anomaly" in options and not extracted.get("anomalies"):
                                extracted = _post_anomaly(
                                    extracted, orchestrator, result.document_type or ""
                                )

                            result.extracted_data = extracted

                        # FIX 5: capture the raw LLM response (empty for pdfplumber-only docs)
                        _raw_llm = ""
                        if result.extraction_response is not None:
                            _raw_llm = getattr(result.extraction_response, "raw_text", "") or ""

                        doc = DocumentResult(
                            job_id=job_id,
                            filename=result.filename,
                            original_filename=display_filename,
                            # the source this record was read from — what
                            # the review screen shows its pages from
                            s3_key=str(fp) if _is_storage_key(fp) else None,
                            document_type=result.document_type if result.success else "unknown",
                            overall_confidence=extracted.get("overall_confidence"),
                            extraction_json=json.dumps(extracted, default=str) if extracted else None,
                            raw_llm_response=_raw_llm or None,
                            validation_errors=error_msg or ("; ".join(result.validation.errors) if result.validation else ""),
                            validation_warnings=(
                                _flag_summary(flagged_fields)
                                if has_flags else ""
                            ),
                            needs_review=(
                                has_flags
                                or bool(extracted.get("needs_review"))
                                or _value_requires_review(extracted)
                                or (result.validation.needs_review
                                    if result.validation else False)
                            ),
                            model_used=(result.extraction_response.model_used
                                        if result.extraction_response else "vision_direct"),
                            tokens_used=(result.extraction_response.tokens_used
                                         if result.extraction_response else 0),
                            latency_ms=result.processing_time_ms,
                        )
                        session.add(doc)
                        session.flush()

                        doc_tokens = (result.extraction_response.tokens_used
                                      if result.extraction_response else 0) or 0
                        total_tokens_used += doc_tokens
                        doc_cost = (doc_tokens / 1_000_000) * 0.15
                        total_cost_usd += doc_cost

                        print(f"[THREAD] saved: {doc_ref(result.filename)} "
                              f"tokens={doc_tokens} cost=${doc_cost:.5f} "
                              f"| job_total={total_tokens_used} tokens "
                              f"${total_cost_usd:.4f}", flush=True)

                        if result.success:
                            successful += 1
                            if doc.needs_review:
                                needs_review += 1
                        else:
                            failed += 1

                    except Exception as save_err:
                        print(f"[THREAD] SAVE ERROR for {doc_ref(result.filename)}: {exc_brief(save_err)}", flush=True)
                        print_safe_traceback()
                        failed += 1
                        _persist_failure(Session, job_id,
                                         getattr(result, "filename", fp), save_err)

            except Cancelled:
                cancelled_at = i
                break
            except Exception as doc_err:
                print(f"[THREAD] doc error: {exc_brief(doc_err)}", flush=True)
                print_safe_traceback()
                failed += 1
                _persist_failure(Session, job_id, display_filename, doc_err)
            finally:
                # An object-store temp copy of this client's document.
                _release_copy(storage, file_path)

            # Rate limit protection: delay between documents
            # Prevents provider 429 errors on batch uploads
            # (RATE_LIMIT_DELAY; 3s when unset)
            if i < len(file_keys) - 1 and not is_cancelled(force=True):
                delay = float(getattr(settings, 'RATE_LIMIT_DELAY', 3.0))
                print(f"[THREAD] rate limit delay {delay}s before next doc", flush=True)
                time.sleep(delay)

        if cancelled_at is None and is_cancelled(force=True):
            cancelled_at = len(file_keys)        # cancelled after the last file
        if cancelled_at is not None:
            session.commit()                     # the files that finished
            _persist_cancelled(Session, job_id, names[cancelled_at:])
            _finish_cancelled(session, job, cancelled_at, len(names), successful,
                              failed, needs_review, time.time() - start_time)
            return

        session.commit()

        # The same cheque scanned twice is FLAGGED on both records, never
        # merged or dropped (engine/duplicates.py). A check that cannot run
        # says so on the job rather than passing for a clean batch.
        try:
            needs_review += _flag_batch_duplicates(session, job_id)
        except Exception as dup_err:
            print(f"[THREAD] duplicate check could not run: {exc_brief(dup_err)}", flush=True)
            job.progress_message = ("The duplicate-cheque check could not run "
                                    "for this batch.")
            session.commit()

        # A job that produced nothing is not "completed". Saying it was is how
        # a total failure came to look like an empty result set: a green tick,
        # an empty grid, a download that 404s, and no statement anywhere that
        # something went wrong. The status now names what happened.
        #
        #   completed — every document produced a result
        #   partial   — some produced results, some failed
        #   failed    — none did
        #
        # `successful + failed` counts RESULTS, not files: one PDF holding
        # several documents yields several. The denominator in the message is
        # therefore the result count, so it always agrees with the two numbers
        # beside it.
        produced = successful + failed
        if produced and failed == 0:
            job.status = "completed"
        elif successful:
            job.status = "partial"
        else:
            job.status = "failed"
        if job.status != "completed":
            job.error_message = _job_error_message(session, job_id,
                                                   failed, produced)
        job.successful = successful
        job.failed = failed
        job.needs_review = needs_review
        job.total_time_sec = time.time() - start_time
        job.completed_at = datetime.utcnow()
        session.commit()
        print(f"[THREAD] {job.status.upper()}: {successful} ok, {failed} failed, "
              f"{needs_review} review | "
              f"TOKENS: {total_tokens_used:,} total | "
              f"COST: ${total_cost_usd:.4f} | "
              f"TIME: {job.total_time_sec:.1f}s", flush=True)

    except Exception as e:
        print(f"[THREAD] FAILED: {exc_brief(e)}", flush=True)
        print_safe_traceback()
        try:
            job = session.query(ExtractionJob).filter_by(id=job_id).first()
            if job and job.status != "cancelled":
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
    provenance: bool = True,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        import openpyxl
    except ImportError:
        raise HTTPException(status_code=500, detail="openpyxl not installed.")

    job = _get_job_or_404(job_id, current_user, db, "job.export")
    demo_audit.record(db, current_user, demo_audit.EXPORT, job_id=job_id,
                      detail={"kind": "template"})

    # A DEMO EXPORT CARRIES NO PROVENANCE. The Source column and the cell
    # comments both name the stored file, which on the object store is a temp
    # name (task: `storage.get_local_path`), so for a demo tenant this is
    # forced off whatever the query says. Non-demo callers keep the default and
    # the `provenance=false` switch exactly as before.
    if is_demo_user(current_user):
        provenance = False

    doc_results = (
        db.query(DocumentResult)
        .filter(DocumentResult.job_id == job_id)
        .order_by(DocumentResult.id)
        .all()
    )
    if not doc_results:
        raise HTTPException(status_code=404, detail="No results found.")

    # FIX 4: single source of truth — prefer the region analysis saved at
    # extraction time so export cannot diverge from extraction.
    saved_regions = None
    for _d in doc_results:
        _ed = _d.get_extracted_data()
        if isinstance(_ed, dict) and _ed.get("template_regions"):
            saved_regions = _ed["template_regions"]
            break

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
                    template_regions = saved_regions or _analyse_template_regions(raw)
        except Exception as e:
            print(f"[EXPORT] Template load error: {exc_brief(e)}", flush=True)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Results"

    if sheet_data:
        _write_excel(ws, doc_results, sheet_data, template_regions, openpyxl,
                     provenance=provenance)
    elif _write_inferred_sheets(wb, ws, doc_results, openpyxl,
                                provenance=provenance):
        pass          # Phase 3 — written from the template the engine inferred
    else:
        # Nothing to build a sheet from (e.g. an image with no text layer).
        _write_flat_table(ws, doc_results, openpyxl,
                          show_filename=not is_demo_user(current_user))
    _add_review_legend(wb, doc_results, demo=is_demo_user(current_user))

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    return StreamingResponse(buf, headers={
        "Content-Disposition": f'attachment; filename="job_{job_id}_results.xlsx"',
        "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    })


@router.get("/jobs/{job_id}/export/zip")
def export_job_zip(
    job_id: int,
    provenance: bool = True,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Export each document as a separate Excel file, bundled into a ZIP."""
    try:
        import openpyxl
    except ImportError:
        raise HTTPException(status_code=500, detail="openpyxl not installed.")

    import zipfile

    job = _get_job_or_404(job_id, current_user, db, "job.export")
    demo_audit.record(db, current_user, demo_audit.EXPORT, job_id=job_id,
                      detail={"kind": "zip"})

    # As above: no provenance, and no temp name on the files inside the ZIP.
    demo = is_demo_user(current_user)
    if demo:
        provenance = False
    doc_results = (
        db.query(DocumentResult)
        .filter(DocumentResult.job_id == job_id)
        .order_by(DocumentResult.id)
        .all()
    )
    if not doc_results:
        raise HTTPException(status_code=404, detail="No results found.")

    # FIX 4: single source of truth — prefer the region analysis saved at
    # extraction time so export cannot diverge from extraction.
    saved_regions = None
    for _d in doc_results:
        _ed = _d.get_extracted_data()
        if isinstance(_ed, dict) and _ed.get("template_regions"):
            saved_regions = _ed["template_regions"]
            break

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
                    template_regions = saved_regions or _analyse_template_regions(raw)
        except Exception as e:
            print(f"[EXPORT] Template load error: {exc_brief(e)}", flush=True)

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for doc in doc_results:
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Results"

            if sheet_data:
                _write_excel(ws, [doc], sheet_data, template_regions, openpyxl,
                             provenance=provenance)
            else:
                _write_flat_table(ws, [doc], openpyxl,
                                  show_filename=not demo)
            _add_review_legend(wb, [doc], demo=demo)

            # Use the original filename without extension as the Excel filename
            # — except for a demo, where the stored name is a temp name and
            # would become the name of the file the investor downloads.
            if demo:
                excel_name = f"document_{len(zf.namelist()) + 1}_extracted.xlsx"
            else:
                base = doc.filename.rsplit(".", 1)[0] if "." in doc.filename else doc.filename
                excel_name = f"{base}_extracted.xlsx"

            excel_buf = io.BytesIO()
            wb.save(excel_buf)
            zf.writestr(excel_name, excel_buf.getvalue())

    zip_buf.seek(0)
    safe_name = f"job_{job_id}_documents.zip"
    return StreamingResponse(zip_buf, headers={
        "Content-Disposition": f'attachment; filename="{safe_name}"',
        "Content-Type": "application/zip",
    })


# ==============================================================================
# STYLE HELPERS
# ==============================================================================


# ==============================================================================
# JOB ROUTES
# ==============================================================================

@router.get("/jobs", response_model=list[JobListItem])
def list_jobs(limit: int=50, offset: int=0, status_filter: Optional[str]=None,
              db: Session=Depends(get_db), current_user: User=Depends(get_current_user)):
    from app.core.permissions import job_scope
    q = db.query(ExtractionJob).order_by(ExtractionJob.created_at.desc())
    scope = job_scope(current_user)          # all | tenant | own
    if scope == "tenant":
        q = q.filter(ExtractionJob.client_id == current_user.client_id)
    elif scope == "own":
        q = q.filter(ExtractionJob.user_id == current_user.id)
    # ...and a demo user sees only what happened after the history cutoff. This
    # is the History page's list and the only list of jobs the app has.
    q = filter_demo_history(current_user, q)
    if status_filter:
        q = q.filter(ExtractionJob.status == status_filter)
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
    docs = q.all()
    docs.sort(key=lambda d: (
        (d.original_filename or d.filename or "").casefold(),
        _document_index(d),
        d.id,
    ))
    return [DocumentResultResponse(
        id=d.id, job_id=d.job_id, filename=d.filename,
        original_filename=d.original_filename or d.filename,
        document_type=d.document_type, overall_confidence=d.overall_confidence,
        extracted_data=d.get_extracted_data(),
        validation_errors=d.validation_errors, validation_warnings=d.validation_warnings,
        needs_review=d.needs_review, reviewed=d.reviewed, reviewed_by=d.reviewed_by,
        model_used=d.model_used, tokens_used=d.tokens_used or 0,
        latency_ms=d.latency_ms or 0, created_at=d.created_at,
    ) for d in docs]

@router.get("/jobs/{job_id}/inferred-templates")
def get_inferred_templates(job_id: int, db: Session = Depends(get_db),
                           current_user: User = Depends(get_current_user)):
    """Phase 3 — the templates the engine designed for a job that ran without
    one, as payloads POST /api/templates accepts directly ("save this as a
    template").

    One entry per distinct shape, not per document: documents that inferred the
    same shape share a template, and the entry says how many used it.
    """
    _get_job_or_404(job_id, current_user, db)
    docs = db.query(DocumentResult).filter(
        DocumentResult.job_id == job_id).order_by(DocumentResult.id).all()

    out = {}
    for d in docs:
        ed = d.get_extracted_data()
        if not isinstance(ed, dict):
            continue
        inferred, grid = ed.get("inferred_template"), ed.get("inferred_grid")
        if not (isinstance(inferred, dict) and isinstance(grid, dict)):
            continue
        sig = ed.get("shape_signature") or "shape"
        if sig in out:
            out[sig]["document_count"] += 1
            out[sig]["documents"].append(d.filename)
            continue
        try:
            for p in [str(_engine_dir), str(_backend_dir), str(_project_dir)]:
                if p not in sys.path:
                    sys.path.insert(0, p)
            from shape_inference import saveable_template
            payload = saveable_template(inferred, grid)
        except Exception as e:
            print(f"[TEMPLATE] could not build saveable template: {exc_brief(e)}", flush=True)
            continue
        out[sig] = {"shape_signature": sig, "document_count": 1,
                    "documents": [d.filename], "template": payload,
                    "fields": inferred.get("fields", []),
                    "tables": inferred.get("tables", []),
                    "totals": inferred.get("totals", [])}
    return list(out.values())


# ══════════════════════════════════════════════════════════════════════════════
# EDITS — addressed by SLOT, never by label
# ══════════════════════════════════════════════════════════════════════════════
#
# A value lives at a slot (`extracted_fields[ref]`, or a cell of a `*_rows`
# row). `extracted_data` is a label-keyed PROJECTION of the field slots for
# display. The grid used to edit the projection, by label, and replace the
# whole document; the template writer reads the slots, so every edit was
# silently absent from the download (since 1076e05). Two slots can share a
# label (a matrix template: `Principal` under 2023 and under 2024), and a label
# cannot say which one was meant.
#
# So an edit names a slot. Every copy of the value moves together — the slot,
# the projection, the confidence map — and the edit is MARKED, so the writer
# never presents a typed value under the quote of the words it replaced.

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


@router.put("/jobs/{job_id}/docs/{doc_id}")
def update_document(job_id: int, doc_id: int, payload: DocumentUpdateRequest,
                    db: Session=Depends(get_db), current_user: User=Depends(get_current_user)):
    _get_job_or_404(job_id, current_user, db, "job.review")
    doc = db.query(DocumentResult).filter(DocumentResult.id==doc_id, DocumentResult.job_id==job_id).first()
    if not doc: raise HTTPException(status_code=404, detail="Document not found")
    stored = doc.get_extracted_data() or {}
    ed = _reconcile_edits(stored if isinstance(stored, dict) else {},
                          payload.extracted_data)
    _save_edit(doc, ed, current_user, db)
    return {"message": "Updated", "doc_id": doc_id, "extracted_data": ed}


@router.patch("/jobs/{job_id}/docs/{doc_id}/fields/{ref}")
def edit_field(job_id: int, doc_id: int, ref: str, payload: FieldEditRequest,
               db: Session=Depends(get_db), current_user: User=Depends(get_current_user)):
    """Edit ONE field slot, addressed by its cell reference."""
    import copy
    _get_job_or_404(job_id, current_user, db, "job.review")
    doc = db.query(DocumentResult).filter(DocumentResult.id==doc_id, DocumentResult.job_id==job_id).first()
    if not doc: raise HTTPException(status_code=404, detail="Document not found")
    stored = doc.get_extracted_data() or {}
    if not isinstance(stored, dict) or ref not in _field_refs(stored):
        raise HTTPException(status_code=404,
                            detail=f"This document has no field at {ref!r}")
    ed = copy.deepcopy(stored)
    _edit_field(ed, stored, ref, payload.value)
    _save_edit(doc, ed, current_user, db)
    return {"message": "Updated", "doc_id": doc_id, "ref": ref, "extracted_data": ed}

@router.post("/jobs/{job_id}/docs/{doc_id}/approve")
def approve_document(job_id: int, doc_id: int,
                     db: Session=Depends(get_db), current_user: User=Depends(get_current_user)):
    _get_job_or_404(job_id, current_user, db, "job.review")
    doc = db.query(DocumentResult).filter(DocumentResult.id==doc_id, DocumentResult.job_id==job_id).first()
    if not doc: raise HTTPException(status_code=404, detail="Document not found")
    doc.reviewed=True; doc.reviewed_by=current_user.username; doc.needs_review=False
    db.commit()
    return {"message": "Approved", "doc_id": doc_id}

@router.delete("/jobs/{job_id}")
def cancel_job(job_id: int, db: Session=Depends(get_db), current_user: User=Depends(get_current_user)):
    """Cancel a pending or running job (owner, or an admin in scope). The job
    thread stops at its next checkpoint — before the next file, between pages
    of the file it is reading, before the next model call — discards the file
    it was in the middle of, keeps the files that finished, and lists every
    unfinished file as cancelled. A second cancel is a no-op that says so."""
    job = _get_job_or_404(job_id, current_user, db, "job.cancel")
    if job.status == "cancelled":
        return {"message": "Already cancelled", "job_id": job_id,
                "already_cancelled": True, "status_reason": job.status_reason}
    if job.status not in ("pending","processing"):
        raise HTTPException(status_code=400, detail=f"Cannot cancel job with status '{job.status}'")
    who = "its owner" if job.user_id == current_user.id else "an administrator"
    job.status = "cancelled"
    job.completed_at = datetime.utcnow()
    job.set_mark("status_reason", f"Cancelled by {who} (user {current_user.id})")
    job.progress_message = "Cancelling: stopping before the next page or file."
    db.commit()
    print(f"[JOB] cancel requested for job {job_id} by user {current_user.id}", flush=True)
    return {"message": "Cancelled", "job_id": job_id, "already_cancelled": False,
            "status_reason": job.status_reason}

@router.delete("/jobs/{job_id}/data")
def delete_job_data(job_id: int, db: Session=Depends(get_db),
                    current_user: User=Depends(get_current_user)):
    """Hard delete: the job's files, page readings and results go; the job
    record stays, marked deleted (`core/job_lifecycle.purge_job`). A tenant
    admin of the job's firm or a platform admin; another firm's job is 404."""
    from app.core.job_lifecycle import RUNNING, PurgeIncomplete, purge_job
    job = _get_job_or_404(job_id, current_user, db, "job.delete")
    if job.status in RUNNING:
        raise HTTPException(status_code=409,
                            detail="The job is still running: cancel it first, then delete.")
    try:
        return purge_job(db, job, current_user)
    except PurgeIncomplete as e:
        raise HTTPException(status_code=500,
                            detail=f"{e.args[0]} stored files could not be deleted; "
                                   "nothing was marked deleted — retry.")

def _get_job_or_404(job_id, current_user, db, action="job.view"):
    """The job, if the caller may see it and do `action` to it.

    A job outside the caller's scope (`permissions.sees_job`) answers 404 "Job
    not found", the same as a missing id, so another firm's ids cannot be
    probed; a job in scope whose action the role does not hold answers 403.
    """
    from app.core.permissions import can, sees_job
    job = db.query(ExtractionJob).filter(ExtractionJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    # A job the history cutoff hides does not exist for a demo account —
    # the same answer as a job that really does not exist. Hiding it from the
    # list but serving it by id would leave it reachable from a bookmark or a
    # stale poll, and its results and its export with it.
    if job_hidden_by_cutoff(current_user, job):
        raise HTTPException(status_code=404, detail="Job not found")
    if not sees_job(current_user, job):
        raise HTTPException(status_code=404, detail="Job not found")
    if not can(current_user, action, job):
        raise HTTPException(status_code=403, detail="Not permitted for this role")
    return job
