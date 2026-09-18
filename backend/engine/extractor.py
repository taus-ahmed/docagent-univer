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




def _with_label_provenance(template_data, page_lines):
    """`template_data` + this DOCUMENT's label provenance, on a copy.

    Provenance is a property of (label, document), never of the schema. A
    batch-reused schema is shared by every document of its kind, so storing the
    quotes on it handed the second statement the FIRST one's lines — including
    its statement number, which `test_batch_isolation` caught as contamination.
    The copy is shallow and the schema itself is never mutated, because the
    next document of this kind gets the same object.
    """
    if not template_data or not template_data.get("inferred"):
        return template_data
    out = dict(template_data)
    out["inferred_label_provenance"] = _label_provenance(
        out.get("layout"), page_lines)
    return out


def _label_provenance(grid, page_lines):
    """{cell_ref: {source, page}} for every inferred label PRINTED on the page.

    I5 mode 2. An inferred label is the model's own word for a value, and by
    standing policy it does not have to be the document's (CLAUDE.md, "Naming":
    a letterhead company name has no printed label at all, and an ambiguous one
    is deliberately replaced by the precise term). So this REQUIRES nothing,
    rejects nothing and renames nothing — it records the line a label was read
    from when there is one.

    Measured before it existed: of 2,858 inference labels in the recorded
    corpus, 1,599 are printed verbatim and 1,259 are not, and nothing could
    tell which of those 1,259 were policy and which were contamination, because
    a label carried no location. This is what makes that answerable.

    Kept OUT of the grid on purpose. A grid cell is `{value, style}` — text a
    user could have typed — and that is the invariant the whole one-rule shape
    system rests on. This travels beside it, exactly as `field_provenance` is
    kept apart from `extracted_data`.
    """
    if not page_lines:
        return {}
    from text_layer import find_line, line_page, text_from_lines
    lines = [ln for pg in page_lines for ln in (pg or [])]
    if not lines:
        return {}
    out = {}
    for key, cell in (grid or {}).get("cells", {}).items():
        value = str((cell or {}).get("value") or "").strip()
        if not value:
            continue
        ln = find_line(lines, value)
        if not ln:
            continue
        try:
            r, c = (int(x) for x in key.split(","))
        except (ValueError, AttributeError):
            continue
        out[_cell_ref(r, c)] = {"source": text_from_lines([ln]),
                                "page": line_page(ln)}
    return out


def _cell_ref(row, col):
    letters = ""
    c = int(col)
    while True:
        letters = chr(ord("A") + c % 26) + letters
        c = c // 26 - 1
        if c < 0:
            break
    return f"{letters}{int(row) + 1}"


def _infer_template_data(orchestrator, file_path, doc_text_pages, page_images,
                         page_lines=None):
    """Phase 3 — read the document, design a template for it, and return the
    same `template_data` a saved template would produce. Returns None if the
    document's structure could not be worked out.

    The point is that nothing downstream can tell the difference: the inferred
    grid goes through `compute_shape` and `run_slot_extraction` exactly as a
    user's grid does. There is no separate no-template engine.
    """
    from shape_inference import build_grid, infer_template, signature
    from template_shape import compute_shape, is_usable

    # The canonical vocabulary is chosen by keyword pre-screening — no LLM
    # call, and only a hint: the model still decides the document type itself.
    # I5 mode 1 — the SAME pages with their column breaks kept, so a block
    # heading printed beside another one is not read as owning its neighbour's
    # lines. `doc_text_pages` is untouched: it is what `verify_span` grounds
    # against and what slot extraction is prompted with.
    column_pages, marked = [], 0
    if page_lines:
        from text_layer import column_text_pages
        column_pages, marked = column_text_pages(page_lines, doc_text_pages)
        if marked:
            _log("INFER", f"{file_path.name}: {marked} page(s) carry a column "
                          f"break; inference reads them with columns kept")
    inferred = infer_template(orchestrator, doc_text_pages, page_images,
                              file_path.name,
                              doc_type_hint=_hint_type("\n".join(
                                  str(t or "") for t in (doc_text_pages or []))),
                              column_pages=column_pages or None)
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
    # Positional evidence, one list of visual lines per page. Kept alongside
    # the text rather than replacing it: the model reads text, validation
    # reads geometry. See engine/text_layer.py.
    doc_page_lines = list(getattr(doc, "page_lines", []) or [])
    doc_text = doc.extracted_text or ""
    page_images = doc.page_images_b64 or []
    if selected_pages and page_images:
        keep = [i - 1 for i in selected_pages if 0 < i <= len(page_images)]
        if keep:
            page_images = [page_images[i] for i in keep]
            doc_text_pages = [doc_text_pages[i] for i in keep if i < len(doc_text_pages)]
            doc_page_lines = [doc_page_lines[i] for i in keep if i < len(doc_page_lines)]

    # I10 — a page whose text layer had to be un-shredded. FILE page numbers,
    # so a split document still names the page the reader can turn to.
    shredded = list(getattr(doc, "shredded_pages", []) or [])
    # Checks the READER could not perform, as distinct from checks that came
    # back clean. See engine/text_layer.py's seam and
    # docs/OCR-READER-SEAM-DESIGN.md §8.
    unchecked_overprint = list(getattr(doc, "unchecked_overprint_pages", []) or [])
    unchecked_shred = list(getattr(doc, "unchecked_shred_pages", []) or [])

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
               default_doc_type=default_doc_type, start=start,
               page_lines=doc_page_lines)

    def _note_shredded(results):
        """Say it on the RESULT, not only in the log (I10).

        A shredded page is the shape that produced round 2's run 12: a BoA
        statement of ~130 transactions came back as two rows that summed
        correctly, because only 3 of those lines survived into the prompt. The
        rows are recovered now, but a page that needed this much repair is one
        a person should look at, and a log line nobody reads is not a warning.

        ⚠ Deliberately NOT a scanned-page warning. See the note in
        `core/preprocessor.py`: a thin OCR text layer scores 1.00 and says
        nothing here.
        """
        if not shredded:
            return results
        pages = ", ".join(str(n) for n in shredded)
        for r in results or []:
            ed = getattr(r, "extracted_data", None)
            if not isinstance(ed, dict):
                continue
            ed.setdefault("validation_notes", []).append(
                f"page {pages}: the text layer was SHREDDED — several texts "
                f"are set at different font sizes over the same lines and "
                f"their characters interleave. They have been separated and "
                f"the page re-read, but check this page against the original. "
                f"(This check does not detect scanned pages or thin OCR "
                f"text layers.)")
            ed["needs_review"] = True
            ed.setdefault("validation", {})["shredded_pages"] = list(shredded)
        return results

    def _note_unchecked(results):
        """Say which checks the READER could not perform (reader seam, §8).

        A check that did not run is not a check that passed. `shredded_pages`
        is populated when something was found and repaired; these are populated
        when something was never looked at, so the note has to say so in as
        many words rather than borrowing the same phrasing.

        ⚠ DELIBERATELY DOES NOT SET `needs_review`. `shredded_pages` sets it
        because a shredded page is one a person should check. Whether "this
        reader could not run one of the checks" deserves the same treatment
        depends on how many documents arrive that way, and we have never seen a
        client document — if most of them are scans, setting it on every one
        makes the flag mean nothing, which is how the coverage indicator failed.
        Deferred at docs/OCR-READER-SEAM-DESIGN.md §10.4.
        """
        if not unchecked_overprint and not unchecked_shred:
            return results
        for r in results or []:
            ed = getattr(r, "extracted_data", None)
            if not isinstance(ed, dict):
                continue
            v = ed.setdefault("validation", {})
            if unchecked_overprint:
                pages = ", ".join(str(n) for n in unchecked_overprint)
                ed.setdefault("validation_notes", []).append(
                    f"page {pages}: overprint detection was NOT PERFORMED — "
                    f"the reader used for this document cannot supply "
                    f"character geometry. This does not mean the page is "
                    f"clean; it means the check did not run.")
                v["unchecked_overprint_pages"] = list(unchecked_overprint)
            if unchecked_shred:
                pages = ", ".join(str(n) for n in unchecked_shred)
                ed.setdefault("validation_notes", []).append(
                    f"page {pages}: the shredded-text-layer check was NOT "
                    f"PERFORMED — the reader used for this document cannot "
                    f"read the same page both with and without font size, and "
                    f"that comparison is the check. This does not mean the "
                    f"page is clean; it means the check did not run.")
                v["unchecked_shred_pages"] = list(unchecked_shred)
        return results

    # ── DOCUMENT BOUNDARIES ──
    # One file was one document, unconditionally: three invoices merged into
    # one PDF produced 13 field slots where 3 x 13 were needed, the model
    # answered for one of them, and the other two were lost with no error and
    # no note. Splitting keeps slot addressing exactly as it is — each
    # document gets the full slot set, its own grounding and its own result —
    # and the Excel writer already stacks a list of results.
    from doc_boundaries import split as _split_documents

    slices, why = _split_documents(doc_text_pages, doc_page_lines, page_images)
    if len(slices) > 1:
        _log("SPLIT", f"{file_path.name}: {len(slices)} documents in one file "
                      f"({why}) — extracting each separately")
        results = []
        for n, (texts, lines, images, first_page) in enumerate(slices, 1):
            sub = dict(ctx)
            sub["doc_text"] = "\n\n".join(texts)
            sub["doc_text_pages"] = texts
            sub["page_lines"] = lines
            sub["page_images"] = images
            part = _extract_one(orchestrator, file_path, template_data, sub,
                                sub["doc_text"], texts, images,
                                default_doc_type, batch_schemas)
            last = first_page + max(len(texts) - 1, 0)
            span = (f"page {first_page}" if first_page == last
                    else f"pages {first_page}-{last}")
            for r in part:
                r.filename = f"{file_path.name} [{n} of {len(slices)}]"
                ed = getattr(r, "extracted_data", None)
                if isinstance(ed, dict):
                    ed["document_index"] = n
                    ed["document_count"] = len(slices)
                    ed["source_pages"] = [first_page, last]
                    ed.setdefault("validation_notes", []).append(
                        f"document {n} of {len(slices)} in "
                        f"{file_path.name} ({span})")
            results += part
        return _note_unchecked(_note_shredded(results))

    return _note_unchecked(_note_shredded(
        _extract_one(orchestrator, file_path, template_data, ctx, doc_text,
                     doc_text_pages, page_images, default_doc_type,
                     batch_schemas)))


def _extract_one(orchestrator, file_path, template_data, ctx, doc_text,
                 doc_text_pages, page_images, default_doc_type, batch_schemas):
    """One DOCUMENT — infer a template if there is none, route, extract.

    Split out of `run_extraction` so a file holding several documents can run
    it once per document. Everything in here is exactly what a single-document
    file always did; the only thing that changed is how many times it happens.
    """
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
            trial["template_data"] = _with_label_provenance(
                reused, ctx.get("page_lines"))
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
                                             doc_text_pages, page_images,
                                             ctx.get("page_lines"))
        if template_data is None:
            from app.api.routes.extract import _fail
            return [_fail(file_path.name,
                          "Could not work out this document's structure. "
                          "Select a template and try again.")]
        template_data = _with_label_provenance(template_data,
                                               ctx.get("page_lines"))
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


