"""
DocAgent — Extraction Engine
============================

The single extraction entry point. `run_extraction` routes a templated
document to slot-directed extraction (engine/slot_extractor.py); a document
with no template still goes through the three layers below, until Phase 3
gives it an inferred shape and sends it through the same slot pipeline.

Phase 2d removed the USE_NEW_EXTRACTOR flag, the legacy inline pipeline in
extract.py, and the layout/field/CBM paths. There is one templated pipeline
and no silent fallback between engines.

THREE LAYERS (no-template path only):

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


def _unwrap_all(parsed):
    """
    A7 — return EVERY document dict from a Gemini response. The old _unwrap took
    documents[0] and silently discarded every other document, so a file holding
    two invoices exported only the first. Top-level fields (extracted_fields /
    table_rows) are merged into the first document when it lacks them.
    """
    if not isinstance(parsed, dict):
        return [{}]
    docs = parsed.get("documents")
    if isinstance(docs, list):
        docs = [d for d in docs if isinstance(d, dict)]
        if docs:
            for key in ("extracted_fields", "table_rows", "layout_sections"):
                if parsed.get(key) and not docs[0].get(key):
                    docs[0][key] = parsed[key]
            return docs
    return [parsed]


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
    base_delay = 1
    for attempt in range(3):
        err_txt = ""
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


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 1 — DOCUMENT INTELLIGENCE
# ══════════════════════════════════════════════════════════════════════════════

_L1_SYSTEM = (
    "You are an expert document analyst with deep knowledge of business documents. "
    "Your task is to create a complete inventory of a document before extraction begins."
)


_L1_MAX_PAGES = 20


def _understand_document(orchestrator, page_images, doc_text, binding_map, file_type):
    """LAYER 1 — ONE Gemini call inventorying the whole file. Returns (document_map, response)."""
    # E4 — very large documents: cap the Layer-1 mapping call at the first 20
    # pages to stay inside Gemini's context limit. Layer 2 is unaffected — it
    # always sends each section's OWN page(s).
    l1_images = page_images
    if page_images and len(page_images) > _L1_MAX_PAGES:
        _log("L1", f"large document — using first {_L1_MAX_PAGES} of "
                   f"{len(page_images)} pages for the document map")
        l1_images = page_images[:_L1_MAX_PAGES]
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
                             images=l1_images, text=doc_text)
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
            # A3 — even without a designated total cell, the total must NEVER be
            # returned as a line-item row (it corrupts a neighbouring row's value).
            total_block = ("\nDo NOT include the section's TOTAL/SUBTOTAL row in "
                           "rows — line items only.\n")
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
            "- PAIRING: each row's value must be the amount printed on the SAME "
            "line as that row's label in the document. NEVER assign a section "
            "total or another line's amount to a different label.\n"
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
    # S5 — a section returning far MORE rows than the document map counted has
    # almost certainly absorbed the next section's items (e.g. Shareholders
    # Equity rows under TOTAL LIABILITIES & EQUITY). Truncate to item_count when
    # the excess is beyond a 1.5x tolerance (Gemini's counts are approximate).
    expected = int(section_info.get("item_count", 0) or 0)
    if expected > 0 and len(out_rows) > expected * 1.5:
        _log("L2", f"section '{section_info.get('heading', 'section')}' truncated "
                   f"{len(out_rows)} -> {expected} rows (document map item_count="
                   f"{expected}; excess likely belongs to the next section)")
        out_rows = out_rows[:expected]
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
        sec_to_group = {}

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
                # S1 — the group's total cell comes from the binding map's
                # total-label scan (total_cells). The old window scan picked ANY
                # value_target between start_row and end_row+2 — including labeled
                # DATA rows inside the band (that's how B5 was used as a "total"
                # when the real total row is B9).
                tc_list = grp.get("total_cells") or []
                total_cell = tc_list[0] if tc_list else None
                if total_cell is None:
                    # legacy maps without total_cells: scan strictly BELOW the band
                    cand = [fc for fc in fixed_cells
                            if fc["col"] == grp.get("value_col")
                            and int(grp.get("end_row", 0)) < fc["row"] <= int(grp.get("end_row", 0)) + 3]
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


def _validate_extraction(extracted, doc_text, doc_type, file_type, document_map_doc,
                         column_groups=None):
    """LAYER 3 — confidence per value + cross-checks. Returns (confidence_map, flagged, notes,
    overall_confidence, needs_review).

    column_groups (V1): the template's binding-map column groups — each section's
    total is cross-validated ONLY against its OWN group's total_cell.
    """
    ls = extracted.get("layout_sections", {})

    # E1 — scanned / image / no text layer: pdfplumber text is empty or garbage,
    # so text cross-validation would flag every correct value. Skip it entirely:
    # every value medium, needs_review globally, one clear note.
    if file_type in ("scanned_pdf", "image") or len((doc_text or "").strip()) < 50:
        conf_map = {}
        for sec_label, block in (ls.items() if isinstance(ls, dict) else []):
            for row in (block.get("rows", []) if isinstance(block, dict) else []):
                if isinstance(row, dict):
                    conf_map[f"{row.get('value_col', '')}{row.get('row', '')}"] = "medium"
        for ref in (extracted.get("extracted_fields", {}) or {}):
            conf_map[ref] = "medium"
        notes = ["Scanned document — manual verification recommended"]
        _log("L3", "scanned/low-text document — text cross-validation skipped, "
                   "all values medium, needs_review forced")
        return conf_map, [], notes, "medium", True

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

    # Step 2 — financial cross-validation: each section's item sum vs its OWN
    # column group's total_cell (V1). The old logic compared against ANY
    # extracted_field in the same column letter, so Current assets (col B) was
    # checked against B11 — Current LIABILITIES' total — a guaranteed false
    # positive. Sections whose group has no total_cell are skipped.
    if (doc_type or "").lower() in _FINANCIAL_TYPES:
        cgs = column_groups or []

        def _group_for(sec_label):
            n = _norm(sec_label)
            for g in cgs:                                  # exact
                if _norm(g.get("section_label")) == n:
                    return g
            for g in cgs:                                  # fuzzy substring
                gn = _norm(g.get("section_label"))
                if gn and n and (gn in n or n in gn):
                    return g
            return None

        for sec_label, block in (ls.items() if isinstance(ls, dict) else []):
            rows = block.get("rows", []) if isinstance(block, dict) else []
            grp = _group_for(sec_label)
            tot_refs = (grp.get("total_cells") or []) if grp else []
            if not tot_refs:
                continue          # V1: no own total cell -> no cross-validation
            tot_raw = (extracted.get("extracted_fields", {}) or {}).get(tot_refs[0])
            tot = _num(tot_raw.get("value") if isinstance(tot_raw, dict) else tot_raw)
            if not tot:
                continue
            s = sum(v for v in (_num(r.get("value")) for r in rows if isinstance(r, dict)) if v is not None)
            if abs(s - tot) / abs(tot) > 0.01:
                notes.append(f"Section '{sec_label}' total mismatch — items sum to "
                             f"{s:g}, own total {tot_refs[0]} shows {tot:g}")
                flagged.append({"ref": tot_refs[0], "value": str(tot),
                                "issue": "section total mismatch"})
            # A3 — a line item carrying the SECTION TOTAL as its value is the
            # signature of a label/value misassignment. Flag for review.
            if len(rows) > 1:
                for r_i in rows:
                    if not isinstance(r_i, dict):
                        continue
                    rv = _num(r_i.get("value"))
                    if rv is not None and rv == tot:
                        rref = f"{r_i.get('value_col','')}{r_i.get('row','')}"
                        notes.append(f"Section '{sec_label}': row "
                                     f"'{r_i.get('label','')}' value equals the "
                                     f"section total ({tot:g}) — likely misassigned")
                        flagged.append({"ref": rref, "value": str(rv),
                                        "issue": "row value equals section total"})

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

    # (Scanned/image documents returned early above — E1.)
    confs = list(conf_map.values())
    if "low" in confs:
        overall = "low"
    elif "medium" in confs:
        overall = "medium"
    else:
        overall = "high"
    needs_review = bool(flagged) or overall == "low"

    n_high = confs.count("high"); n_med = confs.count("medium"); n_low = confs.count("low")
    _log("L3", f"validation: {n_high} high, {n_med} medium, {n_low} low confidence")
    if needs_review:
        _log("L3", f"needs_review: {notes[0] if notes else 'low-confidence values'}")
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




# CBM extraction is a single focused call where accuracy matters more than cost —
# pin it to the stronger gemini-2.5-flash tier (not the default -lite, which has
# been observed returning bare currency symbols instead of full amounts).
_CBM_MODEL = "gemini-2.5-flash"
_BARE_CURRENCY = {"$", "£", "€", "₹", "¥"}










def _run_three_layer(orchestrator, file_path, template_data, binding_map, page_images,
                     doc_text, doc_text_pages, file_type, default_doc_type, start,
                     primary_mode):
    """Layer 1 → Layer 2 → Layer 3. Reached only by the NO-TEMPLATE path now;
    Phase 3 replaces it with shape inference feeding the one slot pipeline."""
    from app.api.routes.extract import _fail
    document_map, l1_resp = _understand_document(orchestrator, page_images, doc_text,
                                                 binding_map, file_type)
    file_type = document_map.get("file_type", file_type)
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
            ext, doc_text, doc_type, file_type, d, column_groups=cgs)
        all_resps = ([l1_resp] if l1_resp is not None else []) + l2_responses
        seg_fn = (file_path.name if len(docs) == 1
                  else f"{file_path.stem}_doc{di+1}{file_path.suffix}")
        results.append(_assemble_result(
            seg_fn, di, doc_type, ext.get("identifier", ""),
            ext.get("layout_sections", {}), ext.get("extracted_fields", {}),
            cgs, primary_mode, d, conf_map, flagged, notes, overall, needs_review,
            all_resps, (time.time() - start) * 1000))
    return results or [_fail(file_path.name, "no documents extracted")]




def _run_unguided_extraction(orchestrator, file_path, template_data, binding_map,
                             page_images, doc_text, doc_text_pages, file_type,
                             default_doc_type, start):
    """NO template: extract everything, two-column A/B output via the three layers."""
    _log("UNGUIDED", f"{file_path.name}: no template — full document, two-column A/B")
    return _run_three_layer(orchestrator, file_path, None, None,
                            page_images, doc_text, doc_text_pages, file_type,
                            default_doc_type, start, primary_mode="unguided")


# Document types routed to slot-directed extraction. Phase 1 scoped this to
# bank_statement so the change could be measured in isolation; Phase 2c widens
# it to every document type, because slot addressing by (row label, column
# header) is what removes the layout path's 2-column ceiling.
# None = all document types.
_SLOT_DOC_TYPES = None


def run_extraction(orchestrator, file_path, template_data, selected_pages=None):
    """
    Single entry point. Returns list[DocumentExtractionResult].

    Two outcomes, decided at the start:

      no template (or a template with no slots) -> _run_unguided_extraction
      a template with a usable shape            -> slot-directed extraction

    The shape says how many columns the template needs; slot addressing serves
    any number, so the only way to fail is a template with nowhere to put
    anything — and that fails loudly, with a message saying what to change.
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

    # ── ROUTING DECISION AT THE START — STRICT SEPARATION (the 3 paths never cross) ──
    # 1. no template            -> unguided
    # 2. template_type structural -> layout (NEVER cbm, even if a cbm exists)
    # 3. labeled/mixed + valid cbm -> cbm field extraction
    # 4. labeled/mixed, no cbm   -> legacy field extraction
    if not template_data:
        _log("ROUTE", f"{file_path.name}: NO TEMPLATE -> unguided extraction")
        return _run_unguided_extraction(**ctx)

    # E6 — EMPTY TEMPLATE: a saved grid with zero content cells (no values, no
    # extract targets) gives extraction nothing to anchor to. Treat it exactly
    # like no template: unguided extraction instead of a garbage field prompt.
    if template_data.get("mode", "layout") == "layout":
        tpl_cells = (template_data.get("layout") or {}).get("cells") or {}
        has_content = any(
            isinstance(cd, dict) and (str(cd.get("value") or "").strip()
                                      or cd.get("extractTarget"))
            for cd in tpl_cells.values())
        if not has_content:
            _log("ROUTE", f"{file_path.name}: EMPTY TEMPLATE (0 content cells) "
                          f"-> unguided extraction")
            ctx["template_data"] = None
            ctx["binding_map"] = None
            return _run_unguided_extraction(**ctx)

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
