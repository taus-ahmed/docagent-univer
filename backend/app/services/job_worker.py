"""The background job thread: per-file extraction, post-processing, persistence, cancellation.

Moved verbatim from app/api/routes/extract.py (round 13); extract.py re-exports every name.
"""

import app.services.paths  # noqa: F401  (engine on sys.path)
from cancellation import Cancelled
from app.models import DocumentResult
from typing import Optional
from pathlib import Path
from app.core.confidence import UNVERIFIED
from app.services.vision_prompts import _build_vision_prompt
from app.services.result_processing import _fail
from app.services.template_parsing import _get_unguided_prompt
from app.services.uploads import _is_image_file
from app.services.result_processing import _job_error_message
from app.services.uploads import _load_image_as_png_bytes
from app.services.result_processing import _process_vision_result
from datetime import datetime
from log_safety import doc_ref
from log_safety import exc_brief
from app.core.storage import get_storage
import json
from log_safety import print_safe_traceback
import re
from app.config import settings
import sys
import time
from cancellation import watching
# --imports-end--


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


def _commit_file(session, staged) -> None:
    """Store every record of one file in ONE transaction, or none of them."""
    for doc, _ok, _tokens in staged:
        session.add(doc)
    session.commit()


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

                # ONE FILE, ONE TRANSACTION. Every record of this file is
                # built first (`staged`) and nothing touches the session until
                # one last cancel check has passed; then all of them are
                # committed together (`_commit_file`). A cancel before that
                # check — or raised while a record is being built — discards
                # the whole file, which is then listed as cancelled; a cancel
                # after it lets the file complete and be saved whole. A
                # record could no longer be stored half-way through a file.
                staged = []          # (doc, success, tokens)
                file_failures = []   # (ref, error) for records not built
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
                        doc_tokens = (result.extraction_response.tokens_used
                                      if result.extraction_response else 0) or 0
                        staged.append((doc, bool(result.success), doc_tokens))

                    except Exception as save_err:
                        print(f"[THREAD] SAVE ERROR for {doc_ref(result.filename)}: {exc_brief(save_err)}", flush=True)
                        print_safe_traceback()
                        file_failures.append((getattr(result, "filename", fp), save_err))

                # The last moment a cancel discards this file.
                if is_cancelled(force=True):
                    raise Cancelled()
                try:
                    _commit_file(session, staged)
                except Exception as commit_err:
                    session.rollback()
                    print(f"[THREAD] SAVE ERROR for {doc_ref(display_filename)}: "
                          f"{exc_brief(commit_err)} — none of its "
                          f"{len(staged)} record(s) were stored", flush=True)
                    print_safe_traceback()
                    staged = []
                    file_failures.append((display_filename, commit_err))
                for doc, ok, doc_tokens in staged:
                    total_tokens_used += doc_tokens
                    doc_cost = (doc_tokens / 1_000_000) * 0.15
                    total_cost_usd += doc_cost
                    print(f"[THREAD] saved: {doc_ref(doc.filename)} "
                          f"tokens={doc_tokens} cost=${doc_cost:.5f} "
                          f"| job_total={total_tokens_used} tokens "
                          f"${total_cost_usd:.4f}", flush=True)
                    if ok:
                        successful += 1
                        if doc.needs_review:
                            needs_review += 1
                    else:
                        failed += 1
                for ref, err in file_failures:
                    failed += 1
                    _persist_failure(Session, job_id, ref, err)

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
