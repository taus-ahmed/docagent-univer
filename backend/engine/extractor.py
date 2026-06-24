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

import re
import time
from pathlib import Path


def _norm_section(s) -> str:
    """Fuzzy section-key normalisation: lowercase, strip non-alphanumerics."""
    return re.sub(r'[^a-z0-9]+', '', str(s or "").lower())


def _unwrap_doc(parsed):
    """Return the per-document dict, unwrapping a Gemini documents[] wrapper."""
    if (isinstance(parsed, dict) and isinstance(parsed.get("documents"), list)
            and parsed["documents"] and isinstance(parsed["documents"][0], dict)):
        return parsed["documents"][0]
    return parsed if isinstance(parsed, dict) else {}


def _build_narrow_section_prompt(group, doc_type, fixed_cells, doc_text):
    """
    FIX 3 — generic per-section "extract & place" prompt. Describes ONE section,
    one column pair, and one row range only. fixed_cells = [{'ref','label'}] are the
    totals whose value cell falls in this section's row range. Returns (prompt, key).
    """
    lcl = (group.get("label_col_letter") or "").upper()
    vcl = (group.get("value_col_letter") or "").upper()
    start = int(group.get("start_row", 0)) + 1     # 1-based spreadsheet rows
    end   = int(group.get("end_row", 0)) + 1
    sec   = group.get("section_label", "section")
    key   = _norm_section(sec) or "section"
    if fixed_cells:
        fixed_block = ("\nTotal cell(s) for this section — return these in "
                       "extracted_fields (value only, by cell reference):\n"
                       + "\n".join(f"  {fc['ref']} = {fc['label']}" for fc in fixed_cells)
                       + "\n")
        ef_example = ", ".join(f'"{fc["ref"]}": "<amount>"' for fc in fixed_cells[:3])
    else:
        fixed_block, ef_example = "", ""
    prompt = (
        "Extract content for ONE section of this document.\n\n"
        f"Section name: {sec}\n"
        f"Label column: {lcl}\n"
        f"Value column: {vcl}\n"
        f"Template rows: {start} to {end}\n\n"
        f"Find the {sec} portion of the document.\n"
        "Extract EVERY line item from this section ONLY.\n"
        "Place each item using ONLY these columns:\n"
        f"  labels -> column {lcl}\n"
        f"  values -> column {vcl}\n"
        f"{fixed_block}\n"
        "Return ONLY this JSON — nothing else:\n"
        "{\n"
        '  "layout_sections": {\n'
        f'    "{key}": {{\n'
        '      "rows": [\n'
        f'        {{"label_col": "{lcl}", "value_col": "{vcl}", "row": {start}, '
        '"label": "<item name>", "value": "<amount>"}\n'
        "      ]\n"
        "    }\n"
        "  },\n"
        f'  "extracted_fields": {{{ef_example}}}\n'
        "}\n\n"
        "CONSTRAINTS:\n"
        f"- Only column {lcl} for labels\n"
        f"- Only column {vcl} for values\n"
        f"- Only rows {start} to {end}\n"
        "- Do NOT include section totals in the rows (return them in extracted_fields)\n"
        "- Do NOT include any other sections or columns\n\n"
        "=== DOCUMENT TEXT ===\n"
        f"{doc_text}\n"
    )
    return prompt, key


def _extract_layout_per_section(orchestrator, column_groups, binding_map, doc_type,
                                doc_text, page_imgs, system_instruction, file_path):
    """
    FIX 3 — one Gemini call per section group (each gets ALL page images). Merges the
    per-section responses into a single layout result. Returns (combined_doc,
    extraction) or (None, None) if nothing was extracted (caller falls back to the
    single-call path).
    """
    from app.api.routes.extract import _cell_ref

    fixed_all = []
    for k, b in (binding_map or {}).items():
        if isinstance(b, dict) and b.get("role") == "value_target" and b.get("label"):
            try:
                r, c = map(int, str(k).split(","))
            except (ValueError, AttributeError):
                continue
            fixed_all.append({"ref": _cell_ref(r, c), "label": b["label"], "row": r, "col": c})

    combined_ls, combined_ef, last_ext = {}, {}, None
    print(f"[EXTRACTOR] {file_path.name}: layout per-section mode — "
          f"{len(column_groups)} section call(s)", flush=True)

    for group in column_groups:
        g_fixed = [fc for fc in fixed_all
                   if fc["col"] == group.get("value_col")
                   and int(group.get("start_row", 0)) <= fc["row"]
                   <= int(group.get("end_row", 0)) + 2]
        nprompt, _nkey = _build_narrow_section_prompt(group, doc_type, g_fixed, doc_text)

        sresp = None
        for attempt in range(3):
            try:
                sresp = (orchestrator.llm.extract(
                            image_b64=page_imgs, prompt=nprompt,
                            system_instruction=system_instruction)
                         if page_imgs else
                         orchestrator.llm.extract(
                            text=doc_text, prompt=nprompt,
                            system_instruction=system_instruction))
                if sresp and sresp.success and sresp.parsed_json:
                    break
            except Exception as e:
                print(f"[EXTRACTOR] section '{group.get('section_label')}' error: {e}", flush=True)
            if attempt < 2:
                time.sleep(2)

        if not sresp or not sresp.success or not sresp.parsed_json:
            print(f"[EXTRACTOR] {file_path.name}: section "
                  f"'{group.get('section_label')}' call failed — skipping", flush=True)
            continue
        last_ext = sresp
        sd0 = _unwrap_doc(sresp.parsed_json)
        sls = sd0.get("layout_sections", {})
        n_rows = 0
        if isinstance(sls, dict) and sls:
            first = next(iter(sls))
            block = sls.get(first) or {}
            combined_ls[group.get("section_label", first)] = block
            n_rows = len(block.get("rows", []) if isinstance(block, dict) else [])
        sef = sd0.get("extracted_fields", {})
        if isinstance(sef, dict):
            combined_ef.update(sef)
        print(f"[EXTRACTOR] {file_path.name}: section "
              f"'{group.get('section_label')}' -> {n_rows} rows", flush=True)

    if not combined_ls and not combined_ef:
        return None, None

    final = {
        "layout_sections":    combined_ls,
        "extracted_fields":   combined_ef,
        "document_type":      doc_type,
        "overall_confidence": "high",
    }
    return final, last_ext


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
        # FIX 1: send ALL page images for this segment so multi-page documents
        # (balance sheet / payslip page 2, etc.) are fully visible to Gemini.
        page_imgs = [page_images[p] for p in pages if 0 <= p < len(page_images)]
        if not page_imgs and page_images:
            page_imgs = [page_images[0]]

        # STEP 4 — PROMPT (auto layout vs field via binding_map)
        system_instruction, prompt = _build_vision_prompt(template_data, doc_text)

        # FIX 3 — layout mode with 2+ section groups: one Gemini call per section
        # (each gets all page images) to stop the model losing column assignments
        # for later sections. Falls back to the single-call path if it yields nothing.
        _cg = (binding_map or {}).get("_meta", {}).get("column_groups", []) if is_layout else []
        if is_layout and len(_cg) >= 2:
            _ps_d0, _ps_ext = _extract_layout_per_section(
                orchestrator, _cg, binding_map, doc_type, doc_text,
                page_imgs, system_instruction, file_path)
            if _ps_d0 is not None:
                elapsed = (time.time() - start) * 1000
                results.append(_process_vision_result(
                    _ps_d0, template_data, file_path.name, doc_type,
                    elapsed, _ps_ext, doc_text, "", seg_idx))
                continue   # skip the single-call path for this segment

        # STEP 5 — GEMINI CALL (vision-first, 3 retries w/ 2s backoff on 503/err)
        extraction, last_err = None, ""
        for attempt in range(3):
            try:
                if page_imgs:
                    extraction = orchestrator.llm.extract(
                        image_b64=page_imgs, prompt=prompt,
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
                            image_b64=page_imgs, prompt=enforce + prompt,
                            system_instruction=system_instruction)
                          if page_imgs else
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

        # STEP 5c — SECTION COMPLETENESS (layout mode). Compare the sections Gemini
        # returned against the sections described in the prompt (fuzzy match). If any
        # are missing: retry once with an INCOMPLETE-RESPONSE directive, then
        # reconstruct any still-missing section from extracted_fields.
        if is_layout and isinstance(d0, dict):
            expected = [g.get("section_label", "")
                        for g in (binding_map or {}).get("_meta", {}).get("column_groups", [])]

            def _missing(layout):
                got = {_norm_section(k) for k in (layout or {}).keys()}
                return [s for s in expected if s and _norm_section(s) not in got]

            miss = _missing(d0.get("layout_sections", {}))
            if miss:
                print(f"[EXTRACTOR] {file_path.name}: incomplete response — missing "
                      f"sections: {miss} — retrying", flush=True)
                comp = ("INCOMPLETE RESPONSE DETECTED. Your previous response was missing "
                        f"these required sections: {', '.join(miss)}. You MUST include ALL "
                        "sections. Each section must have at least one row of extracted "
                        "line items.\n\n")
                try:
                    re2 = (orchestrator.llm.extract(
                                image_b64=page_imgs, prompt=comp + prompt,
                                system_instruction=system_instruction)
                           if page_imgs else
                           orchestrator.llm.extract(
                                text=doc_text, prompt=comp + prompt,
                                system_instruction=system_instruction))
                    if re2 and re2.success and re2.parsed_json:
                        rd2 = _unwrap_doc(re2.parsed_json)
                        if (rd2.get("layout_sections")
                                and len(_missing(rd2["layout_sections"])) < len(miss)):
                            raw, extraction, d0 = re2.parsed_json, re2, rd2
                            print(f"[EXTRACTOR] {file_path.name}: retry recovered sections", flush=True)
                except Exception as e:
                    print(f"[EXTRACTOR] completeness retry error: {e}", flush=True)

                still = _missing(d0.get("layout_sections", {}))
                if still and d0.get("extracted_fields"):
                    conv = _convert_extracted_fields_to_layout(
                        d0.get("extracted_fields", {}), binding_map or {})
                    ls = d0.setdefault("layout_sections", {})
                    for s in still:
                        for ck, cv in conv.items():
                            if _norm_section(ck) == _norm_section(s) and cv.get("rows"):
                                ls[ck] = cv
                                print(f"[EXTRACTOR] {file_path.name}: reconstructed section "
                                      f"'{s}' from extracted_fields", flush=True)
                                break

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
