"""
DocAgent — Shape Inference (Phase 3)

No-template extraction is not a second engine. It is the same slot-directed
pipeline, with the shape coming from inference instead of from the user:

    with a template:  user's grid  -> shape -> slot extraction
    without one:      inferred grid -> shape -> slot extraction

Inference reads the document once and returns a REAL TEMPLATE — document type,
header fields, repeating tables with their actual column names, totals. That
template is built into the same `SheetSaveData` grid the editor saves, so:

  - `compute_shape` derives its shape by the same one rule as any other
    template (text = static label, empty = slot),
  - `run_slot_extraction` fills it with no knowledge that it was inferred,
  - `_write_slot_excel` writes it with proper column headers rather than
    dumping everything into one column,
  - and the grid can be handed back to the UI as "save this as a template".

Two documents that infer the same shape share one template and stack into one
sheet; the signature is what decides that.
"""

import hashlib
import json
import re

from extractor import _llm_json, _log

_SYSTEM = (
    "You are a document analyst who designs spreadsheet templates. Given a "
    "document, you describe the template someone would build to extract it: "
    "the single-value fields it has, the repeating tables it has and their "
    "real column names, and its totals. You describe structure only — never "
    "the values themselves."
)

_MAX_TEXT = 12000


def infer_template(orchestrator, doc_text_pages, page_images, filename=""):
    """One LLM call. Returns the inferred template dict, or None on failure."""
    text = "\n".join(f"--- page {i} ---\n{t or ''}"
                     for i, t in enumerate(doc_text_pages or [], 1))[:_MAX_TEXT]

    prompt = (
        "Design the spreadsheet template for extracting this document.\n\n"
        "=== DOCUMENT ===\n" + text + "\n=== END DOCUMENT ===\n\n"
        "Describe its STRUCTURE, not its values:\n\n"
        "1. document_type — one of: sales_invoice, purchase_order, cheque, "
        "receipt, pay_order, bank_statement, payslip, expense_report, "
        "tax_form, income_statement, balance_sheet, audit_report, other.\n"
        "2. title — a short human title for the sheet.\n"
        "3. fields — EVERY single value the document states, in the order it "
        "appears. Give each a short label, using the document's own wording "
        "where it has some and a plain descriptive one where it does not.\n"
        "   Do not stop at the neatly labelled ones. Include:\n"
        "   - values in a BLOCK under one heading. 'Bill To:' followed by a "
        "company, a street address and a contact person is THREE fields "
        "(Bill To Company, Bill To Address, Bill To Contact), not one.\n"
        "   - values in a party block laid out side by side, e.g. a Vendor "
        "column and a Buyer column: give every line of BOTH sides a field.\n"
        "   - letterhead values: the issuing company's name, address, phone, "
        "tax/registration number, printed above or beside the title.\n"
        "   - values with NO label at all: a stamped or printed status (PAID, "
        "OUTSTANDING, APPROVED, VOID), a signature name, a bank's MICR line "
        "and the routing and account numbers inside it, a cheque's payer and "
        "its amount in figures and in words.\n"
        "   - amounts that sit in their own box rather than on a labelled "
        "row.\n"
        "   But a REPEATING group of similar rows is a table (item 4), not a "
        "list of fields — do not list its rows here. A balance sheet's "
        "'Current Assets' or an income statement's 'Operating Expenses' is a "
        "table of label/amount rows, not twenty fields.\n"
        "4. tables — every REPEATING group of rows. For each: a name, its real "
        "column headings in left-to-right order, and how many rows it has.\n"
        "5. totals — the summary values at the end (subtotal, tax, total, "
        "closing balance).\n\n"
        "Return ONLY this JSON:\n"
        "{\n"
        '  "document_type": "bank_statement",\n'
        '  "title": "Account Statement",\n'
        '  "fields": ["Bank Name", "Account Holder", "Statement No"],\n'
        '  "tables": [{"name": "Transactions",\n'
        '              "columns": ["Date", "Description", "Debit", "Credit"],\n'
        '              "row_count": 12}],\n'
        '  "totals": ["Total Credits", "Closing Balance"]\n'
        "}\n\n"
        "RULES\n"
        "- A column heading is a heading, never a value: 'Date', not '01/03'.\n"
        "- A field label is a label, never a value: 'Invoice Number', not "
        "'INV-2024-0031'.\n"
        "- Give a table EVERY column the document shows, even ones that are "
        "blank on most rows. A statement with separate Debit and Credit "
        "columns has both.\n"
        "- Do not invent fields the document does not have.\n"
        "- A value that is printed on the page has a field, whether or not "
        "anything labels it. Missing it is the most common failure — go back "
        "over the letterhead, the party blocks, any stamp, and the footer "
        "before you answer.\n"
        "- Give each part of a block its own field rather than one field "
        "holding several values.\n"
        "- If the document has no repeating rows, return \"tables\": [].\n"
    )

    # TEMPERATURE 0. Inference decides what the columns are CALLED, and a
    # near-tie between two equally correct names ("Doc No" vs "Document
    # Number", "Company EIN" vs "Company Tax ID") resolves differently on each
    # sample. That renamed columns between runs of the SAME document, and — via
    # `signature()`, which hashes the field names — gave two invoices with the
    # identical printed layout two different shapes, so a batch that should be
    # one sheet became several.
    #
    # This is a floor, not a fix. Gemini offers NO reproducibility guarantee
    # even at temperature 0: there is no seed parameter in the REST API used
    # here, and batching and kernel scheduling make identical requests able to
    # return different tokens. It removes the sampling contribution to the
    # variance; the structural contribution — that "what should this column be
    # called" has several correct answers — is untouched by any decoding
    # setting, and needs a fixed vocabulary or a reused schema.
    parsed, resp = _llm_json(orchestrator, prompt, _SYSTEM,
                             images=page_images, text=text, temperature=0)
    if not isinstance(parsed, dict):
        _log("INFER", f"{filename}: no usable template inferred")
        return None

    inferred = _clean(parsed)
    if not (inferred["fields"] or inferred["tables"] or inferred["totals"]):
        _log("INFER", f"{filename}: inferred template is empty")
        return None

    _log("INFER", f"{filename}: {inferred['document_type']} — "
                  f"{len(inferred['fields'])} fields, "
                  f"{len(inferred['tables'])} table(s) "
                  f"({', '.join(str(len(t['columns'])) + 'col' for t in inferred['tables']) or 'none'}), "
                  f"{len(inferred['totals'])} total(s)")
    return inferred


def _labels(seq):
    """Clean a list of label strings: strings only, trimmed, deduped, ordered."""
    out, seen = [], set()
    for x in seq or []:
        if isinstance(x, dict):
            x = x.get("label") or x.get("name") or ""
        s = re.sub(r"\s+", " ", str(x or "")).strip().strip(":").strip()
        if not s or len(s) > 60:
            continue
        k = s.casefold()
        if k in seen:
            continue
        seen.add(k)
        out.append(s)
    return out


def _clean(parsed):
    tables = []
    for t in parsed.get("tables") or []:
        if not isinstance(t, dict):
            continue
        cols = _labels(t.get("columns"))
        if len(cols) < 2:
            continue                      # a one-column "table" is a field list
        try:
            n = int(t.get("row_count") or 0)
        except (TypeError, ValueError):
            n = 0
        name = re.sub(r"\s+", " ", str(t.get("name") or "Items")).strip() or "Items"
        tables.append({"name": name, "columns": cols,
                       "row_count": max(3, min(n or 8, 200))})
    return {
        "document_type": str(parsed.get("document_type") or "other").strip() or "other",
        "title": re.sub(r"\s+", " ", str(parsed.get("title") or "")).strip(),
        "fields": _labels(parsed.get("fields")),
        "tables": tables,
        "totals": _labels(parsed.get("totals")),
    }


# ══════════════════════════════════════════════════════════════════════════════
# INFERRED TEMPLATE -> GRID
# ══════════════════════════════════════════════════════════════════════════════

def build_grid(inferred):
    """Inferred template -> the same SheetSaveData grid the editor saves.

    Laid out so `compute_shape` reads it by the ordinary rule: a label in
    column A with an empty cell beside it is a field slot; a row of column
    headings with empty rows beneath it is a repeating band.
    """
    cells, r = {}, 0
    widths = []

    def put(row, col, value=""):
        cells[f"{row},{col}"] = {"value": value, "style": {}}

    for label in inferred["fields"]:
        put(r, 0, label)
        put(r, 1, "")
        r += 1

    for t in inferred["tables"]:
        if r:
            r += 1                                   # spacer above a band
        put(r, 0, t["name"])                         # section title for the band
        r += 1
        for c, head in enumerate(t["columns"]):
            put(r, c, head)
        r += 1
        for _ in range(t["row_count"]):              # the band's empty rows
            r += 1
        widths = widths or [max(90, min(300, 14 * len(h))) for h in t["columns"]]

    if inferred["totals"]:
        # A spacer is only needed when fields ran straight into the totals; a
        # band already ends in blank rows, and an extra one would just extend
        # the band (a band runs to the row before the next static cell).
        if r and not inferred["tables"]:
            r += 1
        for label in inferred["totals"]:
            put(r, 0, label)
            put(r, 1, "")
            r += 1

    max_col = max((int(k.split(",")[1]) for k in cells), default=1)
    if not widths:
        widths = [240, 140]
    while len(widths) <= max_col:
        widths.append(120)

    return {"cells": cells, "colWidths": widths[:max_col + 1],
            "merges": {}, "repeatRows": []}


def signature(inferred):
    """Stable id for a shape. Two documents with the same signature share one
    template and stack into one sheet — never one template per document when
    the shapes match."""
    payload = {
        "document_type": inferred["document_type"],
        "fields": [f.casefold() for f in inferred["fields"]],
        "tables": [{"columns": [c.casefold() for c in t["columns"]]}
                   for t in inferred["tables"]],
        "totals": [t.casefold() for t in inferred["totals"]],
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def saveable_template(inferred, grid, name=""):
    """The artifact the UI offers as 'save this as a template' — exactly the
    payload POST /api/templates accepts."""
    columns = [{"name": f, "type": "Text", "order": i}
               for i, f in enumerate(inferred["fields"])]
    for t in inferred["tables"]:
        for c in t["columns"]:
            columns.append({"name": c, "type": "Text", "order": len(columns),
                            "extraction_type": "lineitem"})
    for i, f in enumerate(inferred["totals"]):
        columns.append({"name": f, "type": "Text", "order": len(columns)})
    return {
        "name": name or inferred["title"] or "Inferred template",
        "document_type": inferred["document_type"],
        "description": json.dumps(grid),
        "columns": columns,
    }
