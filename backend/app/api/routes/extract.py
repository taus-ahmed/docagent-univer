"""
Extraction routes: upload, jobs, results, edits, cancel, hard delete, export.

This module is the router. The work it routes to lives in `app/services/`
(split out of this file in round 13, moved verbatim — see
`scripts/split_proof.py` and `tests/reports/extract_split_before.json`):

    uploads            upload names, page selection, content checks
    template_parsing   template grid -> template_data, registry loader
    vision_prompts     the image path's prompt builder
    result_processing  pdfplumber validation, normalisation, result processors
    excel_cells        cell values/formats, provenance comments, styles, widths
    excel_legacy       legacy layout/table/form/mixed/flat writers
    excel_slot         the slot writer, inferred sheets, `_write_excel`
    job_worker         the background job thread (extraction, persistence, cancel)
    edits              value edits addressed by slot

Every moved name is re-exported below, so `from app.api.routes.extract import X`
keeps working. Code that must steer the job thread (tests) patches
`app.services.job_worker`, whose globals the thread reads.

Kept here: tenancy (`resolve_client_id`, `load_template_for_user`), the upload
route and `_start_extraction_job`, the export routes, the job and edit routes,
and `_get_job_or_404` (access through `app/core/permissions.py`).
"""

import io
import sys
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
from app.core.demo import (check_upload_file, check_upload_quota,
                           check_uploads_enabled, filter_demo_history,
                           filter_options, is_demo_user, job_hidden_by_cutoff)
from app.core import demo_audit
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
from log_safety import exc_brief  # noqa: E402
# --split-reexports--
from app.services.edits import (  # noqa: E402,F401  moved, re-exported
    _edit_field,
    _field_refs,
    _reconcile_edits,
    _ref_for_label,
    _save_edit,
)
from app.services.job_worker import (  # noqa: E402,F401  moved, re-exported
    CANCELLED_FILE_MSG,
    CANCEL_POLL_SEC,
    _FINANCIAL_CRITICAL_TYPES,
    _MULTI_RECORD_SUFFIX_RE,
    _cancel_probe,
    _cross_validate_section_totals,
    _document_index,
    _extract_image_with_template,
    _extract_with_template,
    _extract_with_template_inner,
    _finish_cancelled,
    _flag_batch_duplicates,
    _flag_summary,
    _is_storage_key,
    _persist_cancelled,
    _persist_failure,
    _post_anomaly,
    _post_categorize,
    _post_summarize,
    _release_copy,
    _resolve_source,
    _result_display_name,
    _run_extraction_job,
    _run_extraction_sync,
    _value_requires_review,
)
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
            # ids only: neither firm's client_id goes in the log
            print(f"[TENANCY] user {current_user.id} named another client_id; "
                  "using the token's own", flush=True)
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
    # the same answer as a missing id: another firm's template ids cannot be probed
    raise HTTPException(status_code=404, detail="Template not found")


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
    passwords: Optional[list] = None,
) -> ExtractUploadResponse:
    """Validate, persist and start one extraction job. The whole upload path.

    It was the body of `POST /api/extract/upload`. It is a function so that the
    demo's "use this sample document" button cannot become a second, thinner
    pipeline that forgets a check - it runs the ordinary one, as the ordinary
    user, with the same limits and the same tenant resolution.
    """
    from app.core.lifecycle import RESTART_REFUSAL, draining
    if draining():
        # Part 2.3: shutting down — a job started now would be cut off
        raise HTTPException(status_code=503, detail=RESTART_REFUSAL,
                            headers={"Retry-After": "60"})
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
                src.filename, content,
                (passwords or [None] * len(sources))[sources.index(src)]
                if passwords and sources.index(src) < len(passwords) else None)
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
    # The firm's monthly page limit (core/usage.py), before anything is stored
    # or started: a refusal leaves no job row and costs no model call. Pages
    # are what will be read — the selected pages of each file when a subset
    # was asked for.
    from app.core.usage import PAGES_MARK, check_page_quota
    job_pages = sum(len(selected_pages_list) if selected_pages_list else n
                    for _, n in page_counts)
    check_page_quota(db, client_id, job_pages)

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
        job.set_mark(PAGES_MARK, job_pages)
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
                    "original_filenames": [src.original_filename for src in sources],
                    # IN MEMORY ONLY: handed to the thread, never stored,
                    # logged or returned (Part 1.7)
                    "passwords": list(passwords) if passwords else None},
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
    # Part 1.7: per-file PDF passwords, a JSON array in file order (null for a
    # file without one). Used in memory only; never stored, logged or returned.
    passwords: Optional[str] = Form(None),
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
        passwords=_parse_passwords(passwords, len(files)),
    )


@router.post("/extract/page-count")
async def get_pdf_page_count(
    files: list[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
):
    """Pages per uploaded file, for the extract page's "choose pages" dialog.
    Reads only the posted bytes; stores nothing. A locked PDF answers 1 (its
    pages are counted again, with its password, when it is uploaded).

    Restored (Part A7): a cleanup removed it while the page still called it,
    and the dialog silently stopped appearing."""
    if len(files) > settings.MAX_FILES_PER_BATCH:
        raise HTTPException(status_code=400, detail=f"Max {settings.MAX_FILES_PER_BATCH} files.")
    results = []
    for f in files:
        content = await f.read()
        safe_name, _kind, page_count = _validate_upload_content(f.filename, content)
        results.append({"filename": safe_name, "page_count": page_count})
    return results


def _parse_passwords(raw, n_files):
    """A JSON array of passwords (or nulls) in file order, or None. A
    malformed value is refused without echoing it."""
    if raw is None or str(raw).strip() == "":
        return None
    try:
        vals = json.loads(raw)
    except ValueError:
        raise HTTPException(status_code=400,
                            detail="passwords must be a JSON array in file order")
    if not isinstance(vals, list) or len(vals) > n_files or not all(
            v is None or isinstance(v, str) for v in vals):
        raise HTTPException(status_code=400,
                            detail="passwords must be a JSON array of strings or nulls, "
                                   "one per file at most")
    return [v or None for v in vals]


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


# ==============================================================================
# SECTIONED MULTI-PASS EXTRACTION (parallel column templates)
# ==============================================================================


# ==============================================================================
# BACKGROUND THREAD
# ==============================================================================


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
def delete_job_data(job_id: int, confirm: bool = False, db: Session=Depends(get_db),
                    current_user: User=Depends(get_current_user)):
    """Hard delete: the job's files, page readings and results go; the job
    record stays, marked deleted (`core/job_lifecycle.purge_job`). The job's
    own user, a tenant admin of its firm, or a platform admin; another firm's
    job is 404. `?confirm=true` is required — an explicit second step, since
    nothing can bring the data back."""
    from app.core.job_lifecycle import RUNNING, PurgeIncomplete, purge_job
    from app.core.permissions import can
    job = _get_job_or_404(job_id, current_user, db)
    if not (can(current_user, "job.delete", job) or job.user_id == current_user.id):
        raise HTTPException(status_code=403, detail="Not permitted for this role")
    if not confirm:
        raise HTTPException(status_code=400,
                            detail="Deleting cannot be undone: repeat with ?confirm=true.")
    if job.status in RUNNING:
        raise HTTPException(status_code=409,
                            detail="The job is still running: cancel it first, then delete.")
    try:
        return purge_job(db, job, current_user)
    except PurgeIncomplete as e:
        raise HTTPException(status_code=500,
                            detail=f"{e.args[0]} stored files could not be deleted; "
                                   "nothing was marked deleted — retry.")


@router.get("/usage")
def get_usage(client_id: Optional[str] = None, db: Session = Depends(get_db),
              current_user: User = Depends(get_current_user)):
    """This month's pages and the firm's limit (core/usage.py). A firm's
    administrator sees its own firm, whatever it names; the platform admin
    names the firm. Anyone else: 403."""
    from app.core.permissions import can
    from app.core.usage import usage
    if not can(current_user, "stats.view"):
        raise HTTPException(status_code=403, detail="Not permitted for this role")
    if can(current_user, "tenant.all"):
        if not client_id:
            raise HTTPException(status_code=400, detail="Name the firm: ?client_id=")
        return usage(db, client_id)
    return usage(db, current_user.client_id)


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
