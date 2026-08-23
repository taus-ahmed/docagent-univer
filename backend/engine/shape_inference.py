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
from vocabulary import split_other, vocabulary_block

_SYSTEM = (
    "You are a document analyst who designs spreadsheet templates. Given a "
    "document, you describe the template someone would build to extract it: "
    "the single-value fields it has, the repeating tables it has and their "
    "real column names, and its totals. You describe structure only — never "
    "the values themselves."
)

_MAX_TEXT = 12000


# ── deterministic section detection ──────────────────────────────────────────
#
# "A heading followed by 3+ label/amount lines is a table" is a rule about
# SHAPE, and shape is visible in the text. Asking the model to apply it worked
# on some documents and not others, and flipped between runs on the same
# document — the balance sheet obeyed it, the income statement did not, and
# each rewording moved which one complied. That is the failure decision-log §3
# warns about: a rule applied to a shape it cannot reliably express, failing
# silently.
#
# So the sections are detected HERE, in code, and handed to the model as a list
# it must cover. The model still decides everything else — what the columns
# are, what the table is called, which line is a total. It no longer decides
# whether a run of label/amount lines under a heading is a table, because that
# question has an arithmetic answer.
#
# Deliberately NOT dictating the columns: an invoice's line-item block also
# matches "heading, then rows", and it is a FIVE-column table. Naming it as a
# section is harmless — the model already tables it correctly — but telling it
# the columns were [Description, Amount] would break it.

_AMOUNT_LINE = re.compile(
    r"^(?P<label>.{2,70}?)\s+\(?[-$£€₹¥]?\s?\d[\d,]*(?:\.\d+)?\)?$")

_MIN_SECTION_ROWS = 3


_STOPWORDS = {"the", "and", "of", "a", "an", "s"}


def _words(text):
    return {w for w in re.findall(r"[a-z0-9]+", str(text or "").lower())
            if w not in _STOPWORDS}


def _is_section_total(label, heading):
    """Is this trailing line the section's own total rather than a data row?

    Two ways to be one, and the second exists because the first is not enough:

      "Total …", "Subtotal …", "Sum …"   — unambiguous, whatever follows.

      "Net …" or "Gross …" that shares a word with the heading — "Net Revenue"
      under REVENUE. The bare "starts with Net" test cannot be used on its own:
      a balance sheet's SHAREHOLDERS' EQUITY section has "Net Income YTD Q1" as
      a genuine DATA row, and stripping it would delete a row gold expects.
      Sharing a word with the heading is what separates the two.
    """
    lab = str(label or "").strip().lower()
    if re.match(r"^(total|subtotal|sub-total|sum)\b", lab):
        return True
    if re.match(r"^(net|gross)\b", lab):
        return bool(_words(label) & _words(heading))
    return False


def _split_total(labels, heading):
    """(data_rows, totals) — cut at the FIRST line that is this section's own
    total. Everything before it is data; everything from it on is totals.

    Scanning FORWARD is what makes both ends work, and neither backward rule
    did. "Strip while the last line is a total" stops one line early, because a
    statement prints its own aggregate straight after a section's total —
    "Total COGS" then "GROSS PROFIT" — and that aggregate is not total-worded.
    "Cut at the LAST total line" over-corrects and keeps "Total Non-Current
    Assets" as a row because "TOTAL ASSETS" follows it.

    Forward, the first total ends the section by definition, and everything
    after it lands on the totals side. It also protects a genuine data row that
    merely reads like an aggregate: a balance sheet's equity section lists
    "Net Income YTD Q1" BEFORE "Total Equity", so the cut falls after it.
    """
    for i, lab in enumerate(labels):
        if _is_section_total(lab, heading):
            return list(labels[:i]), list(labels[i:])
    return list(labels), []


def detect_amount_sections(doc_text_pages):
    """[{heading, rows, labels}] for every heading followed by >= 3 lines that
    each end in an amount. [] for a document with no such shape — most of them.
    """
    lines = [l.strip() for t in (doc_text_pages or [])
             for l in str(t or "").split("\n") if l.strip()]
    out, i = [], 0
    while i < len(lines):
        if not _AMOUNT_LINE.match(lines[i]):
            i += 1
            continue
        j = i
        while j < len(lines) and _AMOUNT_LINE.match(lines[j]):
            j += 1
        if j - i >= _MIN_SECTION_ROWS and i > 0:
            heading = lines[i - 1]
            # A line carrying its own value ("SSN: ***-**-3317", "PO Number:
            # PO-2024-0018") is a data line that happens to sit above a run —
            # the top block of a payslip or a PO, not a section heading. Taking
            # it as one would turn a document's header fields into a table.
            if (not _AMOUNT_LINE.match(heading) and len(heading) <= 70
                    and not re.search(r":\s*\S", heading)):
                labels = [_AMOUNT_LINE.match(lines[k]).group("label").strip()
                          for k in range(i, j)]
                data, totals = _split_total(labels, heading)
                # The 3-line minimum counts the section's lines INCLUDING its
                # total (policy P7). What has to be a table is the DATA, and
                # two rows is the smallest real one — a balance sheet's
                # long-term liabilities and an income statement's revenue are
                # both two rows plus a total. A heading with one data line and
                # a pile of statement aggregates under it (an income
                # statement's OTHER INCOME) is not a table.
                if len(data) >= 2:
                    out.append({"heading": heading, "rows": len(data),
                                "labels": data, "totals": totals})
        i = max(j, i + 1)
    return out


def _sections_block(sections):
    """The MUST-cover list appended to the inference prompt."""
    if not sections:
        return ""
    p = ["",
         "SECTIONS DETECTED IN THIS DOCUMENT (read from its text — this is not "
         "a suggestion). Each heading below is followed by repeating "
         "label/amount rows, so each MUST appear in \"tables\", never as a list "
         "of separate fields:"]
    for sec in sections:
        shown = ", ".join(sec["labels"]) or "(none)"
        line = f'  - "{sec["heading"]}" — table rows: {shown}'
        if sec["totals"]:
            line += f'   |   section total (goes in "totals", NOT a row): ' \
                    + ", ".join(sec["totals"])
        p.append(line)
    p.append("The rows are listed for you: the section's own total has already "
             "been separated out above, so a table's row_count is exactly the "
             "number of rows named on its line. Do not add the total back in "
             "as a row.")
    p.append("")
    return "\n".join(p)


def infer_template(orchestrator, doc_text_pages, page_images, filename="",
                   doc_type_hint=""):
    """One LLM call. Returns the inferred template dict, or None on failure.

    `doc_type_hint` selects the CANONICAL VOCABULARY offered to the model
    (engine/vocabulary.py). It comes from keyword pre-screening, costs no
    LLM call, and is only a hint: the model still decides `document_type`
    itself, and a wrong hint costs nothing but an unused name list.
    """
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
        "   But a REPEATING group of similar rows is a table (item 4), not "
        "a list of fields — do not list its rows here.\n"
        "4. tables — every REPEATING group of rows. For each: a name, its "
        "column headings in left-to-right order, and how many rows it has.\n"
        "   A TABLE DOES NOT NEED A PRINTED HEADING ROW. This is the most "
        "common thing to get wrong. Wherever a heading is followed by three "
        "or more consecutive lines that each pair a name with an amount, "
        "that is a table — whether or not the document prints a "
        "'Description  Amount' line above it. Name the table after its "
        "heading and give it the columns [\"Description\", \"Amount\"].\n"
        "   Worked example — this SHAPE, whatever the document calls it:\n"
        "       <HEADING>\n"
        "       <name>                <amount>\n"
        "       <name>                <amount>\n"
        "       <name>                <amount>\n"
        "       Total <heading>       <amount>\n"
        "   is ONE table named after <HEADING>, with columns "
        "[\"Description\", \"Amount\"] and row_count 3 — NOT three "
        "separate fields. The closing 'Total …' line is a TOTAL (item 5), "
        "not a row of the table.\n"
        "   The heading can be anything a document groups amounts under: "
        "CURRENT ASSETS, OPERATING EXPENSES, REVENUE, COST OF GOODS SOLD, "
        "Earnings, Deductions, Fees. The SHAPE decides, not the wording — "
        "apply this to every document, not to one kind of statement.\n"
        "   COUNT THE SECTION'S LINES INCLUDING ITS CLOSING TOTAL. A "
        "heading with two named amounts and a Total under them is THREE "
        "lines: a table of 2 rows, plus that total. A heading with only "
        "one or two lines and NO total is too short to be a table — "
        "leave those as fields.\n"
        "   Every such heading gets its OWN table, named after that "
        "heading. A statement with five headings of this kind has FIVE "
        "tables; one with three has THREE. Never merge them into one "
        "table, and never return none. This applies to EVERY document "
        "that groups amounts under headings — assets and liabilities, "
        "revenue and expenses, earnings and deductions — not to one kind "
        "of statement.\n"
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
        "- NOTHING APPEARS TWICE. Every value belongs to exactly ONE of "
        "fields, tables or totals. If a line is a row of a table in "
        "item 4, it must NOT also be a field in item 3; if it is a "
        "section total in item 5, it is not a table row either. A "
        "value listed in two places is written into the sheet twice.\n"
        "- If the document has no repeating rows, return \"tables\": [].\n"
        + _sections_block(detect_amount_sections(doc_text_pages))
        + vocabulary_block(doc_type_hint)
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

    n_named = (len(inferred["fields"]) + len(inferred["totals"])
               + sum(len(t["columns"]) for t in inferred["tables"]))
    n_novel = len(inferred.get("novel_fields") or [])
    if doc_type_hint:
        _log("VOCAB", f"{filename}: {n_named - n_novel}/{n_named} labels from "
                      f"the {doc_type_hint} vocabulary, {n_novel} outside it")
    _log("INFER", f"{filename}: {inferred['document_type']} — "
                  f"{len(inferred['fields'])} fields, "
                  f"{len(inferred['tables'])} table(s) "
                  f"({', '.join(str(len(t['columns'])) + 'col' for t in inferred['tables']) or 'none'}), "
                  f"{len(inferred['totals'])} total(s)")
    return inferred


def _labels(seq, novel=None):
    """Clean a list of label strings: strings only, trimmed, deduped, ordered.

    A label the model prefixed "other: " fell outside the canonical vocabulary.
    The prefix is stripped — a spreadsheet should read "Bank Address", not
    "other: Bank Address" — and the name is recorded in `novel`, because the
    share of values needing it is how we know whether the vocabulary is wide
    enough.
    """
    out, seen = [], set()
    for x in seq or []:
        if isinstance(x, dict):
            x = x.get("label") or x.get("name") or ""
        s = re.sub(r"\s+", " ", str(x or "")).strip()
        s, was_other = split_other(s)
        s = s.strip().strip(":").strip()
        if not s or len(s) > 60:
            continue
        k = s.casefold()
        if k in seen:
            continue
        seen.add(k)
        out.append(s)
        if was_other and novel is not None:
            novel.append(s)
    return out


def _clean(parsed):
    novel = []
    tables = []
    for t in parsed.get("tables") or []:
        if not isinstance(t, dict):
            continue
        cols = _labels(t.get("columns"), novel)
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
        "fields": _labels(parsed.get("fields"), novel),
        "tables": tables,
        "totals": _labels(parsed.get("totals"), novel),
        "novel_fields": novel,
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
