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
from micr import field_role, find_micr_line, parse_micr
from text_layer import (check_placement, column_bands, find_line,
                        record_span, source_occurrences)


# ── text normalisation (grounding) ───────────────────────────────────────────

_DASHES = {"–": "-", "—": "-", "−": "-", "‐": "-", "‑": "-"}


def _flag(ref, value, reason) -> dict:
    """One entry in `validation.flagged_fields`.

    ONE SHAPE, because there were three. This path appended plain strings
    (`"Closing Balance: not found in document text"`), the image path appended
    `{ref, value, issue}`, and the legacy path `{ref, value, reason}` — while
    both consumers assumed the last of those. The job runner built its
    `validation_warnings` summary with `f['ref']`, which raises TypeError on a
    string, and that exception was caught by the per-document handler: ANY
    document with a flagged field failed to save, with the failure counted and
    the cause visible only on stdout. The review panel, reading `f.reason` off
    a string, rendered a row of blanks.

    `ref` is the human-facing identifier — a row label, or `Table[3].Amount`
    for a table cell. Cell addresses live in `confidence_map`, which is keyed
    by them.
    """
    return {"ref": str(ref), "value": "" if value is None else str(value),
            "reason": str(reason or "")}


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


def table_headers(t):
    """The keys the model answers a table with, whichever way it runs.

    A transposed table's headings live down its first COLUMN, so its "columns"
    for answering purposes are its field names — one answer object per record
    (per document column) instead of per row. Everything downstream then treats
    both orientations identically; only the writer has to transpose.
    """
    if t.get("orientation") == "columns":
        return [f["header"] for f in t.get("fields") or []]
    return [c.get("key") or c["header"] for c in t.get("columns") or []]


def _table_map(t):
    """The geometry the writer needs to place a table's answers."""
    m = {"name": t["name"], "header_row": t.get("header_row", t.get("start_row", 0)),
         "start_row": t["start_row"], "end_row": t["end_row"],
         "columns": t.get("columns") or []}
    if t.get("orientation") == "columns":
        m.update({"orientation": "columns", "header_col": t["header_col"],
                  "start_col": t["start_col"], "end_col": t["end_col"],
                  "fields": t.get("fields") or []})
    return m


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
        # The label is the slot's ADDRESS, not its answer. Saying only
        # 'row label "Net Revenue"' let the model read the label as the thing
        # to output, and it answered every slot with its own label — read off
        # the right line, so grounding passed and the sheet said
        # "Net Revenue | Net Revenue".
        p.append("FIELD SLOTS — each is one cell of the sheet. The label is the "
                 "slot's ADDRESS, not its answer: find that row in the document "
                 "and give the VALUE printed on it. Answer every slot by its id:")
        for f in fields:
            addr = f'the value on the row labelled "{f["row_label"]}"'
            if f["section"]:
                addr = f'in section "{f["section"]}", ' + addr
            p.append(f'  {f["slot_id"]}: {addr}')
        p.append("")

    for t in tables:
        cols = " | ".join(table_headers(t))
        if t.get("orientation") == "columns":
            # A transposed table is answered exactly like any other — one object
            # per record — so the model never has to think in columns. Only the
            # writer transposes.
            p.append(f'TABLE "{t["name"]}" — one object per record present in the document.')
            if t.get("section"):
                p.append(f'  section: "{t["section"]}"')
            p.append(f"  columns (use EXACTLY these keys): {cols}")
            p.append(f'  the sheet has room for {t["end_col"] - t["start_col"] + 1} '
                     f"records; return as many as the document actually has, not "
                     f"that number.")
            p.append("")
            continue
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
        keys = ", ".join(f'"{h}": "..."' for h in table_headers(t0)[:3])
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
    # SELECTION FIELDS. Where the document marks which option is chosen — a
    # printed [X], or a form widget whose state was written into the text —
    # this is read correctly. Where NOTHING marks it, every option is equally
    # printed and equally groundable, so any answer is a guess that passes
    # every check the pipeline has. An invented entity type is worse than a
    # blank one: these are the fields that decide treatment.
    p.append('- A slot whose line offers SEVERAL OPTIONS and marks none of '
             'them as chosen has no answer: give "". Do not pick the first, '
             'the most likely, or the most common. Only a marked option '
             '([X], a tick, "Yes"/"No" written in) is an answer.')
    p.append("- Give the value only, not the label. For a slot labelled "
             '"Closing Balance" on the line "Closing Balance: 125,357.26", '
             'answer "125,357.26" — NOT "Closing Balance: 125,357.26", and '
             'NEVER "Closing Balance". Repeating the label back is not an '
             'answer; if the line has no value, give "".')
    return "\n".join(p)


# ══════════════════════════════════════════════════════════════════════════════
# GROUNDING
# ══════════════════════════════════════════════════════════════════════════════

_EMAIL = re.compile(r"[^\s@]+@[^\s@]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}")


def _single_datum(value, label):
    """One cell, one piece of information.

    A value carrying an email, a phone number or a pipe alongside something
    else is two data crammed into one cell — 'Mr. Robert Chen –
    rchen@apex.com' where the slot asked for a contact name. It reads as
    plausible, which is exactly why it must not be called high confidence.
    A slot that ASKS for an email or a phone may of course contain one.
    """
    v = str(value or "")
    lab = str(label or "").casefold()
    if "|" in v:
        return False
    if _EMAIL.search(v) and not any(w in lab for w in ("email", "e-mail", "mail")):
        return False
    if _PHONE.search(v) and not any(w in lab for w in ("phone", "tel", "mobile",
                                                       "fax", "contact no")):
        return False
    return True


# NOTE: a rule requiring the value to be the whole span, or set off in it by a
# separator, was tried and rejected. It was meant to catch a value truncated at
# a line break ("NEXUS GLOBAL TRADING" where the letterhead continues "LLC").
# It demoted 250 correct cells to reach 98.4% — worse than the 99.5% without
# it — because a correct value read off a line ("First National Bank of New
# York" from "...BANK OF NEW YORK ACCOUNT STATEMENT") is structurally identical
# to a truncated one. Nothing in the span distinguishes them.


# ── the confidence vocabulary ────────────────────────────────────────────────
#
# Defined once in app/core/confidence.py — the engine, the API, the exporters
# and the UI all say the same words. In short:
#
#   HIGH        grounded AND the slot's label was authored by the USER
#   GROUNDED    grounded, but the slot's label was written by the model itself,
#               so nothing independent says the value BELONGS there
#   UNVERIFIED  no text layer existed to check any span against
#   LOW         checked and failed
#
# Read that module's docstring before changing any of this.
from app.core.confidence import (  # noqa: E402
    CONFIDENT_LEVELS, GROUNDED, HIGH, LOW, MEDIUM, UNVERIFIED,
)


def is_label_echo(value, row_label) -> bool:
    """The answer is the slot's own label rather than a value.

    "Net Revenue" for the slot labelled "Net Revenue", read off the line
    "Net Revenue $1,951,400". Grounding cannot catch this: the label really is
    in the document, and really is inside the span the value was read from, so
    every check passes and the sheet ends up reading "Net Revenue | Net
    Revenue". It is a distinct failure from a wrong value — nothing was
    extracted at all — and it is treated as no answer rather than written.
    """
    v, l = _flat(value), _flat(row_label)
    if not v or not l:
        return False
    if v == l:
        return True
    # "Total COGS:" / "Total COGS -" — the label with trailing punctuation.
    return v.rstrip(" :-–—") == l.rstrip(" :-–—")


def confidence_for(value, source, label, grounded, inferred=False):
    """(level, reason).

    `inferred=True` when the template was designed by inference rather than by
    the user — the value can then be GROUNDED at best, never HIGH, because
    there is no user-authored slot for it to be the right answer to.
    """
    if not grounded:
        return LOW, "value could not be grounded in the document"
    if not _single_datum(value, label):
        return LOW, "cell carries more than one piece of information"
    return (GROUNDED if inferred else HIGH), ""


def verify_span(value, source, page, page_texts, record=""):
    """(grounded, reason). An empty answer needs no grounding.

    `record` is the span of document lines this row actually occupies, when
    geometry could tell us. A value the model did not manage to quote — it
    quoted the first line of a four-line W-2 record and the value is on the
    third — is checked against that instead, which is a statement about the
    same record rather than about the document at large. The record span
    stops at the next row's line, so this can never reach into a neighbour.
    """
    if value is None or str(value).strip() == "":
        return True, "empty"
    src = _flat(source)
    if not src and not _flat(record):
        return False, "no source span given"
    if not src:
        source, src = record, _flat(record)

    haystacks = [_flat(t) for t in page_texts]
    try:
        pi = int(page) - 1
    except (TypeError, ValueError):
        pi = -1
    ordered = ([haystacks[pi]] if 0 <= pi < len(haystacks) else []) + haystacks
    if not any(src in h for h in ordered if h):
        return False, "source span not found in document"

    # the value must sit inside the span it claims to come from — or, failing
    # that, inside the record that span belongs to
    for span in (source, record):
        if not str(span or "").strip():
            continue
        flat = _flat(span)
        val = _flat(value)
        if val and val in flat:
            return True, ""
        dv, ds = _digits(value), _digits(span)
        if dv and dv in ds:
            return True, ""
        n = _num(value)
        if n is not None:
            for tok in re.findall(r"\(?-?[\d,]*\.?\d+\)?", str(span)):
                t = _num(tok)
                if t is not None and round(abs(t), 2) == round(abs(n), 2):
                    return True, ""
    return False, "value not found inside its own source span"


# ══════════════════════════════════════════════════════════════════════════════
# RUN
# ══════════════════════════════════════════════════════════════════════════════

def run_slot_extraction(orchestrator, file_path, template_data, binding_map,
                        page_images, doc_text, doc_text_pages, file_type,
                        default_doc_type, start, page_lines=None):
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

    # Was this template designed by inference rather than by the user? If so no
    # cell can be HIGH — see the confidence vocabulary above.
    inferred = bool((template_data or {}).get("inferred"))
    confident = GROUNDED if inferred else HIGH
    if inferred:
        _log("SLOT", f"{file_path.name}: inferred template — cells can be "
                     f"'{GROUNDED}' at best, never '{HIGH}'")

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
    misplaced = 0
    dropped = 0
    all_lines = [ln for pg in (page_lines or []) for ln in (pg or [])]

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
            if is_label_echo(value, slot["row_label"]):
                notes.append(f'{slot["row_label"]}: the model returned the '
                             f"slot's own label instead of a value — dropped")
                continue
            ok, why = verify_span(value, source, page, pages)
            lvl, reason = confidence_for(value, source, slot["row_label"], ok,
                                         inferred=inferred)
            extracted_fields[slot["ref"]] = value
            conf_map[slot["ref"]] = lvl
            if not ok:
                ungrounded += 1
            if lvl not in CONFIDENT_LEVELS:
                flagged.append(_flag(slot["row_label"], value, reason or why))

    # ── MICR decomposition ──
    # A cheque's routing and account numbers are printed only inside the MICR
    # band, and the model returns that band whole: asked for a routing number
    # it answers "A021000021A C7743882201C 001847D". No prompt fixes that,
    # because the band is not prose — it is E-13B, with a sentinel character
    # delimiting each field, so it is PARSED instead (engine/micr.py). The
    # routing number is checked against the ABA checksum before it is used.
    #
    # Only slots the model left EMPTY are filled, so a real answer is never
    # overwritten, and each derived value is grounded against the band itself —
    # the digits are verbatim on the page — by the same rule as any other.
    micr_line = find_micr_line(pages)
    if micr_line:
        parts = parse_micr(micr_line)
        for slot in slots["fields"]:
            if slot["ref"] in extracted_fields:
                continue
            role = field_role(slot["row_label"])
            value = parts.get(f"{role}_number") if role else None
            if not value:
                continue
            ok, why = verify_span(value, micr_line, 0, pages)
            lvl, reason = confidence_for(value, micr_line, slot["row_label"], ok,
                                         inferred=inferred)
            extracted_fields[slot["ref"]] = value
            conf_map[slot["ref"]] = lvl
            if not ok:
                ungrounded += 1
            if lvl not in CONFIDENT_LEVELS:
                flagged.append(_flag(slot["row_label"], value, reason or why))
        if parts:
            _log("MICR", f"{file_path.name}: band decomposed -> "
                         + ", ".join(sorted(parts)))

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
            headers = table_headers(t)
            # PLACEMENT (D6). Grounding says the value is in the document; it
            # cannot say the value belongs in THIS column, because a flattened
            # line carries no columns. The document's own heading line does:
            # where it prints a heading this band also has, that heading's
            # x-span is the column, and a value whose span sits under a
            # DIFFERENT column is misplaced however well it grounds. A Debit
            # written into the Credit column quotes the same source line and
            # passes every other check there is.
            #
            # The check is opportunistic on purpose. A band whose headings the
            # document does not print gets no bands and no verdict — calling a
            # placement wrong on a guessed column would demote correct values,
            # which is the failure this is meant to prevent.
            bands = column_bands(all_lines, headers) if all_lines else {}
            if bands:
                _log("PLACE", f'{t["name"]}: column bands read from the '
                              f'document for {sorted(bands)}')
            # ROW IDENTITY IS POSITIONAL, NOT TEXTUAL.
            #
            # This used to key a row on the TEXT of its source span and drop
            # every later row quoting the same words. That is only correct if
            # the document prints those words once. Two rows legitimately
            # quoting one line is ordinary — a group header, a repeated column
            # heading, a document that simply prints the same line twice — and
            # in a file holding twenty invoices the identifying lines repeat by
            # construction: measured on five merged invoices, 9 lines repeat
            # and 33 rows become deletable; five payslips, 11 and 43. It scales
            # linearly with the number of documents in the file, and the whole
            # point of the product is putting many documents in one file.
            #
            # A row is now identified by WHICH document line it was read from.
            # Each row claims one occurrence; a row that can claim a free
            # occurrence is a real row however many others quote the same text.
            # Only a row claiming a line every copy of which is already spoken
            # for is a duplicate — which is exactly the fabricated-row case the
            # dedup existed for, stated precisely instead of approximately.
            #
            # Without geometry (the image path, or a caller that passes no
            # page_lines) identity falls back to the source PLUS the row's own
            # values, so two different rows quoting one line still both survive.
            # That is weaker — it cannot catch a hallucinated variant of a real
            # row — and it is why `page_lines` is worth threading through.
            #
            # CLAIMING IS A PASS OF ITS OWN, because a record's extent is only
            # known once the NEXT record has claimed its line. A row's cells
            # are verified against the line the model quoted and, failing that,
            # against the lines between this row's line and the next one's —
            # which is what a record spanning several printed lines needs, and
            # cannot reach into a neighbouring record.
            seen_rows, claimed_lines, rows_out = set(), set(), []
            claims = []
            for r in raw:
                if not isinstance(r, dict):
                    continue
                cells = r.get("cells") if isinstance(r.get("cells"), dict) else r
                source, page = r.get("source", ""), r.get("page", 0)
                key = _flat(source)
                occurrences = (source_occurrences(all_lines, source)
                               if (all_lines and key) else [])
                free = None
                if occurrences:
                    free = next((i for i in occurrences
                                 if i not in claimed_lines), None)
                    duplicate = free is None
                    if free is not None:
                        claimed_lines.add(free)
                else:
                    ident = (key, tuple(sorted(
                        (h, str(cells.get(h, "") or "")) for h in headers)))
                    duplicate = bool(key) and ident in seen_rows
                    seen_rows.add(ident)
                claims.append((cells, source, page, free, duplicate))

            later = sorted(i for _c, _s, _p, i, _d in claims if i is not None)
            for cells, source, page, line_no, duplicate in claims:
                record = ""
                if line_no is not None and all_lines:
                    nxt = next((i for i in later if i > line_no), None)
                    record = record_span(all_lines, line_no, nxt)
                if duplicate:
                    # VISIBLY. A dropped row appeared only in validation_notes:
                    # not flagged, not in needs_review, not in the confidence
                    # map, invisible in the app and in the export. A silent
                    # deletion is worse than a duplicate row, because nothing
                    # tells the reader to go and look.
                    dropped += 1
                    shown = " | ".join(
                        f"{h}={cells.get(h)}" for h in headers
                        if str(cells.get(h, "") or "").strip()) or str(source)[:60]
                    flagged.append(_flag(
                        f'{t["name"]}[dropped]', shown,
                        "row dropped: it was read from a document line that "
                        "another row already used, and the document prints "
                        "that line only once"))
                    notes.append(
                        f'{t["name"]}: dropped a row claiming an already-used '
                        f"source line: {str(source)[:60]!r}")
                    continue
                row, row_conf = {}, confident
                for h in headers:
                    v = cells.get(h, "")
                    if v is None:
                        v = ""
                    if str(v).strip() == "" or is_label_echo(v, h):
                        row[h] = ""
                        continue
                    ok, why = verify_span(v, source, page, pages, record)
                    lvl, reason = confidence_for(v, source, h, ok,
                                                 inferred=inferred)
                    row[h] = v
                    if not ok:
                        ungrounded += 1
                    if lvl not in CONFIDENT_LEVELS:
                        row_conf = LOW
                        flagged.append(_flag(
                            f'{t["name"]}[{len(rows_out)}].{h}', v,
                            reason or why))
                if bands and t.get("orientation") != "columns":
                    line = (all_lines[line_no] if line_no is not None
                            else find_line(all_lines, source))
                    for bad_key, why in check_placement(
                            row, t.get("columns") or [], line, bands):
                        row_conf = LOW
                        ungrounded += 1
                        misplaced += 1
                        flagged.append(_flag(
                            f'{t["name"]}[{len(rows_out)}].{bad_key}',
                            row.get(bad_key, ""), why))
                if any(str(v).strip() for v in row.values()):
                    row["_confidence"] = row_conf
                    rows_out.append(row)
            tables_out[t["name"]] = rows_out
            row_counts[t["name"]] = len(rows_out)

    total_cells = len(extracted_fields) + sum(
        len([v for k, v in r.items() if not k.startswith("_") and str(v).strip()])
        for rows in tables_out.values() for r in rows)
    if dropped:
        notes.append(f"{dropped} table row(s) were dropped as duplicates — see "
                     f"the flagged rows")
    if misplaced:
        notes.append(f"{misplaced} table value(s) sit under a different column "
                     f"in the document than the slot they were written to")
    _log("SLOT", f"filled {len(extracted_fields)}/{len(slots['fields'])} field slots, "
                 f"table rows {row_counts}, {ungrounded} ungrounded value(s), "
                 f"{misplaced} misplaced, {dropped} dropped")

    # DOCUMENT-LEVEL GATE — a document where more than 30% of cells are low
    # confidence is sent for manual review as a whole, rather than handing the
    # user a wall of per-cell warnings to work through.
    low_cells = sum(1 for v in conf_map.values() if v == LOW)
    low_cells += sum(1 for rows in tables_out.values() for r in rows
                     if r.get("_confidence") == LOW)
    graded = len(conf_map) + sum(len(r) for r in tables_out.values())
    low_ratio = (low_cells / graded) if graded else 0.0
    review_gate = low_ratio > 0.30
    if review_gate:
        notes.append(f"{low_cells} of {graded} cells ({low_ratio:.0%}) are low "
                     f"confidence — this document needs manual review")

    # "medium" at DOCUMENT level is a genuine mixed state — mostly grounded, one
    # or two values not — not a claim about a check that never ran. That is
    # UNVERIFIED, below.
    overall = confident if ungrounded == 0 else (MEDIUM if ungrounded <= 2 else LOW)
    if review_gate:
        overall = LOW
    if file_type in ("scanned_pdf", "image") or len(doc_text.strip()) < 50:
        # No text layer to check any span against. Every cell here was reported
        # as "medium" before Phase 8, which implied a verification that never
        # happened; UNVERIFIED says what is actually true.
        overall = UNVERIFIED
        notes.append("No text layer — spans could not be verified against the "
                     "document; values are unverified, not low quality")
        conf_map = {k: UNVERIFIED for k in conf_map}
    needs_review = (bool(ungrounded) or bool(unanswered) or review_gate
                    or bool(dropped))

    r = DocumentExtractionResult(filename=file_path.name)
    r.document_type = default_doc_type
    r.success = True
    r.processing_time_ms = int((time.time() - start) * 1000)

    kv = {}
    for ref, v in extracted_fields.items():
        slot = next((f for f in slots["fields"] if f["ref"] == ref), None)
        kv[slot["row_label"] if slot else ref] = {
            "value": v, "confidence": conf_map.get(ref, confident), "ref": ref}

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
            "tables": [_table_map(t) for t in slots["tables"]],
        },
        "validation": {
            "flagged_count": len(flagged),
            "flagged_fields": flagged,
            "confidence_map": conf_map,
            "ungrounded_count": ungrounded,
            "misplaced_count": misplaced,
            "dropped_row_count": dropped,
            "low_confidence_cells": low_cells,
            "graded_cells": graded,
            "low_confidence_ratio": round(low_ratio, 4),
            "document_needs_review": review_gate,
            "grounded_count": max(0, total_cells - ungrounded),
        },
        "validation_notes": notes,
        "needs_review": needs_review,
        "template_type": "slot",
        "template_regions": {"primary_mode": "slot"},
        # Phase 3 — when the template was inferred rather than chosen, the grid
        # travels with the result so export can write a proper sheet for it and
        # the UI can offer "save this as a template".
        "inferred_template": (template_data or {}).get("inferred"),
        "inferred_grid": ((template_data or {}).get("layout")
                          if (template_data or {}).get("inferred") else None),
        "shape_signature": (template_data or {}).get("shape_signature"),
        "raw_llm_responses": [getattr(resp, "raw_text", "")] if resp else [],
    }
    for name, rows in tables_out.items():
        ed[f"{name}_rows"] = rows
    r.extracted_data = ed
    r.extraction_response = resp
    _log("RESULT", f"slot-directed: {len(kv)} fields, "
                   f"{sum(len(v) for v in tables_out.values())} table rows, {overall}")
    return [r]
