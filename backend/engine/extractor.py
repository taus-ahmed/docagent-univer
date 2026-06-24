"""
DocAgent — Clean Extraction Engine (v3)
=======================================

A clean, vision-first replacement for the inline extraction pipeline that lived
in app/api/routes/extract.py (_extract_with_template_inner /
_vision_extract_all_documents). Activated by the USE_NEW_EXTRACTOR feature flag;
when off, the legacy path runs unchanged (safe rollback).

The 8-step architecture (everything we have learned):

  1. PREPROCESS      — text + page image for every page (poppler required).
  2. BOUNDARY        — layout templates = ONE document; field templates may split.
  3. BINDING MAP     — neighbor-matrix cell roles (compute_binding_map, reused).
  4. PROMPT          — layout mode (unlabeled) vs field mode (labeled), reused
                       via _build_vision_prompt (auto-branches on binding_map).
  5. GEMINI CALL     — always send page images; retry on 503; enforce the layout
                       format and convert extracted_fields<->layout_sections.
  6. VALIDATION      — pdfplumber cross-validation + section-total check (reused
                       inside _process_vision_result / _cross_validate_section_totals).
  7. RESULT ASSEMBLY — DocumentExtractionResult with extraction_json shape that
                       the existing save path and Excel writers already consume.
  8. EXCEL           — handled at export time by the existing _write_layout_excel
                       / _write_form_excel writers (they read the saved JSON).

Heavy primitives are imported lazily from app.api.routes.extract to avoid code
duplication and import cycles.
"""

import time
from pathlib import Path


def _unwrap_doc(parsed):
    """Return the per-document dict, unwrapping a Gemini documents[] wrapper."""
    if (isinstance(parsed, dict) and isinstance(parsed.get("documents"), list)
            and parsed["documents"] and isinstance(parsed["documents"][0], dict)):
        return parsed["documents"][0]
    return parsed if isinstance(parsed, dict) else {}


def run_extraction(orchestrator, file_path, template_data, selected_pages=None):
    """
    Entry point. Returns list[DocumentExtractionResult] — same contract as the
    legacy _extract_with_template_inner, so _run_extraction_sync is unchanged.
    """
    from app.api.routes.extract import (
        compute_binding_map, _build_vision_prompt, _process_vision_result,
        _convert_extracted_fields_to_layout, _detect_document_boundaries_vision,
        _fail,
    )
    from core.preprocessor import preprocess_file

    file_path = Path(file_path)
    doc_type = template_data.get("doc_type", "other")
    start = time.time()
    results = []

    # ── STEP 1 — PREPROCESS ──────────────────────────────────────────────────
    doc = preprocess_file(file_path)
    doc_text = doc.extracted_text or ""
    page_images = doc.page_images_b64 or []
    if selected_pages and page_images:
        filtered = [page_images[i - 1] for i in selected_pages
                    if 0 < i <= len(page_images)]
        if filtered:
            page_images = filtered
    print(f"[EXTRACTOR] {file_path.name}: text_len={len(doc_text)} "
          f"pages={len(page_images)} has_vision={bool(page_images)}", flush=True)

    # ── STEP 3 — BINDING MAP (computed early; drives mode + boundaries) ───────
    try:
        binding_map = compute_binding_map(template_data, template_data.get("layout", {}))
    except Exception as e:
        print(f"[EXTRACTOR] binding map failed ({e})", flush=True)
        binding_map = None
    if binding_map:
        template_data = {**template_data, "binding_map": binding_map}
    is_layout = bool(binding_map and binding_map.get("_meta", {}).get("has_table_data"))

    # ── STEP 2 — BOUNDARY DETECTION ──────────────────────────────────────────
    # Layout templates (balance sheet / report / statement) are ALWAYS one doc.
    n_pages = max(1, len(page_images))
    if is_layout or n_pages <= 1 or not page_images:
        segments = [{"doc_index": 0, "pages": list(range(n_pages))}]
    else:
        try:
            segs = _detect_document_boundaries_vision(
                page_images, orchestrator, file_path.name, doc_type)
            segments = [{"doc_index": s.get("index", i),
                         "pages": s.get("page_indices", [0])}
                        for i, s in enumerate(segs)] or [{"doc_index": 0, "pages": list(range(n_pages))}]
        except Exception as e:
            print(f"[EXTRACTOR] boundary detection failed ({e}) — single doc", flush=True)
            segments = [{"doc_index": 0, "pages": list(range(n_pages))}]

    print(f"[EXTRACTOR] {file_path.name}: mode={'layout' if is_layout else 'field'} "
          f"segments={len(segments)}", flush=True)

    # ── STEPS 4-7 per document segment ───────────────────────────────────────
    for seg in segments:
        seg_idx = seg["doc_index"]
        pages = seg.get("pages") or [0]
        page_img = None
        if page_images:
            idx = pages[0] if pages and pages[0] < len(page_images) else 0
            page_img = page_images[idx]

        # STEP 4 — PROMPT (auto layout vs field via binding_map)
        system_instruction, prompt = _build_vision_prompt(template_data, doc_text)

        # STEP 5 — GEMINI CALL (vision-first, 3 retries w/ 2s backoff on 503/err)
        extraction, last_err = None, ""
        for attempt in range(3):
            try:
                if page_img:
                    extraction = orchestrator.llm.extract(
                        image_b64=page_img, prompt=prompt,
                        system_instruction=system_instruction)
                    if (not extraction.success) and doc_text:
                        extraction = orchestrator.llm.extract(
                            text=doc_text, prompt=prompt,
                            system_instruction=system_instruction)
                elif doc_text:
                    extraction = orchestrator.llm.extract(
                        text=doc_text, prompt=prompt,
                        system_instruction=system_instruction)
                else:
                    last_err = "no text or image"
                    break
                if extraction and extraction.success and extraction.parsed_json:
                    break
                last_err = (extraction.error if extraction else "no response")[:120]
            except Exception as e:
                last_err = str(e)[:120]
            if attempt < 2:
                print(f"[EXTRACTOR] {file_path.name}: attempt {attempt+1} failed "
                      f"({last_err}) — retrying in 2s", flush=True)
                time.sleep(2)

        if not extraction or not extraction.success or not extraction.parsed_json:
            r = _fail(file_path.name, f"extraction failed: {last_err}")
            r.processing_time_ms = (time.time() - start) * 1000
            results.append(r)
            continue

        raw = extraction.parsed_json
        d0 = _unwrap_doc(raw)

        # STEP 5b — FORMAT ENFORCEMENT / CONVERSION
        if is_layout and isinstance(d0, dict) and not d0.get("layout_sections"):
            print(f"[EXTRACTOR] {file_path.name}: layout response missing "
                  f"layout_sections — enforcing format", flush=True)
            enforce = ("YOU MUST return layout_sections. Do NOT return only "
                       "extracted_fields. The layout_sections key is REQUIRED.\n\n")
            try:
                re_ext = (orchestrator.llm.extract(
                            image_b64=page_img, prompt=enforce + prompt,
                            system_instruction=system_instruction)
                          if page_img else
                          orchestrator.llm.extract(
                            text=doc_text, prompt=enforce + prompt,
                            system_instruction=system_instruction))
                if (re_ext and re_ext.success and re_ext.parsed_json
                        and _unwrap_doc(re_ext.parsed_json).get("layout_sections")):
                    raw, extraction = re_ext.parsed_json, re_ext
                    d0 = _unwrap_doc(raw)
                    print(f"[EXTRACTOR] {file_path.name}: enforcement produced layout_sections", flush=True)
            except Exception as e:
                print(f"[EXTRACTOR] enforcement retry error: {e}", flush=True)
            if not d0.get("layout_sections") and d0.get("extracted_fields"):
                conv = _convert_extracted_fields_to_layout(
                    d0.get("extracted_fields", {}), binding_map or {})
                if conv:
                    d0["layout_sections"] = conv
                    print(f"[EXTRACTOR] {file_path.name}: converted extracted_fields "
                          f"-> layout_sections", flush=True)

        # field mode but model returned layout_sections -> flatten to extracted_fields
        if (not is_layout and isinstance(d0, dict)
                and d0.get("layout_sections") and not d0.get("extracted_fields")):
            ef = {}
            for sec in d0["layout_sections"].values():
                for row in (sec.get("rows", []) if isinstance(sec, dict) else []):
                    if not isinstance(row, dict):
                        continue
                    rn, lc, vc = row.get("row"), row.get("label_col"), row.get("value_col")
                    if vc and rn and row.get("value") not in (None, ""):
                        ef[f"{vc}{rn}"] = row.get("value")
                    if lc and rn and row.get("label") not in (None, ""):
                        ef[f"{lc}{rn}"] = row.get("label")
            if ef:
                d0["extracted_fields"] = ef
                print(f"[EXTRACTOR] {file_path.name}: flattened layout_sections "
                      f"-> extracted_fields ({len(ef)})", flush=True)

        # STEPS 6+7 — VALIDATION + RESULT ASSEMBLY (reuses proven pipeline)
        elapsed = (time.time() - start) * 1000
        result = _process_vision_result(
            d0, template_data, file_path.name, doc_type,
            elapsed, extraction, doc_text, "", seg_idx)
        results.append(result)

    return results if results else [_fail(file_path.name, "no documents extracted")]
