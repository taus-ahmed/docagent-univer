"""
DocAgent — Slot-Directed Extraction (Phase 1)
=============================================

Replaces "extract a bag of values, then match them into template cells" with
"enumerate the template's cells as addressed slots, ask the model to fill each
slot, write the answer where it was asked for."

There is no matching step afterward. That removes, as a class:
  - wrong-cell placement      (the answer is written where it was requested)
  - silent empty cells        (every slot is asked about; "" is an answer)
  - duplicate values          (a slot is asked once and holds one answer)
  - total-vs-line ambiguity   (the total slot is a different address from the
                               line-item slots, and is asked for separately)

GROUNDING. Every filled slot returns the value AND the verbatim source span it
came from, plus the page. The span is checked against the document text (read
with pdfplumber, independently of the model). A value whose span cannot be
located in the document is not written as a confident value: it is kept, marked
low confidence, and flagged for review.

Table rows carry a ROW-level source span — the document line the row was read
from. That grounds every cell in the row (each cell's value must appear inside
its own row's span) and additionally catches fabricated or duplicated rows,
which a per-cell span cannot.

SHAPE. Slots are derived from the grid by one rule, the same rule Phase 2a will
persist as template metadata:

    a cell with text is a STATIC label;  an empty cell is a SLOT.

  - a row with a static label in the label column and an empty cell beside it
    is a FIELD slot, addressed by that label
  - a row of two or more adjacent static cells with empty rows beneath it is a
    TABLE HEADER; the empty rows below are that table's band, and each cell in
    the band is addressed by (row ordinal, column header)

This module produces `DocumentExtractionResult` objects whose `.extracted_data`
matches the existing downstream contract, so writers, routes and the save path
are unchanged.
"""

import re
import time
from pathlib import Path

from extractor import _llm_json, _log, _num


# ── text normalisation (grounding) ───────────────────────────────────────────

_DASHES = {"–": "-", "—": "-", "−": "-", "‐": "-", "‑": "-"}


def _flat(s) -> str:
    """Collapse whitespace, unify dashes, drop case — for span matching."""
    t = str(s or "")
    for k, v in _DASHES.items():
        t = t.replace(k, v)
    return re.sub(r"\s+", " ", t).strip().casefold()


def _digits(s) -> str:
    return re.sub(r"[^0-9]", "", str(s or ""))


# ══════════════════════════════════════════════════════════════════════════════
# SLOT ENUMERATION
# ══════════════════════════════════════════════════════════════════════════════

def slots_from_shape(shape):
    """Shape (2a) -> the addressed slots this module fills."""
    return {"fields": list((shape or {}).get("field_slots") or []),
            "tables": list((shape or {}).get("repeat_bands") or [])}


def enumerate_slots(grid, shape=None):
    """Addressed slots for a template.

    Prefers the template's STORED shape (Phase 2a). Falls back to inferring it
    from the grid for templates saved before shape metadata existed — the
    inference is identical, it just has not been persisted yet.
    """
    if shape:
        return slots_from_shape(shape)
    from template_shape import compute_shape
    return slots_from_shape(compute_shape(grid, log=lambda msg: _log("SLOT", msg)))


# ══════════════════════════════════════════════════════════════════════════════
# PROMPT
# ══════════════════════════════════════════════════════════════════════════════

_SYSTEM = (
    "You are filling in a spreadsheet from a source document. You are given a "
    "list of SLOTS, each with its address in the sheet. You fill each slot with "
    "the value that belongs at that address, and you quote the exact text you "
    "read it from. You never move a value from one slot to another, and you "
    "never invent a value that is not in the document."
)


def build_prompt(slots, page_texts, doc_type=""):
    fields, tables = slots["fields"], slots["tables"]
    p = []
    p.append(f"Fill in a {doc_type or 'document'} spreadsheet from the document below.\n")

    p.append("=== DOCUMENT TEXT ===")
    for i, txt in enumerate(page_texts, 1):
        p.append(f"--- page {i} ---\n{txt or ''}")
    p.append("=== END DOCUMENT ===\n")

    if fields:
        p.append("FIELD SLOTS — each is one cell. Answer every one by its slot id:")
        for f in fields:
            addr = f'row label "{f["row_label"]}"'
            if f["section"]:
                addr = f'section "{f["section"]}", ' + addr
            p.append(f'  {f["slot_id"]}: {addr}')
        p.append("")

    for t in tables:
        cols = " | ".join(c.get("key") or c["header"] for c in t["columns"])
        p.append(f'TABLE "{t["name"]}" — one object per row present in the document.')
        if t["section"]:
            p.append(f'  section: "{t["section"]}"')
        p.append(f"  columns (use EXACTLY these keys): {cols}")
        p.append(f'  the sheet has {t["end_row"] - t["start_row"] + 1} blank rows for it; '
                 f"return as many rows as the document actually has, not that number.")
        p.append("")

    p.append("Return ONLY this JSON:")
    p.append("{")
    if fields:
        p.append('  "fields": {')
        p.append('    "F1": {"value": "...", "source": "<exact line from the document>", "page": 1}')
        p.append("  },")
    if tables:
        t0 = tables[0]
        keys = ", ".join(f'"{c.get("key") or c["header"]}": "..."'
                         for c in t0["columns"][:3])
        p.append('  "tables": {')
        p.append(f'    "{t0["name"]}": [')
        p.append(f'      {{"cells": {{{keys}, ...}}, '
                 f'"source": "<the exact document line this row was read from>", "page": 1}}')
        p.append("    ]")
        p.append("  }")
    p.append("}\n")

    p.append("RULES")
    p.append('- "source" MUST be copied verbatim from the document text above — the exact '
             "line or span the value was read from. It is checked against the document; a "
             "source that does not appear there marks the value unverified.")
    p.append("- Every value you give must appear inside its own source span.")
    p.append('- A slot the document has no value for: {"value": "", "source": "", "page": 0}. '
             "Never guess, never carry a value over from a neighbouring slot.")
    p.append("- In a table row, a column that is blank on that document line must be \"\". "
             "Never shift a value into a different column to fill a gap — a Debit is not a "
             "Credit, and an empty cell is a real answer.")
    p.append("- One row object per document line. Never merge two lines into one row, and "
             "never repeat a line as two rows.")
    p.append("- Give the value only, not the label: for a slot labelled \"Closing Balance\", "
             'answer "125,357.26", not "Closing Balance: 125,357.26".')
    return "\n".join(p)


# ══════════════════════════════════════════════════════════════════════════════
# GROUNDING
# ══════════════════════════════════════════════════════════════════════════════

def verify_span(value, source, page, page_texts):
    """(grounded, reason). An empty answer needs no grounding."""
    if value is None or str(value).strip() == "":
        return True, "empty"
    src = _flat(source)
    if not src:
        return False, "no source span given"

    haystacks = [_flat(t) for t in page_texts]
    try:
        pi = int(page) - 1
    except (TypeError, ValueError):
        pi = -1
    ordered = ([haystacks[pi]] if 0 <= pi < len(haystacks) else []) + haystacks
    if not any(src in h for h in ordered if h):
        return False, "source span not found in document"

    # the value must sit inside the span it claims to come from
    val = _flat(value)
    if val and val in src:
        return True, ""
    dv, ds = _digits(value), _digits(source)
    if dv and dv in ds:
        return True, ""
    n = _num(value)
    if n is not None:
        for tok in re.findall(r"\(?-?[\d,]*\.?\d+\)?", str(source)):
            t = _num(tok)
            if t is not None and round(abs(t), 2) == round(abs(n), 2):
                return True, ""
    return False, "value not found inside its own source span"


# ══════════════════════════════════════════════════════════════════════════════
# RUN
# ══════════════════════════════════════════════════════════════════════════════

def run_slot_extraction(orchestrator, file_path, template_data, binding_map,
                        page_images, doc_text, doc_text_pages, file_type,
                        default_doc_type, start):
    """Slot-directed extraction for one file. Returns list[DocumentExtractionResult]."""
    from orchestrator import DocumentExtractionResult

    file_path = Path(file_path)
    grid = (template_data or {}).get("layout", {}) or {}
    shape = (template_data or {}).get("shape")
    slots = enumerate_slots(grid, shape)
    if shape:
        _log("SLOT", f"{file_path.name}: using STORED template shape")
    n_tbl_cols = sum(len(t["columns"]) for t in slots["tables"])
    _log("SLOT", f"{file_path.name}: {len(slots['fields'])} field slots, "
                 f"{len(slots['tables'])} table(s), {n_tbl_cols} table columns")

    pages = doc_text_pages or ([doc_text] if doc_text else [])
    prompt = build_prompt(slots, pages, default_doc_type)
    parsed, resp = _llm_json(orchestrator, prompt, _SYSTEM,
                             images=page_images, text=doc_text)
    if not isinstance(parsed, dict):
        _log("SLOT", "no parseable response — failing the document")
        from app.api.routes.extract import _fail
        return [_fail(file_path.name, "Slot extraction returned no usable JSON")]

    by_id = {f["slot_id"]: f for f in slots["fields"]}
    extracted_fields, conf_map, flagged, notes = {}, {}, [], []
    ungrounded = 0

    # ── field slots ──
    answers = parsed.get("fields") or {}
    if isinstance(answers, dict):
        for sid, ans in answers.items():
            slot = by_id.get(str(sid).strip())
            if slot is None:
                notes.append(f"answer for unknown slot id {sid!r} discarded")
                continue
            if isinstance(ans, dict):
                value, source, page = ans.get("value", ""), ans.get("source", ""), ans.get("page", 0)
            else:
                value, source, page = ans, "", 0
            if str(value).strip() == "":
                continue
            ok, why = verify_span(value, source, page, pages)
            extracted_fields[slot["ref"]] = value
            conf_map[slot["ref"]] = "high" if ok else "low"
            if not ok:
                ungrounded += 1
                flagged.append(f'{slot["row_label"]}: {why}')

    unanswered = [f for f in slots["fields"] if f["ref"] not in extracted_fields]
    if unanswered:
        notes.append(f"{len(unanswered)} field slot(s) returned no value: "
                     + ", ".join(f["row_label"] for f in unanswered[:8]))

    # ── table slots ──
    tables_out, row_counts = {}, {}
    resp_tables = parsed.get("tables") or {}
    if isinstance(resp_tables, dict):
        for t in slots["tables"]:
            raw = resp_tables.get(t["name"])
            if raw is None and len(slots["tables"]) == 1 and len(resp_tables) == 1:
                raw = next(iter(resp_tables.values()))  # model renamed the table
            if not isinstance(raw, list):
                continue
            headers = [c.get("key") or c["header"] for c in t["columns"]]
            seen_sources, rows_out = set(), []
            for r in raw:
                if not isinstance(r, dict):
                    continue
                cells = r.get("cells") if isinstance(r.get("cells"), dict) else r
                source, page = r.get("source", ""), r.get("page", 0)
                key = _flat(source)
                if key and key in seen_sources:
                    notes.append("duplicate row dropped — two rows claim the same "
                                 f"source line: {str(source)[:60]!r}")
                    continue
                if key:
                    seen_sources.add(key)
                row, row_conf = {}, "high"
                for h in headers:
                    v = cells.get(h, "")
                    if v is None:
                        v = ""
                    if str(v).strip() == "":
                        row[h] = ""
                        continue
                    ok, why = verify_span(v, source, page, pages)
                    row[h] = v
                    if not ok:
                        ungrounded += 1
                        row_conf = "low"
                        flagged.append(f'{t["name"]}[{len(rows_out)}].{h}: {why}')
                if any(str(v).strip() for v in row.values()):
                    row["_confidence"] = row_conf
                    rows_out.append(row)
            tables_out[t["name"]] = rows_out
            row_counts[t["name"]] = len(rows_out)

    total_cells = len(extracted_fields) + sum(
        len([v for k, v in r.items() if not k.startswith("_") and str(v).strip()])
        for rows in tables_out.values() for r in rows)
    _log("SLOT", f"filled {len(extracted_fields)}/{len(slots['fields'])} field slots, "
                 f"table rows {row_counts}, {ungrounded} ungrounded value(s)")

    overall = "high" if ungrounded == 0 else ("medium" if ungrounded <= 2 else "low")
    if file_type in ("scanned_pdf", "image") or len(doc_text.strip()) < 50:
        overall = "medium"
        notes.append("Scanned document — spans could not be verified against text")
        conf_map = {k: "medium" for k in conf_map}
    needs_review = bool(ungrounded) or bool(unanswered)

    r = DocumentExtractionResult(filename=file_path.name)
    r.document_type = default_doc_type
    r.success = True
    r.processing_time_ms = int((time.time() - start) * 1000)

    kv = {}
    for ref, v in extracted_fields.items():
        slot = next((f for f in slots["fields"] if f["ref"] == ref), None)
        kv[slot["row_label"] if slot else ref] = {
            "value": v, "confidence": conf_map.get(ref, "high"), "ref": ref}

    ed = {
        "document_type": default_doc_type,
        "overall_confidence": overall,
        "extraction_method": "slot_directed",
        "layout_sections": {},
        "extracted_fields": extracted_fields,
        "extracted_data": kv,
        "table_rows": [],
        "slot_map": {
            "fields": [{k: f[k] for k in ("slot_id", "ref", "row_label", "section")}
                       for f in slots["fields"]],
            "tables": [{"name": t["name"], "header_row": t["header_row"],
                        "start_row": t["start_row"], "end_row": t["end_row"],
                        "columns": t["columns"]} for t in slots["tables"]],
        },
        "validation": {
            "flagged_count": len(flagged),
            "flagged_fields": flagged,
            "confidence_map": conf_map,
            "ungrounded_count": ungrounded,
            "grounded_count": max(0, total_cells - ungrounded),
        },
        "validation_notes": notes,
        "needs_review": needs_review,
        "template_type": "slot",
        "template_regions": {"primary_mode": "slot"},
        "raw_llm_responses": [getattr(resp, "raw_text", "")] if resp else [],
    }
    for name, rows in tables_out.items():
        ed[f"{name}_rows"] = rows
    r.extracted_data = ed
    r.extraction_response = resp
    _log("RESULT", f"slot-directed: {len(kv)} fields, "
                   f"{sum(len(v) for v in tables_out.values())} table rows, {overall}")
    return [r]
