"""
DocAgent — Three-Layer Extraction Engine (v4)
=============================================

A clean rewrite of the extraction engine, behind the USE_NEW_EXTRACTOR flag.
Everything downstream (writers, routes, models, save path) is UNCHANGED — this
module only produces `DocumentExtractionResult` objects whose `.extracted_data`
matches the existing contract.

THREE LAYERS (the complete pipeline):

  LAYER 1 — DOCUMENT INTELLIGENCE  (_understand_document)
      ONE Gemini call per file. Inventories the whole file: how many documents,
      their types, page ranges, identifiers, and each section (heading, page,
      item count, table vs kv).

  LAYER 2 — TARGETED EXTRACTION    (_extract_section / _run_all_extractions)
      ONE small, focused Gemini call per section. Extracts that section only,
      using the pages it lives on and (in template mode) the matched column group.

  LAYER 3 — VALIDATION             (_validate_extraction)
      NO Gemini calls. Text-presence confidence, financial cross-validation,
      completeness check, scanned-document handling.

Heavy primitives are imported lazily from app.api.routes.extract to avoid
duplication and import cycles. The public entry point keeps the legacy signature
`run_extraction(orchestrator, file_path, template_data, selected_pages=None)`.
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


def _unwrap(parsed):
    """Return the per-document dict if Gemini wrapped it in documents[]."""
    if (isinstance(parsed, dict) and isinstance(parsed.get("documents"), list)
            and parsed["documents"] and isinstance(parsed["documents"][0], dict)):
        return parsed["documents"][0]
    return parsed if isinstance(parsed, dict) else {}


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


def _llm_json(orchestrator, prompt, system, images=None, text="", model=None):
    """
    One Gemini call (vision-first, all images), returning (parsed_dict_or_None,
    response_or_None). 3 attempts with 2s backoff; text fallback when vision fails.
    `model` pins the Gemini tier (e.g. "gemini-2.5-flash" for accuracy-critical calls).
    """
    resp = None
    for attempt in range(3):
        try:
            if images:
                resp = orchestrator.llm.extract(image_b64=images, prompt=prompt,
                                                system_instruction=system, model=model)
                if (not getattr(resp, "success", False)) and text:
                    resp = orchestrator.llm.extract(text=text, prompt=prompt,
                                                    system_instruction=system, model=model)
            elif text:
                resp = orchestrator.llm.extract(text=text, prompt=prompt,
                                                system_instruction=system, model=model)
            else:
                return None, None
            if resp and getattr(resp, "success", False) and getattr(resp, "parsed_json", None):
                return resp.parsed_json, resp
        except Exception as e:
            _log("LLM", f"error attempt {attempt+1}: {e}")
        if attempt < 2:
            time.sleep(2)
    return None, resp


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 1 — DOCUMENT INTELLIGENCE
# ══════════════════════════════════════════════════════════════════════════════

_L1_SYSTEM = (
    "You are an expert document analyst with deep knowledge of business documents. "
    "Your task is to create a complete inventory of a document before extraction begins."
)


def _understand_document(orchestrator, page_images, doc_text, binding_map, file_type):
    """LAYER 1 — ONE Gemini call inventorying the whole file. Returns (document_map, response)."""
    text_block = ""
    if doc_text and doc_text.strip():
        text_block = ("\n=== EXTRACTED TEXT (for reference) ===\n"
                      + doc_text[:12000] + "\n=== END TEXT ===\n")

    prompt = (
        "Analyze this entire document carefully across all pages.\n"
        + text_block +
        "\nProvide a complete document inventory:\n\n"
        "1. How many separate documents are in this file? (A single invoice = 1 "
        "document. 40 invoices = 40 documents. A 3-page balance sheet = 1 document.)\n\n"
        "2. For each document: its 0-based index, document type "
        "(invoice/balance_sheet/payslip/contract/receipt/other — use 'other' if "
        "unsure), 0-indexed page range, a unique identifier if visible, and EVERY "
        "section with its exact heading text, 0-indexed start page, approximate "
        "line-item count, and whether it is a 'table' (repeating rows) or "
        "'kv_pairs'.\n\n"
        "Each section must represent ONE focused group of related content — "
        "typically 3-15 items. If content would form a section larger than 20 "
        "items, split it into logical subsections. Sections must be distinct and "
        "non-overlapping.\n\n"
        "Return ONLY this JSON:\n"
        "{\n"
        '  "file_type": "digital_pdf" | "scanned_pdf" | "image",\n'
        '  "total_documents": N,\n'
        '  "documents": [\n'
        '    {"doc_index": 0, "doc_type": "invoice", "pages": [0,1],\n'
        '     "identifier": "INV-2024-001",\n'
        '     "sections": [\n'
        '       {"heading": "exact heading", "page": 0, "item_count": 5,\n'
        '        "structure": "table" | "kv_pairs" | "mixed"}\n'
        "     ]}\n"
        "  ]\n}"
    )
    parsed, resp = _llm_json(orchestrator, prompt, _L1_SYSTEM,
                             images=page_images, text=doc_text)
    dm = parsed if (isinstance(parsed, dict) and parsed.get("documents")) else None
    if not dm:
        dm = _fallback_document_map(binding_map, len(page_images) or 1, file_type)
        _log("L1", "Gemini inventory unavailable — using fallback document map")
    dm.setdefault("file_type", file_type)
    docs = dm.get("documents", [])
    total_sections = sum(len(d.get("sections", [])) for d in docs)
    _log("L1", f"document map: {len(docs)} documents, {total_sections} total sections")
    for i, d in enumerate(docs):
        _log("L1", f"doc {i}: {d.get('doc_type','other')}, pages {d.get('pages',[0])}, "
                   f"{len(d.get('sections',[]))} sections")
    return dm, resp


def _fallback_document_map(binding_map, n_pages, file_type):
    """Single-document map; sections from the template's column groups when present."""
    sections = []
    cgs = ((binding_map or {}).get("_meta", {}).get("column_groups", [])
           if binding_map else [])
    for g in cgs:
        sections.append({
            "heading": g.get("section_label", ""),
            "page": 0,
            "item_count": max(1, int(g.get("end_row", 0)) - int(g.get("start_row", 0)) + 1),
            "structure": "table",
        })
    if not sections:
        sections = [{"heading": "Document", "page": 0, "item_count": 10, "structure": "mixed"}]
    return {
        "file_type": file_type,
        "total_documents": 1,
        "documents": [{"doc_index": 0, "doc_type": "other",
                       "pages": list(range(n_pages)), "identifier": "",
                       "sections": sections}],
    }


# ── template matching (exact → fuzzy) ─────────────────────────────────────────

def _match_groups_to_sections(column_groups, sections):
    """Map each column group -> best matching document section (or None). Exact then fuzzy."""
    matches = {}
    used = set()
    norm_secs = [(i, _norm(s.get("heading"))) for i, s in enumerate(sections)]
    for gi, g in enumerate(column_groups):
        gn = _norm(g.get("section_label"))
        found = None
        for si, sn in norm_secs:                       # 1. exact
            if si not in used and sn and sn == gn:
                found = si
                break
        if found is None:                              # 2. fuzzy (substring either way)
            for si, sn in norm_secs:
                if si not in used and gn and (gn in sn or sn in gn):
                    found = si
                    break
        matches[gi] = sections[found] if found is not None else None
        if found is not None:
            used.add(found)
    return matches


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 2 — TARGETED EXTRACTION
# ══════════════════════════════════════════════════════════════════════════════

def _build_section_prompt(section_info, template_group, doc_type, total_cell=None):
    """Build the per-section Layer-2 prompt (template mode or no-template mode)."""
    heading = section_info.get("heading", "section")
    item_count = section_info.get("item_count", 0)
    structure = section_info.get("structure", "table")
    key = _norm(heading) or "section"

    if template_group:
        lcl = (template_group.get("label_col_letter") or "A").upper()
        vcl = (template_group.get("value_col_letter") or "B").upper()
        start = int(template_group.get("start_row", 0)) + 1
        end = int(template_group.get("end_row", 0)) + 1
        struct_rule = (
            "Extract each line item as a separate row. Do NOT combine items. Do NOT "
            "skip items. Number rows from 1 sequentially.\n"
            if structure != "kv_pairs" else
            "Extract each key-value pair. One pair per row.\n"
        )
        total_block = ""
        if total_cell:
            total_block = (f"\nSection total (if present): place it in extracted_fields "
                           f"as \"{total_cell}\": value. Do NOT include the total in rows.\n")
            ef_example = f'"{total_cell}": "total value"'
        else:
            ef_example = ""
        prompt = (
            f"Extract the '{heading}' section from this document page.\n\n"
            f"This section contains approximately {item_count} line items.\n\n"
            f"{struct_rule}"
            f"\nTemplate placement:\n"
            f"- Item labels -> column {lcl}\n"
            f"- Item values -> column {vcl}\n"
            f"- Rows: {start} to {end} (expand beyond {end} if more items than template rows)\n"
            f"{total_block}\n"
            "Return ONLY:\n{\n"
            f'  "layout_sections": {{ "{key}": {{ "rows": [\n'
            f'    {{"label_col": "{lcl}", "value_col": "{vcl}", "row": 1, '
            '"label": "exact item name", "value": "exact value"}\n'
            "  ] } },\n"
            f'  "extracted_fields": {{{ef_example}}}\n}}\n\n'
            "RULES:\n"
            f"- label_col MUST always be \"{lcl}\"\n"
            f"- value_col MUST always be \"{vcl}\"\n"
            "- Row numbers MUST be sequential starting from 1\n"
            "- NEVER leave label_col or value_col empty or null\n"
            "- Extract EVERY item — do not stop early\n"
            "- Values must be exactly as they appear in the document\n"
            "- NUMBERS: return the COMPLETE numeric amount including digits "
            "(e.g. \"$320.00\" -> \"320.00\"). NEVER return only a currency symbol "
            "($, £, €, etc.) as a value — a lone currency symbol means the value was "
            "not found, return \"\" instead."
        )
    else:
        prompt = (
            f"Extract ALL content from the '{heading}' section of this document.\n\n"
            "Return each item as a row with: label (the field name or item "
            "description) and value (the corresponding value).\n\n"
            "Return ONLY:\n{\n"
            f'  "layout_sections": {{ "{key}": {{ "rows": [\n'
            '    {"label_col": "A", "value_col": "B", "row": 1, '
            '"label": "field name", "value": "field value"}\n'
            "  ] } }\n}\n\n"
            "NUMBERS: return the COMPLETE numeric amount including digits "
            "(e.g. \"$320.00\" -> \"320.00\"). NEVER return only a currency symbol "
            "($, £, €, etc.) as a value — a lone currency symbol means the value was "
            "not found, return \"\" instead."
        )
    return prompt, key


def _extract_section(orchestrator, section_info, sec_images, sec_text,
                     template_group, doc_type, system_instruction, total_cell=None):
    """LAYER 2 — one focused Gemini call for a single section. Returns (rows, extracted_fields, response)."""
    prompt, key = _build_section_prompt(section_info, template_group, doc_type, total_cell)
    parsed, resp = _llm_json(orchestrator, prompt, system_instruction,
                             images=sec_images, text=sec_text)
    d0 = _unwrap(parsed) if parsed else {}
    ls = d0.get("layout_sections", {}) if isinstance(d0, dict) else {}
    rows = []
    if isinstance(ls, dict) and ls:
        first = next(iter(ls))
        block = ls.get(first) or {}
        rows = block.get("rows", []) if isinstance(block, dict) else []
    ef = d0.get("extracted_fields", {}) if isinstance(d0, dict) else {}
    # Normalize columns + sequential row numbers; enforce template columns.
    out_rows = []
    lcl = (template_group.get("label_col_letter") if template_group else None) or "A"
    vcl = (template_group.get("value_col_letter") if template_group else None) or "B"
    for i, r in enumerate(rows):
        if not isinstance(r, dict):
            continue
        out_rows.append({
            "label_col": (str(r.get("label_col") or lcl).upper() if not template_group else lcl).upper(),
            "value_col": (str(r.get("value_col") or vcl).upper() if not template_group else vcl).upper(),
            "row": i + 1,
            "label": r.get("label", ""),
            "value": r.get("value", ""),
        })
    return out_rows, (ef if isinstance(ef, dict) else {}), resp


def _run_all_extractions(orchestrator, document_map, page_images, doc_text_pages,
                         binding_map, default_doc_type):
    """LAYER 2 driver — extract every section of every document. Returns (per_doc, responses)."""
    from app.api.routes.extract import _get_system_prompt, _cell_ref

    cgs = (binding_map or {}).get("_meta", {}).get("column_groups", []) if binding_map else []
    # totals (value_target) cells from the binding map, with row/col
    fixed_cells = []
    for k, b in (binding_map or {}).items():
        if isinstance(b, dict) and b.get("role") == "value_target" and b.get("label"):
            try:
                r, c = map(int, str(k).split(","))
            except (ValueError, AttributeError):
                continue
            fixed_cells.append({"ref": _cell_ref(r, c), "row": r, "col": c})

    per_doc, responses = {}, []
    for d in document_map.get("documents", []):
        di = d.get("doc_index", 0)
        doc_type = d.get("doc_type") or default_doc_type or "other"
        system = _get_system_prompt(doc_type)
        sections = d.get("sections", []) or []
        matches = _match_groups_to_sections(cgs, sections) if cgs else {}
        # invert: section index -> column group
        sec_to_group = {}
        for gi, sec in matches.items():
            if sec is not None:
                sec_to_group[id(sec)] = cgs[gi]

        extracted = {"layout_sections": {}, "extracted_fields": {},
                     "doc_type": doc_type, "identifier": d.get("identifier", ""),
                     "doc_index": di}
        for sec in sections:
            grp = sec_to_group.get(id(sec))
            pg = int(sec.get("page", 0) or 0)
            sec_imgs = [page_images[pg]] if (page_images and 0 <= pg < len(page_images)) else (page_images or None)
            sec_text = doc_text_pages[pg] if (doc_text_pages and 0 <= pg < len(doc_text_pages)) else ""
            total_cell = None
            if grp:
                cand = [fc for fc in fixed_cells
                        if fc["col"] == grp.get("value_col")
                        and int(grp.get("start_row", 0)) <= fc["row"] <= int(grp.get("end_row", 0)) + 2]
                total_cell = cand[0]["ref"] if cand else None
            _log("L2", f"extracting: doc {di} section '{sec.get('heading')}' page {pg}")
            rows, ef, resp = _extract_section(orchestrator, sec, sec_imgs, sec_text,
                                              grp, doc_type, system, total_cell)
            if resp is not None:
                responses.append(resp)
            label_for = (grp.get("section_label") if grp else sec.get("heading")) or sec.get("heading", "section")
            extracted["layout_sections"][label_for] = {"rows": rows}
            extracted["extracted_fields"].update(ef or {})
            _log("L2", f"section '{sec.get('heading')}': {len(rows)} rows extracted")

        # Template groups that matched no document section -> empty (logged)
        if cgs:
            matched_groups = {gi for gi, sec in matches.items() if sec is not None}
            for gi, g in enumerate(cgs):
                if gi not in matched_groups:
                    lbl = g.get("section_label", f"group_{gi}")
                    if lbl not in extracted["layout_sections"]:
                        _log("L2", f"catch-all: template section '{lbl}' has no document match — empty")
                        extracted["layout_sections"][lbl] = {"rows": []}

        per_doc[di] = extracted
    return per_doc, responses


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 3 — VALIDATION  (no Gemini)
# ══════════════════════════════════════════════════════════════════════════════

_FINANCIAL_TYPES = {"balance_sheet", "income_statement", "profit_and_loss", "audit_report",
                    "payslip", "bank_statement", "invoice", "purchase_order", "receipt"}


def _validate_extraction(extracted, doc_text, doc_type, file_type, document_map_doc):
    """LAYER 3 — confidence per value + cross-checks. Returns (confidence_map, flagged, notes,
    overall_confidence, needs_review)."""
    text_norm = _norm(doc_text)
    text_digits = _digits(doc_text)
    conf_map, flagged, notes = {}, [], []

    def value_conf(value):
        nv = _norm(value)
        if not nv:
            return "high"
        if nv in text_norm:
            return "high"
        d = _digits(value)
        if d and d in text_digits:
            return "medium"
        return "low"

    # Step 1 — text-presence confidence for every layout row + fixed field.
    ls = extracted.get("layout_sections", {})
    for sec_label, block in (ls.items() if isinstance(ls, dict) else []):
        for row in (block.get("rows", []) if isinstance(block, dict) else []):
            if not isinstance(row, dict):
                continue
            ref = f"{row.get('value_col', '')}{row.get('row', '')}"
            c = value_conf(row.get("value"))
            conf_map[ref or f"{sec_label}:{row.get('row')}"] = c
            if c == "low":
                flagged.append({"ref": ref, "value": str(row.get("value", "")),
                                "issue": "value not found in document text"})
    for ref, val in (extracted.get("extracted_fields", {}) or {}).items():
        v = val.get("value", "") if isinstance(val, dict) else val
        c = value_conf(v)
        conf_map[ref] = c
        if c == "low":
            flagged.append({"ref": ref, "value": str(v), "issue": "total not found in text"})

    # Step 2 — financial cross-validation (sum of items vs section total).
    if (doc_type or "").lower() in _FINANCIAL_TYPES:
        for sec_label, block in (ls.items() if isinstance(ls, dict) else []):
            rows = block.get("rows", []) if isinstance(block, dict) else []
            s = sum(v for v in (_num(r.get("value")) for r in rows if isinstance(r, dict)) if v is not None)
            # nearest total: an extracted_field whose ref column matches a row's value_col
            vcols = {str(r.get("value_col", "")).upper() for r in rows if isinstance(r, dict)}
            for ref, val in (extracted.get("extracted_fields", {}) or {}).items():
                m = re.match(r'^([A-Za-z]+)\d+$', str(ref))
                if not m or m.group(1).upper() not in vcols:
                    continue
                tot = _num(val.get("value") if isinstance(val, dict) else val)
                if tot and abs(s - tot) / abs(tot) > 0.01:
                    notes.append(f"Section '{sec_label}' total mismatch — items sum to "
                                 f"{s:g}, total shows {tot:g}")
                    flagged.append({"ref": ref, "value": str(tot), "issue": "section total mismatch"})

    # Step 3 — completeness (extracted vs expected item count from Layer 1).
    sec_expected = {}
    for sec in (document_map_doc.get("sections", []) if document_map_doc else []):
        sec_expected[_norm(sec.get("heading"))] = int(sec.get("item_count", 0) or 0)
    for sec_label, block in (ls.items() if isinstance(ls, dict) else []):
        exp = sec_expected.get(_norm(sec_label), 0)
        act = len(block.get("rows", []) if isinstance(block, dict) else [])
        if exp and act < exp * 0.8:
            notes.append(f"Section '{sec_label}': expected ~{exp} items, extracted {act}")
            flagged.append({"ref": sec_label, "value": str(act), "issue": "incomplete section"})

    # Step 4 — scanned / image: floor at medium, force review.
    scanned = file_type in ("scanned_pdf", "image")
    if scanned:
        for k in conf_map:
            if conf_map[k] == "high":
                conf_map[k] = "medium"
        notes.append("Scanned document — manual verification recommended")

    confs = list(conf_map.values())
    if scanned:
        overall = "medium"
    elif "low" in confs:
        overall = "low"
    elif "medium" in confs:
        overall = "medium"
    else:
        overall = "high"
    needs_review = bool(flagged) or scanned or overall == "low"

    n_high = confs.count("high"); n_med = confs.count("medium"); n_low = confs.count("low")
    _log("L3", f"validation: {n_high} high, {n_med} medium, {n_low} low confidence")
    if needs_review:
        _log("L3", f"needs_review: {notes[0] if notes else ('low-confidence values' if 'low' in confs else 'scanned')}")
    return conf_map, flagged, notes, overall, needs_review


# ══════════════════════════════════════════════════════════════════════════════
# RESULT ASSEMBLY + ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def _assemble_result(filename, doc_index, doc_type, identifier, layout_sections,
                     extracted_fields, binding_column_groups, primary_mode,
                     document_map_doc, conf_map, flagged, notes, overall, needs_review,
                     responses, elapsed):
    """Build a DocumentExtractionResult with downstream-compatible extracted_data."""
    from orchestrator import DocumentExtractionResult

    # label-keyed extracted_data (for the flat / no-template writer + insights)
    kv = {}
    for block in (layout_sections.values() if isinstance(layout_sections, dict) else []):
        for row in (block.get("rows", []) if isinstance(block, dict) else []):
            if isinstance(row, dict) and row.get("label"):
                ref = f"{row.get('value_col','')}{row.get('row','')}"
                kv[str(row["label"])] = {"value": row.get("value", ""),
                                          "confidence": conf_map.get(ref, "high"), "ref": ref}
    for ref, val in (extracted_fields or {}).items():
        v = val.get("value", "") if isinstance(val, dict) else val
        kv[ref] = {"value": v, "confidence": conf_map.get(ref, "high"), "ref": ref}

    r = DocumentExtractionResult(filename=filename)
    r.document_type = doc_type
    r.success = True
    r.processing_time_ms = elapsed
    r.extracted_data = {
        "document_type": doc_type,
        "overall_confidence": overall,
        "extraction_method": "v4_three_layer",
        "identifier": identifier,
        "doc_index": doc_index,
        "layout_sections": layout_sections,
        "extracted_fields": {k: (v.get("value", "") if isinstance(v, dict) else v)
                             for k, v in (extracted_fields or {}).items()},
        "binding_column_groups": binding_column_groups,
        "extracted_data": kv,
        "table_rows": [],
        "validation": {
            "flagged_count": len(flagged),
            "flagged_fields": flagged,
            "confidence_map": conf_map,
        },
        "validation_notes": notes,
        "needs_review": needs_review,
        "template_regions": {
            "primary_mode": primary_mode,
            "binding_column_groups": binding_column_groups,
            "document_map": document_map_doc,
        },
        "raw_llm_responses": [getattr(x, "raw_text", "") for x in responses if x is not None],
    }
    # representative extraction_response for the save path (model/tokens/raw)
    last = next((x for x in reversed(responses) if x is not None), None)
    if last is not None:
        try:
            import json as _json
            last.raw_text = _json.dumps({"raw_llm_responses":
                                         [getattr(x, "raw_text", "") for x in responses if x is not None]},
                                        default=str)[:200000]
            last.tokens_used = sum(int(getattr(x, "tokens_used", 0) or 0) for x in responses if x is not None)
        except Exception:
            pass
    r.extraction_response = last
    _log("RESULT", f"doc {doc_index}: {len(kv)} fields, "
                   f"{sum(len(b.get('rows',[])) for b in layout_sections.values() if isinstance(b,dict))} rows, "
                   f"{overall}")
    return r


def _run_field_extraction(orchestrator, file_path, template_data, binding_map,
                          page_images, doc_text, doc_text_pages, file_type,
                          default_doc_type, start):
    """
    LABELED template (has_table_data == False). The user told us the exact fields and
    where to put them — one template-guided Gemini call → extracted_fields. NO Layer
    1/2/3. Routes to the form/KV writer at export time.
    """
    from app.api.routes.extract import _build_vision_prompt, _process_vision_result, _fail
    _log("FIELD", f"{file_path.name}: labeled template — single template-guided call")
    td = {**template_data, "binding_map": binding_map} if (template_data and binding_map) else (template_data or {})
    # force_field_mode=True: honour the [ROUTE] decision — _build_vision_prompt must
    # NOT switch to the layout prompt just because the binding map has table_data
    # (mixed templates do). td carries the full binding_map so the field prompt
    # includes both the KV cells and the embedded table.
    system, prompt = _build_vision_prompt(td, doc_text, force_field_mode=True)
    parsed, resp = _llm_json(orchestrator, prompt, system, images=page_images, text=doc_text)
    if not parsed:
        return [_fail(file_path.name, "field extraction failed")]
    d0 = _unwrap(parsed)
    elapsed = (time.time() - start) * 1000
    return [_process_vision_result(d0, td, file_path.name, default_doc_type,
                                   elapsed, resp, doc_text, "", 0)]


# CBM extraction is a single focused call where accuracy matters more than cost —
# pin it to the stronger gemini-2.5-flash tier (not the default -lite, which has
# been observed returning bare currency symbols instead of full amounts).
_CBM_MODEL = "gemini-2.5-flash"
_BARE_CURRENCY = {"$", "£", "€", "₹", "¥"}


def _val_str(x):
    """Stringify an extracted field value (handles {"value": ...} dicts), trimmed."""
    return str((x.get("value", "") if isinstance(x, dict) else x) or "").strip()


def _retry_bare_currency(orchestrator, d0, cell_binding_map, page_images, doc_text, system):
    """
    FIX 2 — gemini sometimes returns ONLY a currency symbol (e.g. "$") with no digits
    for a currency cell. Detect those fields and re-ask Gemini for JUST those cells
    (same page images, stronger model), then merge the recovered amounts back into
    d0["extracted_fields"]. Generic — works for any field / document type. Mutates d0
    in place; returns the number of fields fixed.
    """
    ef = d0.get("extracted_fields") if isinstance(d0, dict) else None
    if not isinstance(ef, dict) or not ef:
        return 0
    bare = {ref: info for ref, info in ef.items() if _val_str(info) in _BARE_CURRENCY}
    if not bare:
        return 0

    _log("CBM", f"{len(bare)} bare currency symbol(s) detected — retrying those fields")
    extract_cells = ((cell_binding_map.get("extract_cells") or {})
                     if isinstance(cell_binding_map, dict) else {})
    field_lines = []
    for ref in bare:
        info = extract_cells.get(ref) or {}
        label = (info.get("label") if isinstance(info, dict) else "") or ref
        field_lines.append(f"  {ref} = {label}")
    retry_prompt = (
        "Some fields were previously returned with ONLY a currency symbol and no "
        "digits. Re-read the document and return the COMPLETE numeric amount for each "
        "of these cells:\n"
        + "\n".join(field_lines) + "\n\n"
        "Return ONLY JSON: {\"extracted_fields\": {\"<cell_ref>\": \"<full amount>\"}}\n"
        "Each value must be the full number (e.g. 320.00, 12179.21) — NEVER just a "
        "currency symbol. If a value genuinely does not appear, return \"\"."
    )
    parsed, _ = _llm_json(orchestrator, retry_prompt, system,
                          images=page_images, text=doc_text, model=_CBM_MODEL)
    r0 = _unwrap(parsed) if parsed else {}
    rfields = r0.get("extracted_fields") if isinstance(r0, dict) else {}
    if not isinstance(rfields, dict):
        return 0
    fixed = 0
    for ref in bare:
        newv = _val_str(rfields.get(ref))
        if newv and newv not in _BARE_CURRENCY:
            ef[ref] = ({**ef[ref], "value": newv} if isinstance(ef[ref], dict) else newv)
            fixed += 1
    if fixed:
        _log("CBM", f"retry recovered {fixed}/{len(bare)} bare currency field(s)")
    return fixed


def _run_cbm_extraction(orchestrator, file_path, template_data, cell_binding_map,
                        binding_map, page_images, doc_text, doc_text_pages, file_type,
                        default_doc_type, start):
    """
    STORED cell_binding_map path (Gemini-based template understanding from save time).
    One template-guided Gemini call whose prompt is built directly from the stored
    map (exact extract cells + table definitions + static-cell exclusions). Returns
    extracted_fields + table_rows → _process_vision_result → form/mixed/table writer.
    No Layer 1/2/3, no re-analysis of the grid.
    """
    from app.api.routes.extract import (_build_cbm_prompt, _process_vision_result,
                                         _get_system_prompt, _fail)
    n_cells = len(cell_binding_map.get("extract_cells", {}) or {})
    n_tables = len(cell_binding_map.get("tables", []) or [])
    _log("FIELD", f"{file_path.name}: stored cell_binding_map "
                  f"({n_cells} extract cells, {n_tables} tables) — single guided call")
    system = _get_system_prompt(default_doc_type)
    prompt = _build_cbm_prompt(cell_binding_map, doc_text)
    # FIX 1 — pin CBM extraction to the stronger gemini-2.5-flash tier (accuracy).
    parsed, resp = _llm_json(orchestrator, prompt, system, images=page_images,
                             text=doc_text, model=_CBM_MODEL)
    if not parsed:
        return [_fail(file_path.name, "cell_binding_map extraction failed")]
    d0 = _unwrap(parsed)
    # FIX 2 — recover any field that came back as a bare currency symbol.
    _retry_bare_currency(orchestrator, d0, cell_binding_map, page_images, doc_text, system)
    td = ({**template_data, "binding_map": binding_map}
          if binding_map else dict(template_data or {}))
    elapsed = (time.time() - start) * 1000
    result = _process_vision_result(d0, td, file_path.name, default_doc_type,
                                    elapsed, resp, doc_text, "", 0)
    # The cbm path always returns extracted_fields + table_rows (field/mixed shape),
    # so EXPORT must use the form/mixed/table writer — never the layout writer. Force
    # template_type accordingly; compute_binding_map's verdict for the same grid may
    # say "structural" and wrongly pick the layout writer (which drops table_rows).
    try:
        if isinstance(getattr(result, "extracted_data", None), dict):
            tables = cell_binding_map.get("tables") or []
            result.extracted_data["template_type"] = "mixed" if tables else "labeled"
            result.extracted_data["layout_sections"] = {}
            # Persist the cbm table definitions + the RAW (column-name keyed) rows so
            # the export writer can place table data deterministically by
            # data_start_row + columns — independent of the fragile region analysis,
            # which can mis-classify the template and route it to the form writer
            # (which otherwise drops table_rows entirely).
            if tables:
                result.extracted_data["cbm_tables"] = tables
                raw_rows = d0.get("table_rows") if isinstance(d0, dict) else None
                if isinstance(raw_rows, list):
                    result.extracted_data["cbm_table_rows"] = raw_rows
    except Exception:
        pass
    return [result]


def _collapse_to_single_document(document_map, n_pages):
    """FIX 6 — merge a multi-document map into ONE document spanning all pages,
    preserving every section. Used for structural templates (a balance sheet / P&L
    is always one document even across pages)."""
    docs = document_map.get("documents", []) or []
    if len(docs) <= 1:
        return document_map
    sections = []
    for d in docs:
        sections.extend(d.get("sections", []) or [])
    merged = {
        "doc_index": 0,
        "doc_type": docs[0].get("doc_type", "other"),
        "pages": list(range(n_pages)) if n_pages else docs[0].get("pages", [0]),
        "identifier": docs[0].get("identifier", ""),
        "sections": sections,
    }
    document_map = dict(document_map)
    document_map["documents"] = [merged]
    document_map["total_documents"] = 1
    _log("L1", f"structural template — collapsed {len(docs)} documents into ONE "
               f"({len(sections)} sections, all {n_pages} pages)")
    return document_map


def _run_three_layer(orchestrator, file_path, template_data, binding_map, page_images,
                     doc_text, doc_text_pages, file_type, default_doc_type, start,
                     primary_mode, single_document=False):
    """Shared Layer 1 → Layer 2 → Layer 3 pipeline used by layout and unguided paths."""
    from app.api.routes.extract import _fail
    document_map, l1_resp = _understand_document(orchestrator, page_images, doc_text,
                                                 binding_map, file_type)
    file_type = document_map.get("file_type", file_type)
    # FIX 6 — structural templates are always ONE document; never split.
    if single_document:
        document_map = _collapse_to_single_document(document_map, len(page_images))
    per_doc, l2_responses = _run_all_extractions(orchestrator, document_map, page_images,
                                                 doc_text_pages, binding_map, default_doc_type)
    cgs = (binding_map or {}).get("_meta", {}).get("column_groups", []) if binding_map else []
    results = []
    docs = document_map.get("documents", [])
    for d in docs:
        di = d.get("doc_index", 0)
        ext = per_doc.get(di, {"layout_sections": {}, "extracted_fields": {}})
        doc_type = ext.get("doc_type", default_doc_type)
        conf_map, flagged, notes, overall, needs_review = _validate_extraction(
            ext, doc_text, doc_type, file_type, d)
        all_resps = ([l1_resp] if l1_resp is not None else []) + l2_responses
        seg_fn = (file_path.name if len(docs) == 1
                  else f"{file_path.stem}_doc{di+1}{file_path.suffix}")
        results.append(_assemble_result(
            seg_fn, di, doc_type, ext.get("identifier", ""),
            ext.get("layout_sections", {}), ext.get("extracted_fields", {}),
            cgs, primary_mode, d, conf_map, flagged, notes, overall, needs_review,
            all_resps, (time.time() - start) * 1000))
    return results or [_fail(file_path.name, "no documents extracted")]


def _run_layout_extraction(orchestrator, file_path, template_data, binding_map,
                           page_images, doc_text, doc_text_pages, file_type,
                           default_doc_type, start):
    """STRUCTURAL template: three-layer → layout_sections. Forced single-document
    (FIX 6): the whole PDF is ONE document, all page images passed to extraction."""
    _log("LAYOUT", f"{file_path.name}: structural template — three-layer (L1 -> L2 -> L3), "
                   f"single-document")
    return _run_three_layer(orchestrator, file_path, template_data, binding_map,
                            page_images, doc_text, doc_text_pages, file_type,
                            default_doc_type, start, primary_mode="layout",
                            single_document=True)


def _run_unguided_extraction(orchestrator, file_path, template_data, binding_map,
                             page_images, doc_text, doc_text_pages, file_type,
                             default_doc_type, start):
    """NO template: extract everything, two-column A/B output via the three layers."""
    _log("UNGUIDED", f"{file_path.name}: no template — full document, two-column A/B")
    return _run_three_layer(orchestrator, file_path, None, None,
                            page_images, doc_text, doc_text_pages, file_type,
                            default_doc_type, start, primary_mode="unguided")


def run_extraction(orchestrator, file_path, template_data, selected_pages=None):
    """
    Single entry point (legacy signature). Returns list[DocumentExtractionResult].

    THE ROUTING DECISION IS MADE AT THE START, by template type (driven by the
    binding map), so the right extraction runs from the beginning:

      binding_map is None (no template)        -> _run_unguided_extraction
      binding_map.has_table_data is True        -> _run_layout_extraction (3-layer)
      binding_map.has_table_data is False        -> _run_field_extraction (single call)
    """
    from app.api.routes.extract import compute_binding_map
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

    # ── Compute the binding map (only when a template was selected) ──
    binding_map = None
    if template_data:
        try:
            binding_map = compute_binding_map(template_data, template_data.get("layout", {}))
        except Exception as e:
            _log("ROUTE", f"binding map failed ({e})")

    ctx = dict(orchestrator=orchestrator, file_path=file_path, template_data=template_data,
               binding_map=binding_map, page_images=page_images, doc_text=doc_text,
               doc_text_pages=doc_text_pages, file_type=ftype,
               default_doc_type=default_doc_type, start=start)

    # ── ROUTING DECISION AT THE START — STRICT SEPARATION (the 3 paths never cross) ──
    # 1. no template            -> unguided
    # 2. template_type structural -> layout (NEVER cbm, even if a cbm exists)
    # 3. labeled/mixed + valid cbm -> cbm field extraction
    # 4. labeled/mixed, no cbm   -> legacy field extraction
    if not template_data:
        _log("ROUTE", f"{file_path.name}: NO TEMPLATE -> unguided extraction")
        return _run_unguided_extraction(**ctx)

    meta = (binding_map or {}).get("_meta", {}) if binding_map else {}
    template_type = meta.get("template_type", "labeled")
    vt = meta.get("value_target_count", 0)
    td = meta.get("table_data_count", 0)
    ng = len(meta.get("column_groups", []))

    # 2. STRUCTURAL — always the three-layer layout path. A stored cell_binding_map
    # is deliberately ignored here (a structural template must never use CBM).
    if template_type == "structural":
        _log("ROUTE", f"{file_path.name}: template_type=structural "
                      f"(value_targets={vt}, table_data={td}, groups={ng}) -> layout extraction")
        return _run_layout_extraction(**ctx)

    # 3. LABELED / MIXED with a valid stored CBM -> CBM field extraction.
    cbm = template_data.get("cell_binding_map")
    if (template_type in ("labeled", "mixed")
            and isinstance(cbm, dict)
            and (cbm.get("extract_cells") or cbm.get("tables"))):
        _log("ROUTE", f"{file_path.name}: template_type={template_type} + stored CBM "
                      f"({len(cbm.get('extract_cells', {}) or {})} cells, "
                      f"{len(cbm.get('tables', []) or [])} tables) -> cbm field extraction")
        return _run_cbm_extraction(orchestrator=orchestrator, file_path=file_path,
                                   template_data=template_data, cell_binding_map=cbm,
                                   binding_map=binding_map, page_images=page_images,
                                   doc_text=doc_text, doc_text_pages=doc_text_pages,
                                   file_type=ftype, default_doc_type=default_doc_type,
                                   start=start)

    # 4. LABELED / MIXED without a CBM -> legacy field path (handles KV + table).
    _log("ROUTE", f"{file_path.name}: template_type={template_type} (no CBM) "
                  f"(value_targets={vt}, table_data={td}, groups={ng}) -> field extraction")
    return _run_field_extraction(**ctx)
