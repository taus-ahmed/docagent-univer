"""
DocAgent — Extraction Engine
============================

The single extraction entry point. There is ONE pipeline:

    template -> shape -> slot-directed extraction    (engine/slot_extractor.py)

A document with no template takes the same path; its shape comes from
inference (engine/shape_inference.py) instead of from the user, and the
inferred template is handed back so it can be saved and reused.

Phase 2d removed the USE_NEW_EXTRACTOR flag, the legacy inline pipeline and
the layout/field/CBM paths. Phase 3 removed the three-layer no-template
engine. Nothing silently falls back to anything.
"""

import re
import time
from pathlib import Path


# ── small helpers ────────────────────────────────────────────────────────────

def _log(tag, msg):
    print(f"[{tag}] {msg}", flush=True)


def _norm(s) -> str:
    """Lowercase, strip non-alphanumerics — for fuzzy heading/section matching."""
    return re.sub(r'[^a-z0-9]+', '', str(s or "").lower())


def _digits(s) -> str:
    return re.sub(r'[^0-9]', '', str(s or ""))


def _num(s):
    """Parse a money/number string to float, or None."""
    t = str(s or "").strip().replace(",", "").replace("$", "").replace("£", "").replace("€", "")
    if t.startswith("(") and t.endswith(")"):
        t = "-" + t[1:-1]
    try:
        return float(t)
    except (ValueError, TypeError):
        return None


def _llm_json(orchestrator, prompt, system, images=None, text="", model=None,
              temperature=0.1):
    """
    One Gemini call (vision-first, all images), returning (parsed_dict_or_None,
    response_or_None). 3 attempts with 2s backoff; text fallback when vision fails.
    `model` pins the Gemini tier (e.g. "gemini-2.5-flash" for accuracy-critical calls).
    `temperature` is 0 for shape inference — see `infer_template`.
    """
    resp = None
    base_delay = 1
    for attempt in range(3):
        err_txt = ""
        try:
            if images:
                resp = orchestrator.llm.extract(image_b64=images, prompt=prompt,
                                                system_instruction=system, model=model,
                                                temperature=temperature)
                if (not getattr(resp, "success", False)) and text:
                    resp = orchestrator.llm.extract(text=text, prompt=prompt,
                                                    system_instruction=system, model=model,
                                                    temperature=temperature)
            elif text:
                resp = orchestrator.llm.extract(text=text, prompt=prompt,
                                                system_instruction=system, model=model,
                                                temperature=temperature)
            else:
                return None, None
            if resp and getattr(resp, "success", False) and getattr(resp, "parsed_json", None):
                return resp.parsed_json, resp
            err_txt = str(getattr(resp, "error", "") or "")
        except Exception as e:
            err_txt = str(e)
            _log("LLM", f"error attempt {attempt+1}: {e}")
        if attempt < 2:
            # E5 — exponential backoff on rate limiting: 1s, 2s, 4s... capped at
            # 30s. Non-429 failures keep the original fixed 2s retry delay.
            low = err_txt.lower()
            if "429" in err_txt or "rate limit" in low or "resource_exhausted" in low or "quota" in low:
                delay = min(base_delay * (2 ** attempt), 30)
                _log("RATE", f"429 received — backing off {delay}s before retry")
                time.sleep(delay)
            else:
                time.sleep(2)
    return None, resp


def _infer_template_data(orchestrator, file_path, doc_text_pages, page_images):
    """Phase 3 — read the document, design a template for it, and return the
    same `template_data` a saved template would produce. Returns None if the
    document's structure could not be worked out.

    The point is that nothing downstream can tell the difference: the inferred
    grid goes through `compute_shape` and `run_slot_extraction` exactly as a
    user's grid does. There is no separate no-template engine.
    """
    from shape_inference import build_grid, infer_template, signature
    from template_shape import compute_shape, is_usable

    inferred = infer_template(orchestrator, doc_text_pages, page_images,
                              file_path.name)
    if not inferred:
        return None
    grid = build_grid(inferred)
    shape = compute_shape(grid, log=lambda m: _log("INFER", m))
    if not is_usable(shape):
        _log("INFER", f"{file_path.name}: inferred template has no slots")
        return None

    sig = signature(inferred)
    _log("INFER", f"{file_path.name}: shape {sig} — "
                  f"{len(shape['field_slots'])} slots, "
                  f"{len(shape['repeat_bands'])} band(s), "
                  f"needs {shape['required_columns']} columns")
    return {
        "mode": "layout",
        "layout": grid,
        "doc_type": inferred["document_type"],
        "name": inferred["title"] or file_path.stem,
        "shape": shape,
        "inferred": inferred,
        "shape_signature": sig,
        "regions": {"primary_mode": "slot"},
    }


# ══════════════════════════════════════════════════════════════════════════════
# BATCH SCHEMA REUSE  (Phase 8)
# ══════════════════════════════════════════════════════════════════════════════
#
# Inference names the columns, and naming is the one thing it does not do the
# same way twice: on the SAME document, run to run, "Doc No" became "Document
# Number" and "Company EIN" became "Company Tax ID". `signature()` hashes those
# names, and the exporter groups sheets by signature — so fifty invoices with
# the identical printed layout produced up to fifty sheets, each with slightly
# different column headings, instead of one sheet with fifty rows. That is
# worse than any accuracy number: it defeats the point of batch extraction.
#
# The fix is not to make inference more stable. It is to run it ONCE per
# document kind per job and reuse the answer, which drives within-batch
# variance to exactly zero — the schema is not re-derived, so it cannot differ.
#
# Two things this must not break:
#
#   MIXED BATCHES. A job holding an invoice, a statement and a cheque must
#   still produce three shapes. Reuse is keyed by document type, decided by
#   `classify_by_hints` — keyword pre-screening, no LLM call, no cost — so a
#   document only inherits a schema built for its own kind.
#
#   TWO LAYOUTS OF THE SAME TYPE. Two invoice designs in one job both classify
#   as sales_invoice, and the second would inherit a schema with the wrong
#   fields. So a reused schema has to EARN it: the document is extracted with
#   it, and if it fills too few of the slots the result is thrown away and the
#   document gets its own inference. A reused schema that fits costs one LLM
#   call instead of two; one that does not costs three, and is rare.

#: A reused schema must fill at least this share of its field slots, or it is
#: judged not to fit this document and inference runs for it after all. Set
#: from the observed fill rates: a fitting schema fills nearly all of them, a
#: mismatched one fills almost none, and there is a wide gap in between.
_REUSE_MIN_FILL = 0.4


def _hint_type(doc_text):
    """Cheap document-type guess — keyword pre-screening, NO LLM call.

    Only ever used to decide which already-inferred schema to OFFER a document.
    A wrong guess costs an extra inference call (the fill-rate check rejects
    the schema); it can never put a value in the wrong place, because the
    schema still has to fit before anything is kept.
    """
    try:
        from app.api.routes.extract import _classify_by_hints
        return _classify_by_hints(doc_text or "") or ""
    except Exception:
        return ""


def _fill_rate(results):
    """Share of the template's field slots that came back with a value."""
    for r in results or []:
        ed = getattr(r, "extracted_data", None)
        if not isinstance(ed, dict):
            continue
        slots = ((ed.get("slot_map") or {}).get("fields") or [])
        if not slots:
            continue
        filled = len(ed.get("extracted_fields") or {})
        return filled / len(slots)
    return 0.0


# Document types routed to slot-directed extraction. Phase 1 scoped this to
# bank_statement so the change could be measured in isolation; Phase 2c widens
# it to every document type, because slot addressing by (row label, column
# header) is what removes the layout path's 2-column ceiling.
# None = all document types.
_SLOT_DOC_TYPES = None


def run_extraction(orchestrator, file_path, template_data, selected_pages=None,
                   batch_schemas=None):
    """
    Single entry point. Returns list[DocumentExtractionResult].

    Two outcomes, decided at the start:

      no template (or a template with no slots) -> infer one, then the same path
      a template with a usable shape            -> slot-directed extraction

    The shape says how many columns the template needs; slot addressing serves
    any number, so the only way to fail is a template with nowhere to put
    anything — and that fails loudly, with a message saying what to change.

    `batch_schemas` is a caller-owned dict, one per JOB, that lets documents of
    the same kind share a single inferred schema instead of each inferring its
    own differently-named copy. Pass None (the default) to infer per document,
    which is what a single-document call wants. See the BATCH SCHEMA REUSE
    block above.
    """
    from core.preprocessor import preprocess_file

    file_path = Path(file_path)
    default_doc_type = (template_data or {}).get("doc_type", "other")
    start = time.time()

    # ── Preprocess (shared by all paths) ──
    doc = preprocess_file(file_path)
    doc_text_pages = list(getattr(doc, "page_texts", []) or [])
    doc_text = doc.extracted_text or ""
    page_images = doc.page_images_b64 or []
    if selected_pages and page_images:
        keep = [i - 1 for i in selected_pages if 0 < i <= len(page_images)]
        if keep:
            page_images = [page_images[i] for i in keep]
            doc_text_pages = [doc_text_pages[i] for i in keep if i < len(doc_text_pages)]

    ftype = (doc.file_type if getattr(doc, "file_type", "") == "image"
             else ("digital_pdf" if getattr(doc, "has_meaningful_text", False) else "scanned_pdf"))
    _log("ROUTE", f"{file_path.name}: file_type={ftype} pages={len(page_images)} "
                  f"text_len={len(doc_text)}")

    # The binding map is gone with the paths that consumed it: routing is now
    # arithmetic on the template's stored shape, and slot extraction addresses
    # cells directly. Kept as None for the no-template path's signature.
    binding_map = None

    ctx = dict(orchestrator=orchestrator, file_path=file_path, template_data=template_data,
               binding_map=binding_map, page_images=page_images, doc_text=doc_text,
               doc_text_pages=doc_text_pages, file_type=ftype,
               default_doc_type=default_doc_type, start=start)

    # ── NO TEMPLATE (Phase 3) — infer one, then take the SAME path ──
    # An empty grid (no labels, no headers) gives extraction nothing to anchor
    # to and is treated exactly like no template at all.
    if template_data and template_data.get("mode", "layout") == "layout":
        tpl_cells = (template_data.get("layout") or {}).get("cells") or {}
        if not any(isinstance(cd, dict) and str(cd.get("value") or "").strip()
                   for cd in tpl_cells.values()):
            _log("ROUTE", f"{file_path.name}: EMPTY TEMPLATE (0 labelled cells) "
                          f"-> treated as no template")
            template_data = None
            ctx["template_data"] = None

    if not template_data:
        # BATCH REUSE — a schema already inferred for this document's kind,
        # earlier in this same job. See the block comment above.
        reused = None
        hint = _hint_type(doc_text) if batch_schemas is not None else ""
        if hint and hint in (batch_schemas or {}):
            reused = batch_schemas[hint]
            _log("INFER", f"{file_path.name}: reusing the {hint} schema "
                          f"inferred earlier in this job "
                          f"(shape {reused.get('shape_signature')}) "
                          f"— no inference call")
            trial = dict(ctx)
            trial["template_data"] = reused
            trial["default_doc_type"] = reused.get("doc_type", default_doc_type)
            from slot_extractor import run_slot_extraction
            results = run_slot_extraction(**trial)
            rate = _fill_rate(results)
            if rate >= _REUSE_MIN_FILL:
                _log("INFER", f"{file_path.name}: reused schema fits "
                              f"({rate:.0%} of slots filled)")
                return results
            # It did not fit — a different layout of the same document type.
            # Throw the result away and infer for this document. Nothing
            # partial is kept: a half-filled sheet from the wrong schema is
            # worse than the cost of one more call.
            _log("INFER", f"{file_path.name}: reused schema does NOT fit "
                          f"({rate:.0%} of slots filled, need "
                          f"{_REUSE_MIN_FILL:.0%}) — inferring for this "
                          f"document instead")

        template_data = _infer_template_data(orchestrator, file_path,
                                             doc_text_pages, page_images)
        if template_data is None:
            from app.api.routes.extract import _fail
            return [_fail(file_path.name,
                          "Could not work out this document's structure. "
                          "Select a template and try again.")]
        ctx["template_data"] = template_data
        default_doc_type = template_data.get("doc_type", default_doc_type)
        ctx["default_doc_type"] = default_doc_type
        # Offer this schema to the rest of the job. Keyed by the type the
        # model itself decided, so the next document of this kind reuses it
        # verbatim rather than re-deriving a differently-named copy.
        if batch_schemas is not None:
            key = template_data.get("doc_type") or hint
            if key and key not in batch_schemas:
                batch_schemas[key] = template_data
                _log("INFER", f"{file_path.name}: schema for '{key}' cached "
                              f"for the rest of this job")

    # ── PATH SELECTION BY ARITHMETIC (Phase 2b) ──
    # How many columns does this template need, and can the path serve that
    # many? Replaces matching the user's column headers against 16 hardcoded
    # English words, which silently misrouted any template headed "2024",
    # "USD", "Q4", a currency symbol, a non-English word, or nothing.
    from template_shape import choose_path, compute_shape

    shape = (template_data or {}).get("shape")
    if not shape:
        shape = compute_shape(template_data.get("layout") or {},
                              log=lambda m: _log("SHAPE", m))
    decision = choose_path(shape, default_doc_type, _SLOT_DOC_TYPES)

    if decision.get("error"):
        # No path fits. Fail the document loudly with a message that says what
        # to change — never a blank or partial sheet with no explanation.
        _log("ROUTE", f"{file_path.name}: CANNOT EXTRACT — {decision['error']}")
        from app.api.routes.extract import _fail
        return [_fail(file_path.name, decision["error"])]

    path = decision["path"]
    _log("ROUTE", f"{file_path.name}: needs {decision['required_columns']} column(s) "
                  f"-> {path} path ({decision['reason']})")

    from slot_extractor import run_slot_extraction
    return run_slot_extraction(**ctx)
