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

from extractor import _llm_json, _log
from log_safety import doc_ref
from micr import field_role, find_micr_line, parse_micr
from validators import FAIL, UNREADABLE, CheckContext, run_checks
from total_row_validators import split_duplicate_totals
from text_layer import (canonical_value, check_placement, column_bands,
                        find_line, flatten_pages, line_page, matches_loosely,
                        overprinted_value, page_for_prompt_page, record_span,
                        source_occurrences, unprinted_headers)


# ── text normalisation (grounding) ───────────────────────────────────────────

_DASHES = {"–": "-", "—": "-", "−": "-", "‐": "-", "‑": "-", "﹣": "-", "－": "-"}
#: Run E, E11: the spaces a PDF prints that are not U+0020
_SPACES = {" ": " ", " ": " ", " ": " ", " ": " ", " ": " "}


def _unify(s) -> str:
    """Every minus and dash variant as `-`, every non-breaking or thin space
    as a space — BEFORE numbers are read or compared. A typographic minus
    (U+2212) is how many statements print a negative, and `−45.00` failed to
    ground against an answer of `-45.00`."""
    t = str(s or "")
    for k, v in _DASHES.items():
        t = t.replace(k, v)
    for k, v in _SPACES.items():
        t = t.replace(k, v)
    return t


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
    return re.sub(r"\s+", " ", _unify(s)).strip().casefold()


# ── printed numbers ──────────────────────────────────────────────────────────
#
# A number grounds only as a WHOLE printed token (see verify_span). That needs
# the tokens, and the text layer does not always hand them over whole: on the
# Berkshire earnings release pdfplumber splits `19,694` into the words `19,6`
# and `94`, and `9.13` into `9`, `.`, `13`. The word boxes touch (gap within
# 0.1pt), but the flattened text puts a space between them like any other
# words, so from the text alone a split number and two columns look the same.
#
# The rejoin therefore rests on the NUMBER, not on the spacing. A piece joins
# the next only when it is visibly incomplete:
#
#   `19,6` + `94`        a final thousands group of fewer than 3 digits, which
#                        the next piece completes to exactly 3
#   `9` + ` . ` + `13`   a decimal point standing alone as its own word
#
# and only across exactly one space. A complete number never absorbs anything,
# so `$ 848 $ 9,020` is two numbers and `18 000` is two numbers: nothing in `18`
# says it was cut short. The same argument as text_layer._shortfall, which
# makes the same decision across a line break.

_NUM_PIECE = re.compile(
    r"(?<![\d.,])"                 # not the tail of a longer number
    r"(?P<open>\()?"
    r"(?P<sign>(?<!\w)-)?"         # a minus, unless it joins two words (INV-2024)
    r"(?:(?P<cur>[$£€])\s?)?"
    r"(?P<sign2>-)?"
    r"(?P<body>\d[\d,]*(?:\.\d+)?)"
    r"(?P<close>\))?"
    r"(?![\d])")


def _piece(m):
    return {"open": bool(m.group("open")), "sign": bool(m.group("sign") or m.group("sign2")),
            "cur": m.group("cur") or "", "body": m.group("body").rstrip(","),
            "close": bool(m.group("close")), "start": m.start(), "end": m.end()}


def _joins(left, right, gap):
    if left["close"] or right["open"] or right["sign"] or right["cur"]:
        return None
    lb, rb = left["body"], right["body"]
    if gap == " " and "," in lb and "." not in lb:
        last = lb.rsplit(",", 1)[1]
        lead = re.match(r"\d+", rb).group(0)
        if len(last) < 3 and len(last) + len(lead) == 3 and "," not in rb[:len(lead)]:
            return lb + rb
    if gap == " . " and "." not in lb and re.fullmatch(r"\d+", rb):
        return lb + "." + rb
    return None


def printed_numbers(text) -> list[str]:
    """Every number printed in `text`, split words rejoined, whitespace removed.

    `$ 19,6 94 $ 37,574` -> ['$19,694', '$37,574'].
    """
    text = _unify(text)
    pieces = [_piece(m) for m in _NUM_PIECE.finditer(text)]
    out = []
    for p in pieces:
        if out:
            joined = _joins(out[-1], p, text[out[-1]["end"]:p["start"]])
            if joined is not None:
                out[-1].update(body=joined, end=p["end"], close=p["close"])
                continue
        out.append(p)
    return [f"{'(' if p['open'] else ''}{'-' if p['sign'] else ''}{p['cur']}"
            f"{p['body']}{')' if p['close'] else ''}" for p in out]


def _number_key(s):
    """A printed number reduced to what it SAYS: sign, digits, decimal point.
    None when `s` is not purely a number in some notation."""
    t = re.sub(r"\s", "", _unify(s))
    # E11: the currency symbol before or after the figure, the sign either side
    m = re.fullmatch(r"(\()?(-)?([$£€])?(-)?(\d[\d,]*(?:\.\d+)?)([$£€])?(-)?(\))?", t)
    if not m or bool(m.group(1)) != bool(m.group(8)) or (m.group(3) and m.group(6)):
        return None
    neg = bool(m.group(1) or m.group(2) or m.group(4) or m.group(7))
    return ("-" if neg else "") + m.group(5).replace(",", "")


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


#: Run C, C7 — said to the model for a cheque read by OCR. Order differs by
#: cheque style, so the fields are named by their symbols and digit counts.
CHEQUE_BOTTOM_LINE = (
    "CHEQUE BOTTOM LINE (MICR): the line printed along the bottom edge holds "
    "three numbers. The ROUTING number is exactly 9 digits, between two "
    "transit symbols (⑆, often read as 'A' or ':'). The ACCOUNT number is the "
    "longer on-us field (usually 6-17 digits) ending with the on-us symbol "
    "(⑈, often read as 'C' or '\"'). The CHEQUE number is the short 3-6 digit "
    "group; it is also printed at the top right of the cheque. Business "
    "cheques print cheque number, routing, account in that order; personal "
    "cheques print routing, account, cheque number. Put each number only in "
    "its own slot - a 9-digit routing number never goes in the account or "
    "cheque-number slot.\n")


def cheque_bottom_line_hint(doc_type, slots, page_origins, file_type="") -> str:
    """The bottom-line instruction, for a cheque whose page was read by OCR
    and whose template asks for a routing, account or cheque number. Empty
    otherwise, so every other prompt — and every recorded answer to it — is
    byte-identical to what it was."""
    from validators import family_of
    if family_of(doc_type) != "cheque":
        return ""
    scanned = any(str(o) == "ocr" for o in (page_origins or {}).values()) \
        or str(file_type or "").lower() in ("image", "scanned_pdf")
    if not scanned:
        return ""
    from micr import field_role
    from cheque_validators import is_cheque_number_label
    if not any(field_role(f["row_label"]) or is_cheque_number_label(f["row_label"])
               for f in slots.get("fields") or []):
        return ""
    return CHEQUE_BOTTOM_LINE


#: free-text table columns, the ones a model fills by copying a neighbour
_FREE_TEXT_COL = re.compile(
    r"\b(?:description|desc|memo|notes?|reference|ref|comments?|details?|"
    r"narrative|particulars|payee|remarks?)\b", re.I)

COLUMN_COPY_RULE = (
    "TABLE COLUMNS: never copy a value from one column into another. A column "
    "the document prints nothing for in a row is left EMPTY (\"\") in that "
    "row, even when a neighbouring column holds text that could fit it.\n")


def column_copy_hint(slots) -> str:
    """Run E, E9: the no-copying rule, for a template whose table has TWO OR
    MORE free-text columns (`Description` and `Memo`) — the shape in which a
    model filled Memo with each row's Description. Empty for every other
    template, so their prompts and recorded answers are byte-identical."""
    for t in slots.get("tables") or []:
        heads = [h for h in table_headers(t) if _FREE_TEXT_COL.search(str(h or ""))]
        if len(heads) >= 2:
            return COLUMN_COPY_RULE
    return ""


def _same_column_name(a, b) -> bool:
    """Two columns the author drew separately are the same column only when
    their headings agree once qualifiers are dropped (`Item Description` /
    `Description`). A synonym group does not make them one: a template that
    draws both `Description` and `Memo` means two things."""
    import aliases as AL
    na, nb = AL._norm(a), AL._norm(b)
    if na == nb:
        return True
    core = lambda s: " ".join(w for w in s.split() if w not in AL._QUALIFIERS)  # noqa: E731
    return bool(core(na)) and core(na) == core(nb)


def copied_columns(rows, keys, printed=None) -> list:
    """Run E, E9: [(copy, source)] for two text columns holding the same
    value on every row either fills, over two or more rows — one is a copy of
    the other, not a reading. The SOURCE is the column whose own heading the
    document prints (`DESCRIPTION`, not `MEMO`); when that does not decide,
    the later column is the copy. Amount columns are left alone: a
    debit-only statement legitimately repeats an amount."""
    from amounts import parse_amount
    printed = printed or (lambda _h: False)

    def _txt(r, k):
        return str(r.get(k, "") or "").strip()

    out, taken = [], set()
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            if a in taken or b in taken or _same_column_name(a, b):
                continue
            filled = [r for r in rows if _txt(r, a) or _txt(r, b)]
            if not filled or any(_txt(r, a) != _txt(r, b) for r in filled):
                continue
            if all(parse_amount(_txt(r, a)).ok for r in filled):
                continue
            copy, src = b, a
            if printed(b) and not printed(a):
                copy, src = a, b
            # Two rows make a copy; ONE does when the page prints the source
            # column's heading and not the copy's (Batch 2, test_01: a
            # one-line PO whose Memo repeats its Description, no Memo printed).
            need = 1 if (printed(src) and not printed(copy)) else 2
            if len(filled) < need:
                continue
            out.append((copy, src))
            taken.add(copy)
    return out


def build_prompt(slots, page_texts, doc_type="", extra=""):
    """`extra` is appended after the document text: the form-field lane (B1)
    and the meaning-match guidance (B2). It is empty for a document that
    needs neither, so the prompt - and every cached answer to it - is
    byte-identical to what it was."""
    fields, tables = slots["fields"], slots["tables"]
    p = []
    p.append(f"Fill in a {doc_type or 'document'} spreadsheet from the document below.\n")

    p.append("=== DOCUMENT TEXT ===")
    for i, txt in enumerate(page_texts, 1):
        p.append(f"--- page {i} ---\n{txt or ''}")
    p.append("=== END DOCUMENT ===\n")
    if extra:
        p.append(extra)

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
        # `prompt_rows`: a header-only band reserves no rows (Run D) but is
        # described as it always was, so recorded answers stay valid.
        room = t.get("prompt_rows") or (t["end_row"] - t["start_row"] + 1)
        p.append(f'  the sheet has {room} blank rows for it; '
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


def _answer_value(ans) -> str:
    """The value of one slot answer, however the model shaped it."""
    if isinstance(ans, dict):
        return str(ans.get("value") or "").strip()
    return str(ans or "").strip()


def _table_rows_of(parsed, t, slots) -> list:
    """The model's rows for band `t` (the renamed-table tolerance included)."""
    import llm_contract as C
    raw = C._table_answer((parsed or {}).get("tables"), t, len(slots["tables"]))
    return [r for r in raw if isinstance(r, dict)] if isinstance(raw, list) else []


def _echoed_header(cells, headers) -> bool:
    """A row whose values are the band's own headings (a header line reprinted
    at the top of a later page, answered as data)."""
    heads = {str(h or "").strip().casefold() for h in headers if str(h or "").strip()}
    vals = [str(v or "").strip().casefold() for v in (cells or {}).values()
            if str(v or "").strip()]
    return len(vals) >= 2 and sum(1 for v in vals if v in heads) * 2 >= len(vals)


def page_at_a_time(ask, slots, pages, page_lines, page_images, nums, inventory,
                   doc_type):
    """(parsed, resp, {file page: why it failed}) for a long document.

    Fields: ONE call over the whole document. Tables: one call per PAGE that
    prints the band's headings, or continues it (the page after one that
    does, holding candidate rows of the band's kind), at most
    PAGE_CALL_CONCURRENCY at once. A page whose call fails is retried ALONE,
    once; a page that still fails is reported, and every other page's rows
    are kept — a failure on page 17 does not discard pages 1-16. A page that
    prints no part of a band is never asked for its rows, so a statement
    template run on a vendor list returns nothing for it rather than
    something invented."""
    import contextvars
    from concurrent.futures import ThreadPoolExecutor

    import llm_contract as C
    import source_inventory as SI

    want = {}                          # page index -> [band]
    for t in slots["tables"]:
        kind = SI.band_kind(t)
        prev = False
        for k, _n in enumerate(nums):
            lines = page_lines[k] if k < len(page_lines) else []
            rows_here = (inventory["pages"].get(nums[k]) or {}).get(
                f"{kind}_rows", 0) > 0
            # Asked only where the page prints the band's headings AND holds
            # a row of its kind, or directly continues a page that did.
            here = rows_here and SI.page_has_band(lines, t)
            cont = prev and rows_here
            # A MACHINE-READ page: OCR misreads dates and headings, so the
            # inventory cannot be trusted to say a page holds no rows. Any
            # such page carrying amounts is asked; the model is told a table
            # the page does not print is [].
            pg = inventory["pages"].get(nums[k]) or {}
            if pg.get("origin") in ("ocr", "pre_ocr") and len(pg.get("amounts") or []) >= 5:
                here = True
            if here or cont:
                want.setdefault(k, []).append(t)
            prev = here or cont
    # A band NO page was selected for is not skipped: the inventory may be
    # blind to it (an OCR misread, a layout it does not know), and skipping
    # would return no rows with nothing to say so. It is asked in one call
    # over the whole document, as before page-at-a-time existed.
    whole = [t for t in slots["tables"]
             if not any(t in bands for bands in want.values())]
    fields_parsed, fields_resp = {}, None
    if slots["fields"] or whole:
        sub = {"fields": slots["fields"], "tables": whole}
        fields_parsed, fields_resp = ask(build_prompt(sub, pages, doc_type), sub,
                                         "fields" + ("+tables" if whole else ""))
    conc = max(1, int(C.setting("PAGE_CALL_CONCURRENCY", 3) or 1))

    def one(k, label):
        sub = {"fields": [], "tables": want[k]}
        n = nums[k]
        p = build_prompt(sub, [pages[k]], doc_type) + (
            f"\n\nThis is page {n} of {len(nums)} of the document, sent on its "
            f"own. Return only the rows printed on THIS page; a table this page "
            f"does not print is [].")
        img = [page_images[k]] if k < len(page_images) and page_images[k] else []
        exp = {t["name"]: (inventory["pages"].get(n) or {}).get(
            f"{SI.band_kind(t)}_rows", 0) for t in sub["tables"]}
        parsed, resp = ask(p, sub, f"{label} {n}", images=img, text=pages[k],
                           expect=exp)
        bad = None
        if not isinstance(parsed, dict):
            bad = getattr(resp, "error_kind", None) or "no usable answer"
        else:
            miss = [f for f in C.check_answer(parsed, sub, resp)
                    if f["kind"] == C.MISSING_TABLE]
            if miss:
                bad = "the answer left out the table"
        return k, parsed, resp, bad

    results, last_resp = {}, None
    order = sorted(want)
    with ThreadPoolExecutor(max_workers=conc) as pool:
        futs = [pool.submit(contextvars.copy_context().run, one, k, "page")
                for k in order]
        for f in futs:
            k, parsed, resp, bad = f.result()
            results[k] = (parsed, bad)
            last_resp = resp or last_resp
    failed = {}
    for k in order:
        if results[k][1]:
            _k, parsed, resp, bad = one(k, "retry:page")
            results[k] = (parsed, bad)
            last_resp = resp or last_resp
            if bad:
                failed[nums[k]] = bad
    tables = {t["name"]: [] for t in slots["tables"]}
    for t in whole:
        tables[t["name"]] = list(_table_rows_of(fields_parsed or {}, t,
                                                {"tables": whole}))
    for k in order:
        parsed, bad = results[k]
        if bad or not isinstance(parsed, dict):
            continue
        for t in want[k]:
            heads = table_headers(t)
            for r in _table_rows_of(parsed, t, {"tables": want[k]}):
                cells = r.get("cells") if isinstance(r.get("cells"), dict) else r
                if _echoed_header(cells, heads):
                    continue
                tables[t["name"]].append({**r, "page": k + 1})
    fields_ok = not (slots["fields"] or whole) or isinstance(fields_parsed, dict)
    pages_ok = any(not results[k][1] for k in order)
    if not fields_ok and not pages_ok:
        # Nothing at all came back: a FAILED document, not an empty success.
        return None, fields_resp or last_resp, failed
    if order and not pages_ok and not (slots["fields"] or whole):
        return None, last_resp, failed
    merged = {"fields": (fields_parsed or {}).get("fields") or {}, "tables": tables}
    if not fields_ok:
        failed[0] = "the call for the field slots failed"
    return merged, fields_resp or last_resp, failed


def output_cap(slots, expected_rows) -> int:
    """maxOutputTokens for one call, sized from what the page holds.

    A fixed cap is too small for a dense statement once thinking spends part
    of it (on gemini-2.5 thinking tokens count against the cap), and a cap
    the answer cannot reach costs nothing. Estimated: ~80 tokens per field
    answer, and per expected row ~60 + 20 per column; added to the base."""
    import llm_contract as C
    base = int(C.setting("GEMINI_MAX_OUTPUT_TOKENS", 8192))
    est = 300 + 80 * len(slots.get("fields") or [])
    for t in slots.get("tables") or []:
        rows = max(int((expected_rows or {}).get(t["name"], 0) or 0), 5)
        est += rows * (60 + 20 * len(table_headers(t)))
    return min(65536, base + est)


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


# ── a scalar label holding a scalar wrapped in prose (I11) ───────────────────
#
# Round 2 run 9 answered "Contract End Date" with "the last day of October
# 2020" — a sentence fragment, and wrong besides: the bill says the agreement
# expires on the meter read date FOLLOWING that day. Every check passed. The
# words really are printed on page 3, so `verify_span` grounds them; there is
# no pipe, no email and no phone, so `_single_datum` passes; the cell came back
# HIGH and unflagged and the fragment was written into the sheet.
#
# WHAT THIS IS NOT. It is not "return a parsed value or return nothing". That
# strict reading was measured across every recorded answer in the repo and
# BLANKS 24 of the 849 scalar values written today — 19 of them legitimate date
# ranges, because a period field holds two dates when the document prints two:
#
#     Pay Period      April 1–30, 2024
#     Period          March 15–22, 2024
#     Billing Period  Aug 12, 2020 to Sep 11, 2020
#
# Twenty-three correct values destroyed to catch one wrong one is the trade
# already refused for the strict span rule (see the NOTE below and
# DECISION-LOG §2, where it demoted 250 correct cells to reach a WORSE number).
# So the value is KEPT, demoted and flagged — the same trade as a misplaced
# value and an overprinted one. A visible wrong cell beats an invisible missing
# one, and which half of a sentence was wanted is not knowable here either.
#
# THREE CONDITIONS, ALL REQUIRED, and each one is what keeps a real template out
# of the net:
#
#   1. the LABEL implies a scalar — and a label naming prose beats every other
#      word in it, because "Charge Description" is a description and "Payment
#      Terms" are terms;
#   2. the value CONTAINS a token of that kind. "No date at all" deliberately
#      does not fire: that is where a band's label column lives — a column
#      headed "CURRENT ASSETS" holds account names, not amounts;
#   3. what is left over is PROSE — a lowercase closed-class English word that
#      is not one of the kind's own connectors. "shares" and "par" in "Common
#      Stock (100 shares @ $1,000 par)" are ordinary words, not function words,
#      so a balance sheet's equity line survives; "the" and "of" in "the last
#      day of October 2020" are not.
#
# ⚠ THE WORD LISTS ARE ENGLISH, so THE RULE IS SILENT ON A NON-ENGLISH
# DOCUMENT. A French date field holding "le dernier jour d'octobre 2020" is not
# caught: "octobre" is not in `_MONTHS`, so condition 2 fails and nothing fires.
# That is a gap, not a safeguard, and it is stated rather than papered over —
# the same class of limit `_VALUE_KW` was deleted for. Being silent is the right
# failure for an English-only rule (it demotes nothing it cannot read), but it
# must not be mistaken for coverage.

#: A label naming PROSE wins over every other word in it.
_PROSE_LABEL = re.compile(
    r"\b(description|desc|particulars|narration|notes?|comments?|remarks?|memo"
    r"|terms|method|status|name|address|title|type|category|purpose"
    r"|instructions?|message|label|holder|words|signature|line)\b", re.I)
_DATE_LABEL = re.compile(
    r"\b(date|dated|period|expiry|expires|expiration|maturity|dob|birth)\b",
    re.I)
_AMOUNT_LABEL = re.compile(
    r"\b(amount|amt|total|subtotal|balance|price|cost|fee|fees|charge|charges"
    r"|tax|vat|gst|discount|salary|wage|wages|gross|deduction|deductions"
    r"|deposit|payable|receivable|earnings|income|revenue|expenses?|profit"
    r"|loss|equity|assets?|liabilit(?:y|ies)|debit|credit|pay)\b|\$", re.I)
_COUNT_LABEL = re.compile(
    r"\b(qty|quantity|count|hours|hrs|days|percent|pct|number of|no of)\b|%",
    re.I)
#: `labels_an_identifier` (extract.py) asks the same question for a different
#: job — is this digit run a quantity or something you quote — and matches the
#: word ANYWHERE. Here it must be the label's HEAD, because "Account Number" is
#: an identifier and "Account Holder" is a person.
_ID_LABEL_HEAD = re.compile(
    r"(id|ids|no|nos|num|number|#|code|ref|reference|nmls|ein|ssn|tin|itin"
    r"|routing|aba|acct|licen[cs]e|policy|serial|iban|swift|zip|postcode"
    r"|postal)\b[\s:.)*]*$", re.I)

_MONTHS = r"jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec"
_DATE_TOKEN = re.compile(
    r"\d{1,4}[/.-]\d{1,2}(?:[/.-]\d{1,4})?"
    r"|(?:" + _MONTHS + r")[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s*\d{0,4}"
    r"|\d{1,2}(?:st|nd|rd|th)?\s+(?:" + _MONTHS + r")[a-z]*\.?,?\s*\d{0,4}"
    r"|(?:" + _MONTHS + r")[a-z]*\.?\s+\d{4}"
    r"|\d{1,2}\s*[-–]\s*\d{1,2},?\s*\d{4}", re.I)
_NUMBER_TOKEN = re.compile(
    r"\(?\s*[-+]?\s*[$£€₹¥]?\s*\d[\d,  ]*(?:\.\d+)?\s*\)?\s*"
    r"(?:%|usd|eur|gbp|cad|aud|kwh|kw|hrs?|hours?|days?)?", re.I)
_ANY_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9./#*-]*")

#: What a kind's own notation may legitimately leave behind. A RANGE is the
#: reason this exists: a period field holds two dates joined by a word.
_CONNECTORS = {
    "date": {"to", "through", "thru", "and", "until", "till"},
    "amount": {"cr", "dr", "usd", "eur", "gbp", "each", "per"},
    "number": {"each", "per", "hr", "hrs", "hours", "days", "kwh", "kw",
               "units", "unit", "pcs"},
    "id": set(),
}

#: CLOSED-CLASS English words — determiners, prepositions, conjunctions,
#: pronouns, auxiliaries. An open-class word ("shares", "par", "Inventory") is
#: what an ordinary short value is made of; a function word is what a SENTENCE
#: is made of, and a sentence is what does not belong in a date cell.
_FUNCTION_WORDS = {
    "the", "a", "an", "this", "that", "these", "those", "my", "your", "his",
    "her", "its", "our", "their",
    "of", "on", "in", "at", "for", "to", "from", "by", "with", "into", "onto",
    "upon", "over", "under", "after", "before", "during", "until", "till",
    "within", "without", "between", "among", "about", "through", "across",
    "per", "via", "than", "since", "against", "toward", "towards",
    "and", "or", "but", "nor", "if", "unless", "whether", "because", "so",
    "as", "while", "when", "where", "which", "who", "whom", "whose", "what",
    "is", "are", "was", "were", "be", "been", "being", "am", "will", "shall",
    "would", "should", "may", "might", "can", "could", "must", "do", "does",
    "did", "has", "have", "had",
    "not", "no", "any", "all", "each", "every", "such", "same", "other",
    "both", "either", "neither",
    "it", "they", "them", "he", "she", "we", "you",
}
_WORDS = re.compile(r"[A-Za-z]{2,}")


def scalar_kind(label):
    """'date' | 'amount' | 'number' | 'id' | None — what the LABEL promises.

    Precedence is the same shape as `labels_an_identifier`'s: the more specific
    class wins, and a label naming prose beats them all.
    """
    lab = str(label or "")
    if not lab.strip() or _PROSE_LABEL.search(lab):
        return None
    if _DATE_LABEL.search(lab):
        return "date"
    if _AMOUNT_LABEL.search(lab):
        return "amount"
    if _COUNT_LABEL.search(lab):
        return "number"
    if _ID_LABEL_HEAD.search(lab):
        return "id"
    return None


def prose_in_a_scalar(value, label):
    """(True, why) when a scalar-implying label holds a scalar WRAPPED IN PROSE.

    Read the block above before changing any of this, in particular why "no
    scalar at all" deliberately does not fire and why the value is kept.
    """
    kind = scalar_kind(label)
    v = str(value or "").strip()
    if not kind or not v:
        return False, ""
    if kind == "date":
        tokens = [m.group(0) for m in _DATE_TOKEN.finditer(v)]
    elif kind in ("amount", "number"):
        tokens = [m.group(0) for m in _NUMBER_TOKEN.finditer(v)]
    else:
        tokens = [m.group(0) for m in _ANY_TOKEN.finditer(v)]
    if not tokens:
        return False, ""                      # condition 2 — see the block above
    residue = v
    if kind != "id":
        for t in sorted(tokens, key=len, reverse=True):
            residue = residue.replace(t, " ", 1)
    prose = [w for w in _WORDS.findall(residue)
             if w.islower() and w in _FUNCTION_WORDS
             and w not in _CONNECTORS[kind]]
    if not prose:
        return False, ""
    return True, (f"this cell asks for a {kind} and the answer is a sentence "
                  f"with one in it ({' '.join(sorted(set(prose)))}) — the "
                  f"value written is the model's phrasing, not the "
                  f"document's {kind}")


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
    # I11 — a scalar label holding a scalar wrapped in prose. Demoted and
    # flagged here rather than blanked at the writer, so the reason travels
    # with the cell through `_flag` like every other demotion.
    prose, why = prose_in_a_scalar(value, label)
    if prose:
        return LOW, why
    return (GROUNDED if inferred else HIGH), ""


def _words_nc(s) -> list:
    """Flattened words with commas dropped (E12)."""
    return _flat(str(s or "").replace(",", " ")).split()


def in_line_order(text, page_texts, page=None, max_lines=8) -> bool:
    """Run E, E12: is `text` printed as an ORDERED SEQUENCE of the page's
    lines — a run of its words on one line, the next run on the very next
    line, and so on — ignoring line breaks and commas?

    That is how an address prints: `14 Weavers Yard` / `Shoreditch` /
    `London E2 7DP` / `United Kingdom`, and on an invoice with FROM and BILL
    TO side by side every one of those lines also carries the other party's
    words, so the address is never a contiguous substring of the text. Three
    or more words, at most `max_lines` consecutive lines, every line used
    contributing a run; a word the page does not print, or the parts out of
    order, fails."""
    want = _words_nc(text)
    if len(want) < 3:
        return False
    try:
        pi = int(page) - 1
    except (TypeError, ValueError):
        pi = -1
    pages = ([page_texts[pi]] if 0 <= pi < len(page_texts or []) else []) + list(page_texts or [])
    for txt in pages:
        lines = [_words_nc(ln) for ln in str(txt or "").splitlines()]
        lines = [ln for ln in lines if ln]
        for i in range(len(lines)):
            k, j = 0, i
            while k < len(want) and j < len(lines) and j < i + max_lines:
                ws, best = lines[j], 0
                for m in range(len(want) - k, 0, -1):
                    run = want[k:k + m]
                    if any(ws[s:s + m] == run for s in range(len(ws) - m + 1)):
                        best = m
                        break
                if not best:
                    break
                k += best
                j += 1
            if k == len(want) and j - i >= 2:
                return True
    return False


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
    if not any(src in h for h in ordered if h) and not in_line_order(
            source, page_texts, page):
        return False, "source span not found in document"

    # the value must sit inside the span it claims to come from — or, failing
    # that, inside the record that span belongs to.
    #
    # A NUMBER must be a whole printed number, differing only in notation
    # (whitespace, currency symbol, thousands separators, parentheses as
    # minus). It used to be enough for it to be a substring of the span, for
    # its digits to be a substring of the span's digits, or for it to equal a
    # span number rounded to two decimals — so against a printed `$0.04116`,
    # `0.04`, `0.041`, `$40.4` and `4042` all grounded as high: a rounded or
    # truncated answer stored as verbatim, which nothing downstream can undo.
    # The digit rule was also quietly carrying numbers the text layer splits
    # into several words; printed_numbers rejoins those instead.
    key = _number_key(value)
    for span in (source, record):
        if not str(span or "").strip():
            continue
        if key is not None:
            if any(_number_key(tok) == key for tok in printed_numbers(span)):
                return True, ""
            continue
        val = _flat(value)
        if val and val in _flat(span):
            return True, ""
        # E12: commas are notation in a multi-line value (`Unit 9, Quayside`)
        nc = " ".join(_words_nc(value))
        if nc and len(nc.split()) >= 3 and nc in " ".join(_words_nc(span)):
            return True, ""
    return False, "value not found inside its own source span"


# ══════════════════════════════════════════════════════════════════════════════
# ONE REGION PER BAND
# ══════════════════════════════════════════════════════════════════════════════
#
# A band describes a SHAPE, and nothing ever chose WHICH region of the document
# carrying that shape it was bound to. The prompt asks for "one object per row
# present in the document" over every page, and every row that came back was
# kept. So Berkshire's earnings table (page 1) and its operating-earnings table
# (page 2) — same columns, same headings — were written into one band as one
# table (round 2, I1, runs 1-3). The same-page cases that came out right (runs
# 7, 8) were right because of how the model read those pages, not because of
# any check: there was none.
#
# A region here is a PAGE. That is deliberately narrow. Within one page, nothing
# available tells a subtotal gap inside one table from the gap between two
# tables without the row-classification work of I4, and no same-page merge was
# ever observed; every confirmed merge crossed a page.
#
# THE RULE IS STRICT, AND ITS COST IS ACCEPTED. A table that genuinely
# continues onto the next page loses its continuation, visibly — a short table
# can be seen; a merged lookalike cannot. A rule letting a continuation through
# when the next page repeats the column headings was considered and rejected:
# Berkshire's two tables carry IDENTICAL headings, so it would merge the exact
# case it exists to separate.
#
# WHICH REGION: the page the model's answer BEGINS on. Page order is not
# evidence of which table the band describes — the report has the merge going
# "in both directions" under two templates on one document — while the order
# the model answers in is its own reading of the band's meaning. A choice has
# to be made, it is named in the warning, and the warning fires every time more
# than one region matched, whether or not the choice was right.

# ── VALUE-BASED GROUNDING (Run B, B4) ────────────────────────────────────────
#
# `verify_span` checks the QUOTE the model gave and then the value inside it.
# A quote is the model's own rendering of a line, and it is wrong in ways the
# value is not: on the FlowParse card the model quoted lines with the SAMPLE
# watermark's letters in them ("SKYLARK AIR TICKETS ETravel $412.00"), and once
# the watermark is removed from the text those quotes match nothing - while
# every value in them is printed, plainly, on one line. What has to be on the
# page is the VALUE. So when the quote fails, the line is found from the
# value(s) themselves, and that line becomes the source.

def _line_str(ln) -> str:
    return " ".join(str(w.get("text", "")) for w in ln)


def value_on_line(value, text) -> bool:
    """Is `value` printed on this line, allowing only for notation?"""
    v = str(value or "").strip()
    if not v:
        return False
    key = _number_key(v)
    if key is not None:
        return any(_number_key(tok) == key for tok in printed_numbers(text))
    from dates import parse_date
    d = parse_date(v)
    if d.ok and re.search(r"\d", v):
        for tok in re.findall(r"[0-9A-Za-z]+[/.\-][0-9A-Za-z]+[/.\-][0-9]{2,4}", text):
            dt = parse_date(tok)
            if dt.ok and dt.value == d.value:
                return True
    fv = _flat(v)
    return bool(fv) and fv in _flat(text)


def value_lines(value, all_lines) -> list:
    """Indices of every line on which `value` is printed."""
    return [i for i, ln in enumerate(all_lines or [])
            if ln and value_on_line(value, _line_str(ln))]


def reanchor_row(cells, headers, all_lines, claimed=()):
    """The first unclaimed line printing EVERY non-empty value of this row,
    or None. All of them, so a row cannot be anchored by one shared amount."""
    vals = [str(cells.get(h, "") or "").strip() for h in headers]
    vals = [v for v in vals if v]
    if not vals or not all_lines:
        return None
    for i, ln in enumerate(all_lines):
        if i in claimed or not ln:
            continue
        text = _line_str(ln)
        if all(value_on_line(v, text) for v in vals):
            return i
    return None


def page_of(source, page, all_lines, page_lines, line_no=None):
    """The FILE page a value was read from, or None when nothing can say (I2).

    Geometry first, because it is the document's own answer: the line the row
    claimed, else every line the quote could be read from. Only when geometry
    has nothing does the model's page count, and then only mapped from prompt
    numbering to file numbering — the model counts the pages it was shown,
    which is not the file's numbering once a file is split.

    A quote printed on several pages, none of which the model named, gets None
    rather than a guess: a wrong page in a source column is worse than a blank.
    """
    if line_no is not None and all_lines:
        p = line_page(all_lines[line_no])
        if p is not None:
            return p
    mapped = page_for_prompt_page(page_lines, page) if page_lines else None
    if all_lines and str(source or "").strip():
        pages = _pages_of(source_occurrences(all_lines, source), all_lines)
        if len(pages) == 1:
            return next(iter(pages))
        if pages:
            return mapped if mapped in pages else None
    return mapped


def page_value_page(prov, page_origins, all_lines):
    """The file page a graded value belongs to, for its origin and its page
    gate: the page its provenance records, else the one page its quote can be
    read from, else None. A quote printed on several pages counts as native
    only when every one of them is native.
    """
    prov = prov or {}
    try:
        pg = int(prov["page"]) if prov.get("page") is not None else None
    except (TypeError, ValueError):
        pg = None
    if pg in page_origins:
        return pg
    if all_lines and str(prov.get("source") or "").strip():
        found = _pages_of(source_occurrences(all_lines, prov["source"]),
                          all_lines) & set(page_origins)
        if len(found) == 1 or (found and all(page_origins[p] == "native"
                                             for p in found)):
            return min(found)
    return None


def origin_floor(level):
    """The level a value keeps when its text is a machine's reading.

    A value that passed its checks is UNVERIFIED — never HIGH or GROUNDED,
    because the text it was checked against was itself read by a machine. A
    value that FAILED a check stays exactly what the check said: a measured
    failure is never turned into "no measurement".
    """
    return UNVERIFIED if level in CONFIDENT_LEVELS else level


#: Why a value needs review because a CHECK FAILED — never because of origin.
GROUNDING_FAILED = "grounding_failed"          # the quoted span is not on the page
PLACEMENT_FAILED = "placement_failed"          # under another column, or across a gutter
CONTENT_CHECK_FAILED = "content_check_failed"  # grounded, but not one datum / prose in a scalar
POSSIBLE_MULTIPLE = "possible_multiple_documents"  # one record, more than one cheque?
THIN_TEXT_LAYER = "thin_text_layer"            # Gate 2c: image-covered page, OCR could not check it
#: Run A, A4.2 — the prefix of a flag on an EMPTY slot the page shows a value
#: for (an unplaced amount beside its label, a form's filled values not
#: placed, a label the model quoted with no value). The flag is what turns the
#: review status `empty` into `empty_flagged`.
EMPTY_FLAGGED = "empty_flagged"
# Family checks' codes (amount_mismatch, checksum_failed, ...) live with their
# validators: cheque_validators.py, registered in validators.py.


def _add(reasons, why):
    if why not in reasons:
        reasons.append(why)


def review_metadata(origin, failures=()):
    """(review_required, review_reasons): owed to the value's origin, then to
    every check it failed or could not complete, in that order."""
    reasons = [] if origin == "native" else [f"{origin}_origin"]
    for why in failures:
        _add(reasons, why)
    return bool(reasons), reasons


def _row_at(tables_out, ref):
    """The row a validator addresses as `<table>_rows[i]`, or None."""
    m = re.fullmatch(r"(.+)_rows\[(\d+)\]", str(ref))
    rows = tables_out.get(m.group(1)) if m else None
    i = int(m.group(2)) if m else 0
    return rows[i] if rows is not None and i < len(rows) else None


def _pages_of(occurrences, all_lines):
    return {p for p in (line_page(all_lines[i]) for i in occurrences)
            if p is not None}


_TOTAL_LABEL = re.compile(r"^\s*(?:grand\s+|sub[- ]?)?totals?\b[\s:]*(?:amount|due)?\s*:?\s*$",
                          re.I)


def split_total_rows(rows, keys):
    """(rows, total rows) — a row is the table's OWN TOTAL only when its
    label cell is a total word ("Total", "Subtotal", "Grand Total") AND every
    amount it carries equals the sum of that column over the rows above it
    (since the previous total), to the cent per row. Vocabulary alone is not
    evidence — "Total Fuel" can be a line — and arithmetic alone is not
    either; both, or the row stays (Part 3.5). An ambiguous figure proves
    nothing and keeps the row."""
    from decimal import Decimal

    from amounts import parse_amount
    if not rows or not keys:
        return rows, []
    label = keys[0]
    kept, totals, since = [], [], []
    for row in rows:
        lab = str(row.get(label) or "").strip()
        nums = {}
        for k in keys[1:]:
            txt = str(row.get(k) or "").strip()
            if txt:
                a = parse_amount(txt)
                nums[k] = a.value if a.ok and not a.percent else None
        if _TOTAL_LABEL.match(lab) and since and nums and None not in nums.values():
            sums_ok = True
            for k, v in nums.items():
                col = []
                for r in since:
                    t = str(r.get(k) or "").strip()
                    if not t:
                        continue
                    a = parse_amount(t)
                    if not a.ok or a.percent:
                        col = None
                        break
                    col.append(a.value)
                if not col or abs(sum(col) - v) > Decimal("0.01") * len(col):
                    sums_ok = False
                    break
            if sums_ok:
                totals.append(row)
                since = []
                continue
        kept.append(row)
        since.append(row)
    return kept, totals


_OPENING_LINE = re.compile(
    r"^\s*(?:beginning|opening|previous|starting)\s+balance\b|^\s*balance\s+(?:forward|brought)\b",
    re.I)


def split_opening_rows(rows, keys, field_values):
    """(rows, opening rows) - Run B. A statement prints its opening balance as
    the first line of its transaction table ("09/01 BEGINNING BALANCE
    18,240.12"); it is not a transaction. Such a row is taken out ONLY when
    every amount it carries is already in one of the sheet's own fields (the
    template's Opening Balance), so nothing the reader needs leaves the sheet;
    any other row stays."""
    from amounts import parse_amount
    if not rows or not keys:
        return rows, []
    held = set()
    for v in field_values:
        a = parse_amount(str(v or ""))
        if a.ok and not a.percent:
            held.add(abs(a.value))
    kept, opening = [], []
    for row in rows:
        texts = [str(row.get(k) or "") for k in keys]
        if not any(_OPENING_LINE.match(t) for t in texts):
            kept.append(row)
            continue
        nums = []
        for t in texts:
            a = parse_amount(t.strip()) if t.strip() else None
            if a is not None and a.ok and not a.percent and re.search(r"\.\d{2}\b", t):
                nums.append(abs(a.value))
        if nums and all(n in held for n in nums):
            opening.append(row)
        else:
            kept.append(row)
    return kept, opening


#: A label that CLOSES a table: its own total, a net figure, a closing
#: balance. Broader than `_TOTAL_LABEL` (which must match the whole label,
#: for the arithmetic gate) because here it only decides whether a table
#: has ended at a page break.
_ENDS_TABLE = re.compile(
    r"^\s*(?:grand\s+|sub[- ]?)?totals?\b|^\s*net\s+(?:pay|income|earnings|amount)\b"
    r"|\b(?:ending|closing)\s+balance\b", re.I)

_PAGE_N_OF = re.compile(r"page\s+(\d{1,3})\s*(?:of|/)\s*(\d{1,3})", re.I)


def continued_pages(kept_page, all_lines, headers):
    """Pages after `kept_page` that the DOCUMENT says continue its table
    (Part 3.5): each is numbered as the next page of the same run ("Page 2 of
    5" after "Page 1 of 5") AND reprints the band's own heading line. Both,
    because a heading alone is what two different tables share (Berkshire's
    two earnings tables, round 2 I1), and numbering alone says nothing about
    which table a page holds. Anything less stays a different region."""
    heads = [str(h or "").strip().casefold() for h in headers or [] if str(h or "").strip()]
    if len(heads) < 2 or not all_lines:
        return set()
    by_page = {}
    for ln in all_lines:
        p = line_page(ln)
        if p is not None:
            by_page.setdefault(p, []).append(
                " ".join(str(w.get("text", "")) for w in ln if isinstance(w, dict)))

    def numbered(p):
        for t in by_page.get(p, []):
            m = _PAGE_N_OF.search(t)
            if m:
                return int(m.group(1)), int(m.group(2))
        return None

    def heading(p):
        return any(all(h in t.casefold() for h in heads) for t in by_page.get(p, []))

    out, p = set(), kept_page
    while True:
        a, b = numbered(p), numbered(p + 1)
        if not (a and b and b == (a[0] + 1, a[1]) and heading(p + 1)):
            return out
        out.add(p + 1)
        p += 1


def _heading_on(page, all_lines, headers) -> bool:
    """Does `page` print one line holding every one of the band's headings?"""
    heads = [str(h or "").strip().casefold() for h in headers or []
             if str(h or "").strip()]
    if len(heads) < 2:
        return False
    for ln in all_lines or []:
        if line_page(ln) != page:
            continue
        t = " ".join(str(w.get("text", "")) for w in ln if isinstance(w, dict)).casefold()
        if all(h in t for h in heads):
            return True
    return False


def _line_text(ln) -> str:
    """A visual line's words, casefolded, single-spaced: a comparison key."""
    return " ".join(" ".join(str(w.get("text", "")) for w in ln
                             if isinstance(w, dict)).casefold().split())


def _reprints_block(page, nxt, located, pages_by_row, all_lines) -> bool:
    """Does page `nxt` print again the heading block the band has on `page`
    — the (up to two) lines without an amount directly above the band's
    first row there? The DOCUMENT's own headings, whatever the template calls
    its columns: Berkshire prints "Fourth Quarter  Full Year" over
    "2024 2023 2024 2023" above both of its tables."""
    import source_inventory as SI
    first = None
    for (_c, _s, _p, _k, occ), pages in zip(located, pages_by_row):
        if page in pages:
            idx = [i for i in occ if line_page(all_lines[i]) == page]
            if idx:
                first = min(idx) if first is None else min(first, min(idx))
    if first is None:
        return False
    block = []
    for i in (first - 1, first - 2):
        if i < 0 or line_page(all_lines[i]) != page:
            break
        ln = all_lines[i]
        if any(SI.amount_of(w.get("text", "")) is not None for w in ln
               if isinstance(w, dict)):
            break
        block.append(_line_text(ln))
    if not block:
        return False
    on_next = {_line_text(ln) for ln in all_lines if line_page(ln) == nxt}
    return any(b in on_next for b in block)


def select_region(located, all_lines, page_lines, headers=None):
    """(located rows kept, region report or None).

    `located` is [(cells, source, page, key, occurrences)] in the model's
    order. A row's pages are the file pages of every line its source could be
    read from; with no such line, the page the model claimed. A row carrying
    no page at all (no geometry, or a source matching nothing) is never left
    out — nothing says it belongs to another region, and it is already
    ungrounded.

    Kept rows have their occurrences narrowed to the kept page, so a line
    printed on both pages is claimed where the table actually is.
    """
    pages_by_row = []
    for _cells, _source, page, _key, occurrences in located:
        pages = _pages_of(occurrences, all_lines) if all_lines else set()
        if not pages and not occurrences:
            p = page_for_prompt_page(page_lines, page)
            pages = {p} if p is not None else set()
        pages_by_row.append(pages)

    distinct = []
    for pages in pages_by_row:
        for p in sorted(pages):
            if p not in distinct:
                distinct.append(p)
    if len(distinct) < 2:
        return located, None

    # The first row that places itself on exactly one page decides; a row
    # whose source is printed on several pages cannot.
    kept_page = next((next(iter(p)) for p in pages_by_row if len(p) == 1),
                     distinct[0])
    region = {kept_page} | continued_pages(kept_page, all_lines, headers)
    # A BAND CONTINUES ACROSS A PAGE BREAK UNTIL ITS TOTAL LINE (Run A, A8.3).
    # The strict rule above kept one page unless the document numbered its
    # pages, and gave up real rows that simply ran onto the next page — a
    # payslip's `Life Insurance` deduction and three equity lines of a
    # balance sheet were dropped. A table whose rows on its last page do not
    # end in its own total line has not ended: the NEXT page's rows are its
    # continuation. A table that did end there (Berkshire's first earnings
    # table, closed by its own total before the second one starts) keeps the
    # strict rule, and anything left out is still flagged.
    if headers:
        label = headers[0]
        last = max(region)
        while (last + 1) in distinct:
            on_last = [cells for (cells, *_r), pages in zip(located, pages_by_row)
                       if last in pages]
            if not on_last or _ENDS_TABLE.match(
                    str((on_last[-1] or {}).get(label) or "")):
                break
            # A page that prints the band's heading line again opens a NEW
            # table of the same shape (Berkshire page 2: the operating
            # earnings table under the same five headings). A numbered
            # continuation that reprints it is `continued_pages`' case.
            if _heading_on(last + 1, all_lines, headers) or _reprints_block(
                    last, last + 1, located, pages_by_row, all_lines):
                break
            # ...and its rows must LOOK like the band's rows: an amount in a
            # column where the rows before the break carry amounts. ENGIE's
            # page-4 glossary ("Meter Constant", no amount) is not the charges
            # table carrying on.
            import source_inventory as SI
            numeric = {k for c in on_last for k, v in (c or {}).items()
                       if k != label and SI.amount_of(str(v or "")) is not None}
            nxt_rows = [c for (c, *_r), pages in zip(located, pages_by_row)
                        if pages == {last + 1}]
            if not numeric or not nxt_rows or not all(
                    any(SI.amount_of(str((c or {}).get(k) or "")) is not None
                        for k in numeric) for c in nxt_rows):
                break
            region.add(last + 1)
            last += 1
    kept, left_out = [], []
    for row, pages in zip(located, pages_by_row):
        if pages and not (pages & region):
            left_out.append(row)
            continue
        cells, source, page, key, occurrences = row
        if pages:
            occurrences = [i for i in occurrences
                           if line_page(all_lines[i]) in region | {None}]
        kept.append((cells, source, page, key, occurrences))
    if not left_out:
        return located, None
    matched = sorted(region | {p for (row, pages) in zip(located, pages_by_row)
                               if pages and not (pages & region)
                               for p in pages})
    return kept, {"pages": matched, "kept_page": kept_page,
                  "kept_rows": len(kept), "left_out": len(left_out),
                  "left_out_rows": [(c, s) for c, s, *_ in left_out]}


# ══════════════════════════════════════════════════════════════════════════════
# RUN
# ══════════════════════════════════════════════════════════════════════════════

def declare_id_types(grid, slots):
    """`slots` with `id_type` copied from the template grid onto the field
    slots and table columns that declare one. New dicts: the shape (cached on
    the template data) is never mutated."""
    cells = (grid or {}).get("cells") or {}

    def kind(r, c):
        cell = cells.get(f"{r},{c}")
        return cell.get("id_type") if isinstance(cell, dict) else None
    fields = []
    for f in slots.get("fields") or []:
        k = kind(f.get("row"), f.get("col"))
        fields.append({**f, "id_type": k} if k else f)
    tables = []
    for t in slots.get("tables") or []:
        hr = t.get("header_row")
        cols = [({**c, "id_type": kind(hr, c.get("col"))} if kind(hr, c.get("col")) else c)
                for c in t.get("columns") or []]
        tables.append({**t, "columns": cols} if cols != (t.get("columns") or []) else t)
    return {**slots, "fields": fields, "tables": tables}


def template_locale(template_data):
    """The template's locale (`locale` on the template data or its grid), or
    None. A hint for reading numbers and dates, never a guess."""
    td = template_data if isinstance(template_data, dict) else {}
    grid = td.get("layout") if isinstance(td.get("layout"), dict) else {}
    return td.get("locale") or grid.get("locale") or None


def run_slot_extraction(orchestrator, file_path, template_data, binding_map,
                        page_images, doc_text, doc_text_pages, file_type,
                        default_doc_type, start, page_lines=None,
                        page_origins=None, page_numbers=None,
                        widget_values=None, unreadable=None, form_fields=None):
    """Slot-directed extraction for one file. Returns list[DocumentExtractionResult].

    `page_origins` ({file page: "native" | "ocr" | "pre_ocr"}) moves the
    scanned-document floor from the whole document to each value's own page;
    `page_numbers` is the file page of each entry of `doc_text_pages`. A
    caller passing no origins (an image upload, a direct call) keeps the
    whole-document floor exactly as before.
    """
    from orchestrator import DocumentExtractionResult

    file_path = Path(file_path)
    grid = (template_data or {}).get("layout", {}) or {}
    shape = (template_data or {}).get("shape")
    slots = enumerate_slots(grid, shape)
    if shape:
        _log("SLOT", f"{doc_ref(file_path)}: using STORED template shape")
    n_tbl_cols = sum(len(t["columns"]) for t in slots["tables"])
    _log("SLOT", f"{doc_ref(file_path)}: {len(slots['fields'])} field slots, "
                 f"{len(slots['tables'])} table(s), {n_tbl_cols} table columns")

    # Was this template designed by inference rather than by the user? If so no
    # cell can be HIGH — see the confidence vocabulary above.
    inferred = bool((template_data or {}).get("inferred"))
    confident = GROUNDED if inferred else HIGH
    if inferred:
        _log("SLOT", f"{doc_ref(file_path)}: inferred template — cells can be "
                     f"'{GROUNDED}' at best, never '{HIGH}'")

    pages = doc_text_pages or ([doc_text] if doc_text else [])
    import form_fields as FF
    import format_rules as FR
    if form_fields is None and widget_values and str(file_path).lower().endswith(".pdf"):
        try:
            from core.preprocessor import form_field_entries
            form_fields = form_field_entries(file_path)
        except Exception as e:                 # a hint, never fatal
            _log("SLOT", f"form field labels unreadable: {type(e).__name__}")
            form_fields = {}
    _wanted = set(page_numbers or range(1, len(pages) + 1))
    form_entries = [e for pg, es in sorted((form_fields or {}).items())
                    if int(pg) in _wanted for e in es]
    extra = FF.prompt_block(form_entries) if form_entries else ""
    # B2: match by meaning. Said only where it carries information - a slot
    # whose label is not printed but another wording of it is, or aliases the
    # template declares - so a template worded like its document is asked
    # exactly what it was asked before.
    import aliases as AL
    _lines_all = flatten_pages(page_lines) if page_lines else []
    # An INFERRED template's labels were named by the model from this very
    # document: there is no user wording to reconcile.
    wording = [] if inferred else AL.hints(slots, grid, _lines_all)
    extra += AL.prompt_block(wording)
    extra += cheque_bottom_line_hint(default_doc_type, slots, page_origins, file_type)
    extra += column_copy_hint(slots)
    prompt = build_prompt(slots, pages, default_doc_type, extra)

    # ── SOURCE INVENTORY + RESPONSE CONTRACT (Run A, A2/A3) ──
    # What the page holds, counted without the model, and an answer schema
    # in which every slot id and every table key is REQUIRED. Job 15 came
    # back as valid JSON with F1..F8 and no `tables` key, and the absence was
    # read as "no rows".
    import llm_contract as C
    import source_inventory as SI
    nums = list(page_numbers or range(1, len(pages) + 1))
    unread = unreadable or {}
    inventory = SI.build(page_lines or [], nums, widget_values or {},
                         page_origins or {}, unread.get("ocr_failed") or (),
                         unread.get("ocr_zero") or ())
    expected = SI.expected_rows(inventory, slots, page_lines or [], nums)
    sink = C.ATTEMPTS.get()
    attempts = sink if sink is not None else []

    def ask(p, sub, label, images=None, text=None, expect=None):
        tok = C.ATTEMPTS.set(attempts) if sink is None else None
        try:
            with C.section(label):
                return _llm_json(orchestrator, p, _SYSTEM,
                                 images=page_images if images is None else images,
                                 text=doc_text if text is None else text,
                                 response_schema=C.response_schema(sub, table_headers),
                                 max_output_tokens=output_cap(
                                     sub, expected if expect is None else expect))
        finally:
            if tok is not None:
                C.ATTEMPTS.reset(tok)

    # ── HEAVY DOCUMENTS: one PAGE at a time for tables (Run A, A8) ──
    min_pages = int(C.setting("PAGE_CALL_MIN_PAGES", 6) or 0)
    chunked = bool(min_pages and len(pages) >= min_pages and slots["tables"]
                   and page_lines)
    page_failed = {}
    if chunked:
        parsed, resp, page_failed = page_at_a_time(
            ask, slots, pages, page_lines, page_images or [], nums, inventory,
            default_doc_type)
    else:
        parsed, resp = ask(prompt, slots, "fields+tables")
    if not isinstance(parsed, dict):
        _log("SLOT", "no parseable response — failing the document")
        from app.api.routes.extract import _fail
        err = str(getattr(resp, "error", "") or "") if resp is not None else ""
        kind = getattr(resp, "error_kind", None) if resp is not None else None
        why = "Slot extraction returned no usable JSON"
        if resp is not None and not getattr(resp, "success", False):
            why += f" — the model call failed: {err or 'no error given'}"
        failed_r = _fail(file_path.name, why)
        failed_r.extracted_data = {
            "document_state": "FAILED", "failure_kind": kind or C.INVALID_JSON,
            "diagnostics": {"attempts": attempts,
                            "usage": C.summarise(attempts),
                            "inventory": inventory["totals"],
                            "pages": {str(n): "failed" for n in nums}}}
        failed_r.extraction_response = resp
        return [failed_r]

    # ── FORM-FIELD LANE (Run B, B1) ──
    # A filled widget is one value in one box under its own printed label:
    # better evidence than anything the model can pair up from the flattened
    # text. A slot the model left empty, answered with the same value in
    # another notation, or (on a strong match) contradicted, takes the
    # widget's value. It is MACHINE-READ from the file - recorded as such in
    # its provenance and notes - and never reported as missing.
    machine_read = {}
    if form_entries and slots["fields"]:
        answers0 = parsed.get("fields")
        if not isinstance(answers0, dict):
            answers0 = parsed["fields"] = {}
        for f in slots["fields"]:
            entry, strong = FF.match(f["row_label"], form_entries)
            if entry is None:
                continue
            had = _answer_value(answers0.get(f["slot_id"]))
            agrees = bool(had) and FF.same_value(had, entry["value"])
            if had and not agrees and not strong:
                continue                      # a weak match never overrules
            machine_read[f["slot_id"]] = {
                "entry": entry, "model": "" if agrees else had}
            answers0[f["slot_id"]] = {"value": entry["value"],
                                      "source": entry["value"],
                                      "page": entry["page"]}
        if machine_read:
            _log("SLOT", f"{doc_ref(file_path)}: {len(machine_read)} slot(s) "
                         f"filled from the PDF's form fields")

    # Validate BEFORE anything becomes a cell. Missing slot ids whose label
    # the page does not print are not worth a second call — the document
    # simply has no such field.
    contract_first = C.check_answer(parsed, slots, resp, expected)
    C.note_contract(attempts, *C.counts(parsed, slots))
    printed = {f["slot_id"] for f in slots["fields"]
               if any(SI.label_lines(ln, f["row_label"]) for ln in (page_lines or []))}
    retry_ids, retry_tables = [], []
    for fl in contract_first:
        if fl["kind"] == C.MISSING_SLOT:
            retry_ids += [s for s in fl["slots"] if s in printed or not page_lines]
        elif fl["kind"] in (C.MISSING_TABLE, C.EMPTY_TABLE) and not chunked:
            retry_tables += fl["tables"]
    # Empty answers the page contradicts (unplaced amount beside the label,
    # a form's filled values not placed, a label quoted with no value).
    pre = SI.coverage(inventory, slots,
                      {f["ref"]: _answer_value((parsed.get("fields") or {}).get(f["slot_id"]))
                       for f in slots["fields"]
                       if _answer_value((parsed.get("fields") or {}).get(f["slot_id"]))},
                      {t["name"]: [r.get("cells", r) for r in _table_rows_of(parsed, t, slots)]
                       for t in slots["tables"]},
                      parsed.get("fields"), page_lines or [], nums,
                      form_lane=bool(form_entries))
    ref_to_id = {f["ref"]: f["slot_id"] for f in slots["fields"]}
    retry_ids += [ref_to_id[r] for r in pre["flag_slots"] if r in ref_to_id]
    retry_ids = list(dict.fromkeys(retry_ids))
    retry_tables = list(dict.fromkeys(retry_tables))
    contract_after = contract_first
    if retry_ids or retry_tables:
        sub = {"fields": [f for f in slots["fields"] if f["slot_id"] in retry_ids],
               "tables": [t for t in slots["tables"] if t["name"] in retry_tables]}
        labels = [f["row_label"] for f in sub["fields"]] + \
                 [f'table "{t["name"]}"' for t in sub["tables"]]
        _log("SLOT", f"{doc_ref(file_path)}: targeted second request for "
                     f"{len(sub['fields'])} slot(s) and {len(sub['tables'])} table(s)")
        p2 = build_prompt(sub, pages, default_doc_type, extra) + (
            "\n\nSECOND REQUEST. Your previous answer left out these, or left "
            "them empty while the page prints a value for them: "
            + "; ".join(labels) + ". The page image is attached. Answer ONLY "
            "these slots and tables. Read every row of each table. If a value "
            "really is not on the page, give \"\" with status \"absent\".")
        parsed2, resp2 = ask(p2, sub, "retry:" + ",".join(
            (["fields"] if sub["fields"] else []) + [t["name"] for t in sub["tables"]]))
        if isinstance(parsed2, dict):
            parsed = C.merge_answers(parsed, parsed2, retry_ids, retry_tables)
            C.note_contract(attempts, *C.counts(parsed2, sub))
        contract_after = C.check_answer(parsed, slots, resp, expected)

    # Declared identifier kinds (`id_type` on a value cell or a table
    # heading) — attached AFTER the prompt is built, so a declaration never
    # changes what the model is asked (Part 1.6).
    slots = declare_id_types(grid, slots)
    by_id = {f["slot_id"]: f for f in slots["fields"]}
    # I2 — where each field value was read from: {ref: {source, page, grounded}}.
    # `grounded` is None when the value never reached span verification (it was
    # set aside for a different reason, which its flag names).
    field_prov = {}
    extracted_fields, conf_map, flagged, notes = {}, {}, [], []
    ungrounded = 0
    misplaced = 0
    dropped = 0
    empty_rows = 0
    total_rows = 0
    off_schema_keys = 0
    merged_columns = 0
    overprinted = 0
    unwitnessed = 0
    reanchored = 0          # B4: quotes replaced by the line printing the value
    opening_rows = 0        # opening-balance lines left out of a transaction table
    duplicate_total_rows = 0  # a total line repeating its own slot (Run C, C4.1)
    copied_cols = 0           # a column copied from another column (Run E, E9)
    all_lines = flatten_pages(page_lines)
    regions_warned = []
    # WHICH CHECK FAILED, per value. A value made low by a failed check used
    # to say so only in `flagged_fields`; its own provenance carried no reason,
    # so a reader of one value could not tell "checked and failed" from
    # "never checked". {ref: [reason]} for fields; [(row, [reason])] for rows.
    field_fail, row_fail = {}, []

    def failed(ref, why):
        _add(field_fail.setdefault(ref, []), why)

    # PLACEMENT FOR FIELD SLOTS (I9). This check used to run on table rows
    # only — one call site, inside the table loop — so a key/value template
    # got no positional verdict of any kind. That is most of what a user
    # draws, and the column a value sits under is most of its meaning.
    #
    # A field slot carries the heading of the column it was drawn in, so it
    # can be checked by exactly the rule a table row is: find where the
    # document prints that heading, and see whether the value sits under it.
    field_headers = [f.get("col_header", "") for f in slots["fields"]]
    field_bands = (column_bands(all_lines, field_headers)
                   if (all_lines and any(field_headers)) else {})
    if field_bands:
        _log("PLACE", "field slots: column bands read from the document for "
                      f"{sorted(field_bands)}")

    # A TEMPLATE COLUMN THE DOCUMENT NEVER NAMES (I9). `column_bands` returning
    # nothing was treated as "no verdict", which is correct as a placement
    # decision and silent as a report. The user drew a column meaning
    # something; if the document does not say it anywhere, nothing chose which
    # source column filled it except position, and that is worth saying out
    # loud rather than leaving to be discovered in the spreadsheet.
    if all_lines:
        declared = list(field_headers)
        for t in slots["tables"]:
            declared += [c.get("header", "") for c in (t.get("columns") or [])]
            declared += [f.get("header", "") for f in (t.get("fields") or [])]
        # Run B, B8: a heading the document words differently is not missing
        # ("Running Balance" against a printed "Balance", "Item Description"
        # against "Description"), and a column nothing was placed under has
        # nothing to warn about. Both used to flag: job 19 (a correct PO) and
        # every bank, W-2 and card statement carried this flag, so none of
        # them could ever be approve-only. The check now keeps the headings
        # printed neither literally nor by an alias, and reports - below, once
        # the tables are read - only those that actually received a value.
        import aliases as AL
        unprinted_cols = [h for h in unprinted_headers(all_lines, declared)
                          if not AL.printed_by_meaning(all_lines, h)]
    else:
        unprinted_cols = []

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
            mr = machine_read.get(slot["slot_id"])
            if mr and str(value) == mr["entry"]["value"]:
                e = mr["entry"]
                field_prov[slot["ref"]] = {
                    "source": f'form field "{(e["label"] or e.get("extra") or "").strip()}"',
                    "page": e["page"], "grounded": True,
                    "machine_read": "form_field"}
                extracted_fields[slot["ref"]] = value
                conf_map[slot["ref"]] = confident
                notes.append(f'{slot["row_label"]}: machine-read from the PDF '
                             f'form field' + (f' (the model read {mr["model"]!r})'
                                              if mr["model"] else ""))
                continue
            if is_label_echo(value, slot["row_label"]):
                notes.append(f'{slot["row_label"]}: the model returned the '
                             f"slot's own label instead of a value — dropped")
                continue
            field_prov[slot["ref"]] = {
                "source": source,
                "page": page_of(source, page, all_lines, page_lines),
                "grounded": None}

            # LAST 4 (Run B, B3): exactly four digits, and the suffix of an
            # account / card number the page prints - checked against the
            # page, not the model's quote.
            if all_lines and FR.is_last4_slot(slot["row_label"]):
                status, fixed4, line4 = FR.check_last4(value, all_lines,
                                                       slot["row_label"])
                if status in ("ok", "corrected"):
                    field_prov[slot["ref"]].update(
                        source=line4, grounded=True,
                        page=page_of(line4, 0, all_lines, page_lines))
                    if status == "corrected":
                        field_prov[slot["ref"]]["machine_corrected"] = str(value)
                        notes.append(f'{slot["row_label"]}: machine-corrected '
                                     f'{str(value)!r} to {fixed4!r}, the last four '
                                     f'digits of the number the page prints')
                    extracted_fields[slot["ref"]] = fixed4
                    conf_map[slot["ref"]] = confident
                    continue
                if status == "ambiguous":
                    flagged.append(_flag(
                        slot["row_label"], value,
                        "the page prints more than one account/card number "
                        "and nothing says which one these last four belong to"))
                    extracted_fields[slot["ref"]] = value
                    conf_map[slot["ref"]] = LOW
                    failed(slot["ref"], CONTENT_CHECK_FAILED)
                    continue

            # ONE JOIN RULE (D9). A field's value is the document's own words,
            # in reading order, joined by a single space. The join used to be
            # whatever the model returned, and it returned three different
            # things for ONE field on ONE document — INV-2024-0031's Notes came
            # back truncated, joined with a literal newline, and joined with a
            # space across cached runs, with adjacent fields disagreeing inside
            # a single run. The words are at known positions, so the join is
            # re-derived rather than trusted. Nothing is added and nothing
            # dropped: the run of words must spell exactly what the model
            # claimed. A value matching no run is left alone.
            if all_lines:
                canon = canonical_value(value, all_lines)
                if canon:
                    fixed, crossed = canon
                    if fixed != value:
                        notes.append(f'{slot["row_label"]}: re-joined from the '
                                     f"document's own words")
                        value = fixed
                    if crossed:
                        # The run jumped a column gutter, so two side-by-side
                        # blocks were merged into one value. Which half was
                        # wanted is not knowable here, so it is reported rather
                        # than trimmed.
                        merged_columns += 1
                        flagged.append(_flag(
                            slot["row_label"], value,
                            "value runs across a column gutter — two "
                            "side-by-side blocks were merged into one answer"))
                        extracted_fields[slot["ref"]] = value
                        conf_map[slot["ref"]] = LOW
                        failed(slot["ref"], PLACEMENT_FAILED)
                        continue
                elif not matches_loosely(value, all_lines) and not in_line_order(
                        value, pages, page):
                    # (E12: a value printed as an ordered run of consecutive
                    # lines — an address beside another party's — IS spelled
                    # by the page, commas and line breaks aside.)
                    # NO RUN OF WORDS ON THE PAGE SPELLS THIS, even allowing
                    # for renotation. `canonical_value` has always known that
                    # and the answer was dropped on the floor: the branch read
                    # `if canon:` and a None fell through to be reported like
                    # any grounded value.
                    #
                    # The exit exists for values that are DERIVED rather than
                    # read — a reformatted number, a date rewritten to ISO —
                    # so it is kept for anything that matches a run once
                    # punctuation is ignored (`$7,750.00` against a printed
                    # `7,750.00`). What is left is a string assembled from
                    # words that are not next to each other, which is the
                    # shape of a flattening artifact.
                    #
                    # MICR is unaffected: those slots are filled in a separate
                    # pass below and never reach this code.
                    unwitnessed += 1
                    flagged.append(_flag(
                        slot["row_label"], value,
                        "no run of words on the page spells this value — it "
                        "was assembled from words that are not adjacent"))
                    extracted_fields[slot["ref"]] = value
                    conf_map[slot["ref"]] = LOW
                    failed(slot["ref"], GROUNDING_FAILED)
                    continue

                # TWO TEXTS PRINTED OVER ONE ANOTHER (I7). The characters of
                # both interleave, and pdfplumber returns the interleaving as a
                # single word — so the flattened text, the word boxes and
                # `canonical_value` all agree the string is on the page. It is
                # not: nothing printed it. Only the character geometry can say
                # so, and it says so plainly.
                #
                # The value is KEPT. Which of the two overprinted texts was
                # wanted is not recoverable, and a visible wrong cell beats an
                # invisible missing one — the same trade already made for a
                # misplaced value.
                if overprinted_value(value, all_lines):
                    overprinted += 1
                    flagged.append(_flag(
                        slot["row_label"], value,
                        "two texts are printed over one another here, so this "
                        "string is the two of them interleaved rather than "
                        "anything the page prints"))
                    extracted_fields[slot["ref"]] = value
                    conf_map[slot["ref"]] = LOW
                    failed(slot["ref"], GROUNDING_FAILED)
                    continue

            ok, why = verify_span(value, source, page, pages)
            if not ok and all_lines and why == "source span not found in document":
                # B4: grounding is about the VALUE. A quote the page does not
                # hold is replaced by the line that prints the value -
                # preferring one that also carries a word of the slot's label.
                # A quote the page DOES hold with the value not in it stays
                # ungrounded: that is a value taken from somewhere else.
                cands = value_lines(value, all_lines)
                if cands:
                    lab = [w for w in re.split(r"[^0-9a-z]+", slot["row_label"].casefold())
                           if len(w) >= 3]
                    pick = next((i for i in cands if any(
                        w in _line_str(all_lines[i]).casefold() for w in lab)), cands[0])
                    source = _line_str(all_lines[pick])
                    ok, why = verify_span(value, source, 0, pages)
                    if ok:
                        reanchored += 1
                        field_prov[slot["ref"]].update(
                            source=source, reanchored=True,
                            page=page_of(source, 0, all_lines, page_lines, pick))
            field_prov[slot["ref"]]["grounded"] = ok
            lvl, reason = confidence_for(value, source, slot["row_label"], ok,
                                         inferred=inferred)
            extracted_fields[slot["ref"]] = value
            conf_map[slot["ref"]] = lvl
            if not ok:
                ungrounded += 1
            if lvl not in CONFIDENT_LEVELS:
                flagged.append(_flag(slot["row_label"], value, reason or why))
                failed(slot["ref"], GROUNDING_FAILED if not ok
                       else CONTENT_CHECK_FAILED)
            # TYPE CHECK (Run B, B3): flag, never drop or coerce.
            t_ok, t_norm, t_why = FR.check_type(value, slot["row_label"])
            if t_norm is not None:
                field_prov[slot["ref"]]["normalised"] = t_norm
            if not t_ok and lvl in CONFIDENT_LEVELS:
                # Like an UNREADABLE check: said out loud, level not moved -
                # the string may be exactly what the page prints ("n/a").
                flagged.append(_flag(slot["row_label"], value, t_why))
            head = slot.get("col_header", "")
            if field_bands and head and lvl in CONFIDENT_LEVELS:
                line = find_line(all_lines, source)
                for _k, why_p in check_placement(
                        {head: value}, [{"key": head, "header": head}],
                        line, field_bands):
                    misplaced += 1
                    ungrounded += 1
                    conf_map[slot["ref"]] = LOW
                    failed(slot["ref"], PLACEMENT_FAILED)
                    flagged.append(_flag(slot["row_label"], value, why_p))

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
            field_prov[slot["ref"]] = {
                "source": micr_line,
                "page": page_of(micr_line, 0, all_lines, page_lines),
                "grounded": ok}
            lvl, reason = confidence_for(value, micr_line, slot["row_label"], ok,
                                         inferred=inferred)
            extracted_fields[slot["ref"]] = value
            conf_map[slot["ref"]] = lvl
            if not ok:
                ungrounded += 1
            if lvl not in CONFIDENT_LEVELS:
                flagged.append(_flag(slot["row_label"], value, reason or why))
                failed(slot["ref"], GROUNDING_FAILED if not ok
                       else CONTENT_CHECK_FAILED)
        if parts:
            _log("MICR", f"{doc_ref(file_path)}: band decomposed into "
                         f"{len(parts)} field(s)")

    # ── MORE ENTRIES THAN SLOTS (Run B, B5) ──
    # A box holding several stacked entries (W-2 Box 14: 1,600.00 H and
    # 52.00 X) against a template with one cell for it lost every entry but
    # the one the model chose, silently. An extra entry goes into the next
    # EMPTY slot of the same box when the template has one; otherwise it is
    # kept in the diagnostics and the field is flagged in a plain sentence.
    overflow = []
    if page_lines:
        import form_fields as _FF
        for f in slots["fields"]:
            val = extracted_fields.get(f["ref"])
            if not str(val or "").strip():
                continue
            entries = []
            for pl in page_lines:
                entries = SI.stacked_entries(pl, f["row_label"], val)
                if entries:
                    break
            if len(entries) < 2:
                continue
            box = _FF.box_id(f["row_label"])
            siblings = [g for g in slots["fields"] if g is not f and box
                        and _FF.box_id(g["row_label"]) == box
                        and g["ref"] not in extracted_fields]
            name = f"Box {box}" if box else f["row_label"]
            for n_e, e in enumerate(entries[1:]):
                nth = ("second", "third", "fourth", "fifth")[min(n_e, 3)]
                shown = f'{e["amount"]} {e["code"]}'.strip()
                if siblings:
                    g = siblings.pop(0)
                    extracted_fields[g["ref"]] = shown
                    conf_map[g["ref"]] = confident
                    field_prov[g["ref"]] = {"source": shown, "page": None,
                                            "grounded": True, "overflow_of": f["row_label"]}
                    notes.append(f'{name}: further entry {shown!r} placed in '
                                 f'{g["row_label"]!r}')
                    continue
                overflow.append({"slot": f["row_label"], "amount": e["amount"],
                                 "code": e["code"]})
                flagged.append(_flag(
                    f["row_label"], shown,
                    f"{name} has a {nth} entry {shown} that has no slot"))

    unanswered = [f for f in slots["fields"] if f["ref"] not in extracted_fields]
    if unanswered:
        notes.append(f"{len(unanswered)} field slot(s) returned no value: "
                     + ", ".join(f["row_label"] for f in unanswered[:8]))

    # ── table slots ──
    tables_out, row_counts, incomplete = {}, {}, set()
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
                # a count only: a band's name and headings are template text
                _log("PLACE", f"column bands read from the document for "
                              f"{len(bands)} heading(s)")
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
            located = []
            for r in raw:
                if not isinstance(r, dict):
                    continue
                cells = r.get("cells") if isinstance(r.get("cells"), dict) else r
                source, page = r.get("source", ""), r.get("page", 0)
                key = _flat(source)
                occurrences = (source_occurrences(all_lines, source)
                               if (all_lines and key) else [])
                if all_lines and not occurrences:
                    # B4: the quote is on no line; find the line from the
                    # row's own values and read the row from THAT line.
                    taken = {o for *_x, occ in located for o in occ[:1]}
                    li = reanchor_row(cells, headers, all_lines, taken)
                    if li is not None:
                        reanchored += 1
                        source = _line_str(all_lines[li])
                        key = _flat(source)
                        occurrences = source_occurrences(all_lines, source)
                located.append((cells, source, page, key, occurrences))

            # ONE REGION PER BAND (round 2, I1). See `select_region`.
            # Page-at-a-time rows were each asked of ONE page that prints
            # (or continues) the band, so they are bound to a region by
            # construction; only the single-call answer needs choosing.
            located, region = (located, None) if chunked else select_region(
                located, all_lines, page_lines,
                headers=([c.get("header") for c in t.get("columns") or []]
                         or table_headers(t)))
            if region:
                shown_pages = ", ".join(str(p) for p in region["pages"])
                left = region["left_out"]
                regions_warned.append({"table": t["name"], **{
                    k: v for k, v in region.items() if k != "left_out_rows"}})
                flagged.append(_flag(
                    f'{t["name"]}[regions]',
                    f'{len(region["pages"])} regions matched, on pages '
                    f'{shown_pages}; kept page {region["kept_page"]}',
                    f'{len(region["pages"])} regions of the document match '
                    f'this table (pages {shown_pages}). Only the one on page '
                    f'{region["kept_page"]} — where the answer began — was '
                    f'written; {left} row(s) from the other page(s) were left '
                    f'out rather than appended. If the table genuinely '
                    f'continues across pages, those rows are missing.'))
                notes.append(
                    f'{t["name"]}: {len(region["pages"])} regions matched on '
                    f'pages {shown_pages}; kept page {region["kept_page"]}, '
                    f'left out {left} row(s)')
                for cells, source in region["left_out_rows"]:
                    shown = " | ".join(
                        f"{h}={cells.get(h)}" for h in headers
                        if str(cells.get(h, "") or "").strip()) or str(source)[:60]
                    flagged.append(_flag(
                        f'{t["name"]}[not bound]', shown,
                        "row read from a different region of the document "
                        "than the one this table was bound to"))

            claims = []
            for cells, source, page, key, occurrences in located:
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
                # OFF-SCHEMA KEYS (I4). The `cells.get(h, "")` below is an
                # EXACT lookup over this band's column keys, so a key the model
                # returned that this template has no column for is discarded
                # here — and was discarded with nothing recorded. That is the
                # same loss as a dropped row one level down, and it is why the
                # drop depends on template shape at all: change the template's
                # columns and you change which of the model's cells survive.
                #
                # Reported once per ROW rather than once per key. The live run
                # (tests/harness/i4.py: 23 runs, 39 bands, 227 rows) produced
                # zero off-schema keys, including on 17 legitimately reworded
                # bands, so a per-key flag would have been affordable too — but
                # a row is the unit a reader can act on, and one flag naming
                # three lost keys is worth more than three naming one each.
                lost = [k for k in cells
                        if k not in headers and not str(k).startswith("_")
                        and k not in ("source", "page", "cells")
                        and str(cells.get(k) or "").strip()]
                if lost:
                    off_schema_keys += len(lost)
                    flagged.append(_flag(
                        f'{t["name"]}[unused keys]',
                        " | ".join(f"{k}={cells.get(k)}" for k in lost),
                        f"the model answered this row with column name(s) the "
                        f"table does not have ({', '.join(lost)}), so those "
                        f"values were not written. This table's columns are: "
                        f"{', '.join(headers)}"))
                row, row_conf = {}, confident
                unverified_cols = []
                row_why = []
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
                        unverified_cols.append(h)
                    if lvl not in CONFIDENT_LEVELS:
                        row_conf = LOW
                        _add(row_why, GROUNDING_FAILED if not ok
                             else CONTENT_CHECK_FAILED)
                        flagged.append(_flag(
                            f'{t["name"]}[{len(rows_out)}].{h}', v,
                            reason or why))
                if bands and t.get("orientation") != "columns":
                    line = (all_lines[line_no] if line_no is not None
                            else find_line(all_lines, source))
                    for bad_key, why in check_placement(
                            row, t.get("columns") or [], line, bands):
                        row_conf = LOW
                        _add(row_why, PLACEMENT_FAILED)
                        ungrounded += 1
                        misplaced += 1
                        flagged.append(_flag(
                            f'{t["name"]}[{len(rows_out)}].{bad_key}',
                            row.get(bad_key, ""), why))
                if not any(str(v).strip() for v in row.values()):
                    # I4 — VISIBLY. The gate STAYS: a row with nothing in any
                    # column this template has is not a row of this table, and
                    # emitting it would put a blank line into every sheet whose
                    # model returns a trailing empty object. What changes is
                    # that it used to go in silence — no flag, no note, no
                    # counter, no review state — which is the same fault the
                    # duplicate drop was fixed for. Nothing told the reader to
                    # go and look, and a template that silently loses a section
                    # total looks exactly like one that had none.
                    empty_rows += 1
                    shown = " | ".join(
                        f"{k}={v}" for k, v in cells.items()
                        if k not in ("source", "page", "cells")
                        and not str(k).startswith("_")
                        and str(v or "").strip()) or str(source)[:60]
                    flagged.append(_flag(
                        f'{t["name"]}[empty]', shown,
                        "row dropped: none of its values landed in a column "
                        "this table has, so every cell of it would be blank"))
                    notes.append(
                        f'{t["name"]}: dropped a row whose values fill none of '
                        f"this table's columns: {shown[:80]!r}")
                    continue
                row["_confidence"] = row_conf
                # I2 — the quote this row was read from and its file page.
                # Underscore keys are metadata to every reader of a row.
                row["_source"] = source
                row["_page"] = page_of(source, page, all_lines, page_lines,
                                       line_no)
                if unverified_cols:
                    row["_ungrounded"] = unverified_cols
                if row_why:
                    row_fail.append((row, row_why))
                rows_out.append(row)
            rows_out, totals = split_total_rows(rows_out, table_headers(t))
            for row in totals:
                shown = " | ".join(f"{k}={v}" for k, v in row.items()
                                   if not str(k).startswith("_") and str(v).strip())
                flagged.append(_flag(
                    f'{t["name"]}[total row]', shown,
                    "row left out: it is the table's own total — each of its "
                    "amounts equals the sum of the rows above it"))
                notes.append(f'{t["name"]}: left out its total line ({shown[:80]!r}); '
                             f"the arithmetic shows it sums the rows above it")
            total_rows += len(totals)
            rows_out, opening = split_opening_rows(
                rows_out, table_headers(t), extracted_fields.values())
            for row in opening:
                shown = " | ".join(f"{k}={v}" for k, v in row.items()
                                   if not str(k).startswith("_") and str(v).strip())
                notes.append(f'{t["name"]}: left out its opening-balance line '
                             f'({shown[:80]!r}); its amount is already in the '
                             f"sheet's own opening balance field")
            opening_rows += len(opening)
            # Run C, C4.1: the table's own total line returned as a row AND
            # filled into the template's total slot under the table. Dropped
            # only when the amounts agree, so the slot still holds it; said
            # in a note and counted. Disagreeing amounts are the validator's
            # (total_row_validators.total_row_mismatch): both kept, both low.
            rows_out, dup_totals = split_duplicate_totals(
                t, rows_out, slots["tables"], slots["fields"], extracted_fields)
            for row in dup_totals:
                shown = " | ".join(f"{k}={v}" for k, v in row.items()
                                   if not str(k).startswith("_") and str(v).strip())
                notes.append(f'{t["name"]}: left out a row repeating a total the '
                             f"sheet already holds in its own slot below the "
                             f"table ({shown[:80]!r})")
            duplicate_total_rows += len(dup_totals)
            # Run E, E9: a column filled by copying another column of the same
            # row (Memo = Description on every row, the page printing no memo)
            # is CLEARED — the document never said it — and said visibly, once
            # per column; the source column is untouched.
            for col, src in copied_columns(
                    rows_out, table_headers(t),
                    lambda h: bool(_lines_all) and AL.phrase_printed(_lines_all, h)):
                n = sum(1 for r in rows_out if str(r.get(col, "") or "").strip())
                for r in rows_out:
                    if str(r.get(col, "") or "").strip():
                        r[col] = ""
                copied_cols += 1
                flagged.append(_flag(
                    f'{t["name"]}[{col}]', "",
                    f"column cleared: on all {n} rows it held a copy of the same "
                    f"row's {src!r}, and the document prints no {col!r} of its "
                    f"own — fill it only from the document"))
                notes.append(f'{t["name"]}: cleared column {col!r} — every value '
                             f'was a copy of the same row\'s {src!r} ({n} rows)')
            tables_out[t["name"]] = rows_out
            row_counts[t["name"]] = len(rows_out)
            if len(rows_out) + len(totals) + len(dup_totals) < len(raw):
                incomplete.add(t["name"])

    # A TEMPLATE COLUMN THE DOCUMENT NEVER NAMES, BY ANY WORDING, THAT
    # NONETHELESS RECEIVED VALUES (I9, narrowed in Run B, B8). Only position
    # can have chosen what went there, and that is worth saying out loud.
    if unprinted_cols:
        filled = set()
        for t in slots["tables"]:
            for c in (t.get("columns") or []) + (t.get("fields") or []):
                key = c.get("key") or c.get("header")
                if any(str(r.get(key, "") or "").strip()
                       for r in tables_out.get(t["name"], [])):
                    filled.add(c.get("header"))
        for f in slots["fields"]:
            if f.get("col_header") and str(extracted_fields.get(f["ref"], "")).strip():
                filled.add(f["col_header"])
        hit = [h for h in unprinted_cols if h in filled]
        if hit:
            shown = ", ".join(repr(m) for m in hit[:6])
            notes.append(
                f"{len(hit)} template column heading(s) are not printed "
                f"anywhere in this document ({shown}) — values under them were "
                f"placed by position, not by what the heading means")
            flagged.append(_flag(
                "template columns", shown,
                "these column headings do not appear in the document, so "
                "nothing but position decided which source column filled them"))

    # ── CROSS-FIELD CHECKS, by document family (validators.py) ──
    # The family's registered validators, applied by one rule set: FAIL makes
    # each affected value exactly low with the check's reason; UNREADABLE adds
    # the reason and moves no level; PASS is evidence only. A family with
    # nothing registered runs nothing. Run after the tables, so a check may
    # read rows; a row is addressed `<table>_rows[i]`.
    check_notice, check_validation, check_review = {}, {}, False
    row_notice = []
    locale = template_locale(template_data)
    from rules import rules_of
    for res in run_checks(default_doc_type, CheckContext(
            slots["fields"], extracted_fields, pages,
            tables=slots["tables"], rows=tables_out, incomplete=incomplete,
            locale=locale, rules=rules_of(template_data),
            value_pages={ref: (field_prov.get(ref) or {}).get("page")
                         for ref in extracted_fields},
            page_numbers=page_numbers)):
        for ref, ev in res.evidence.items():
            if ref in field_prov:
                field_prov[ref].update(ev)
        for ref in res.slots:
            row = _row_at(tables_out, ref)
            if row is not None:
                if res.status == FAIL:
                    row["_confidence"] = LOW
                    hit = next((w for rr, w in row_fail if rr is row), None)
                    if hit is None:
                        row_fail.append((row, [res.reason]))
                    else:
                        _add(hit, res.reason)
                elif res.status == UNREADABLE:
                    row_notice.append((row, res.reason))
                continue
            if ref not in extracted_fields:
                continue
            if res.status == FAIL:
                conf_map[ref] = LOW
                failed(ref, res.reason)
            elif res.status == UNREADABLE:
                _add(check_notice.setdefault(ref, []), res.reason)
        flagged.extend(_flag(*f) for f in res.flags)
        notes.extend(res.notes)
        check_validation.update(res.validation)
        check_review = check_review or res.needs_review

    total_cells = len(extracted_fields) + sum(
        len([v for k, v in r.items() if not k.startswith("_") and str(v).strip()])
        for rows in tables_out.values() for r in rows)
    if merged_columns:
        notes.append(f"{merged_columns} value(s) run across a column gutter — "
                     f"two side-by-side blocks merged into one answer")
    if dropped:
        notes.append(f"{dropped} table row(s) were dropped as duplicates — see "
                     f"the flagged rows")
    if empty_rows:
        notes.append(f"{empty_rows} table row(s) were dropped because none of "
                     f"their values landed in a column the template has — see "
                     f"the flagged rows")
    if off_schema_keys:
        notes.append(f"{off_schema_keys} value(s) came back under a column "
                     f"name no table in this template has, and were not "
                     f"written — see the flagged rows")
    if misplaced:
        notes.append(f"{misplaced} value(s) sit under a different column "
                     f"in the document than the slot they were written to")
    if overprinted:
        notes.append(f"{overprinted} value(s) were read off a region where two "
                     f"texts are printed over one another — the string is the "
                     f"two of them interleaved, not anything the page prints")
    if unwitnessed:
        notes.append(f"{unwitnessed} value(s) are spelled by no run of words on "
                     f"the page — they were assembled from words that are not "
                     f"adjacent")
    _log("SLOT", f"filled {len(extracted_fields)}/{len(slots['fields'])} field slots, "
                 f"table rows {row_counts}, {ungrounded} ungrounded value(s), "
                 f"{misplaced} misplaced, {dropped} dropped, "
                 f"{empty_rows} empty, {off_schema_keys} off-schema key(s), "
                 f"{overprinted} overprinted, {unwitnessed} unwitnessed")

    # PAGE ORIGIN. Which page each graded value was read from, and so where its
    # text came from. Decided before the gates, which count the levels the
    # checks produced — not the levels the floor below replaces them with.
    origin_mode = bool(page_origins)
    if origin_mode:
        page_origins = {int(k): v for k, v in page_origins.items()}
        numbers = list(page_numbers or sorted(page_origins))
        page_text = {n: pages[i] for i, n in enumerate(numbers) if i < len(pages)}
        thin = {n for n in page_origins
                if len(str(page_text.get(n, "")).strip()) < 50}
        floored_pages = thin | {n for n, o in page_origins.items() if o != "native"}
        field_page = {ref: page_value_page(field_prov.get(ref), page_origins,
                                           all_lines)
                      for ref in conf_map}
        row_page = [(r, page_value_page({"page": r.get("_page"),
                                         "source": r.get("_source")},
                                        page_origins, all_lines))
                    for rows in tables_out.values() for r in rows]
        page_gates = {}
        for n in sorted(page_origins):
            levels = ([lv for ref, lv in conf_map.items() if field_page[ref] == n]
                      + [r.get("_confidence") for r, pg in row_page if pg == n])
            low_n = sum(1 for lv in levels if lv == LOW)
            ratio_n = (low_n / len(levels)) if levels else 0.0
            page_gates[n] = {
                "origin": page_origins[n],
                "graded_cells": len(levels),
                "low_confidence_cells": low_n,
                "low_confidence_ratio": round(ratio_n, 4),
                "review_gate": ratio_n > 0.30,
                "text_floor": n in thin,
            }

        def page_floored(pg):
            # A value nothing can place is floored whenever the document has
            # any floored page: unplaced is not the same as native.
            return pg in floored_pages if pg is not None else bool(floored_pages)

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
    if origin_mode:
        # THE FLOOR IS PER PAGE. A value read off a page whose text did not
        # come from the PDF's own text layer, or off a page with under 50
        # characters of text, is floored; a value read off a native page in the
        # same file keeps what its checks earned. It used to be one bit for the
        # whole file, so one scanned page took `high` from every digital page
        # beside it, and a blank scan floored a native page.
        conf_map = {ref: (origin_floor(lv) if page_floored(field_page[ref]) else lv)
                    for ref, lv in conf_map.items()}
        # Table rows were never floored at all: a row read off a scan kept
        # `high`. Same rule as a field.
        for r, pg in row_page:
            if page_floored(pg):
                r["_confidence"] = origin_floor(r["_confidence"])
        for origin, what in (("ocr", "no usable text layer — read by OCR, a "
                                     "machine's reading of the page image"),
                             ("pre_ocr", "the text layer is an embedded OCR "
                                         "layer (invisible text over a page "
                                         "image), a machine's reading rather "
                                         "than the document's own words")):
            those = sorted(n for n, o in page_origins.items() if o == origin)
            if those:
                notes.append(f"page {', '.join(map(str, those))}: {what}; "
                             f"values read from it are unverified")
        if floored_pages >= set(page_origins):
            overall = UNVERIFIED
        elif overall in CONFIDENT_LEVELS and (
                any(page_floored(pg) for pg in field_page.values())
                or any(page_floored(pg) for _r, pg in row_page)):
            overall = MEDIUM
    elif file_type in ("scanned_pdf", "image") or len(doc_text.strip()) < 50:
        # No text layer to check any span against. Every cell here was reported
        # as "medium" before Phase 8, which implied a verification that never
        # happened; UNVERIFIED says what is actually true.
        overall = UNVERIFIED
        notes.append("No text layer — spans could not be verified against the "
                     "document; values that passed their checks are "
                     "unverified, and values that failed them stay low")
        conf_map = {k: origin_floor(v) for k, v in conf_map.items()}
        for rows in tables_out.values():
            for r in rows:
                r["_confidence"] = origin_floor(r["_confidence"])

    # PER-VALUE ORIGIN AND REVIEW (Gate 2). On EVERY value, native or not, so
    # a reader never has to guess what an absent key means. The only reasons
    # recorded here are owed to origin; a native value carries none.
    if origin_mode:
        machine = [o for o in ("ocr", "pre_ocr") if o in page_origins.values()]

        def origin_of(pg):
            if pg is not None:
                return page_origins[pg]
            # Unplaced, in a document with machine-read pages: assume the
            # value is one of them. Unplaced is not native.
            return machine[0] if machine else "native"
    else:
        legacy_floored = (file_type in ("scanned_pdf", "image")
                          or len(doc_text.strip()) < 50)

        def origin_of(_pg):
            return "ocr" if legacy_floored else "native"

    value_origins = []
    for ref, p in field_prov.items():
        origin = origin_of(field_page.get(ref) if origin_mode else None)
        p["origin"] = origin
        p["review_required"], p["review_reasons"] = review_metadata(
            origin, field_fail.get(ref, []) + check_notice.get(ref, []))
        if ref in conf_map:
            value_origins.append(origin)
    for rows in tables_out.values():
        for r in rows:
            pg = next((pg for rr, pg in row_page if rr is r), None) \
                if origin_mode else None
            origin = origin_of(pg)
            r["_origin"] = origin
            r["_review_required"], r["_review_reasons"] = review_metadata(
                origin, list(next((w for rr, w in row_fail if rr is r), ()))
                + [why for rr, why in row_notice if rr is r])
            value_origins.append(origin)
    # ── COMPLETENESS (Run A, A3/A4) ──
    # The extraction against what the page holds. A slot the page shows a
    # value for and the extraction left empty is EMPTY AND FLAGGED; a slot
    # whose label the page does not print stays plain empty and is listed as
    # absent — GL Account and PO number must not make noise.
    cov = SI.coverage(inventory, slots, extracted_fields, tables_out,
                      parsed.get("fields"), page_lines or [], nums,
                      form_lane=bool(form_entries))
    label_of = {f["ref"]: f["row_label"] for f in slots["fields"]}
    # B6: the TOTAL cell carries both numbers. The slot holding the printed
    # total is flagged when the template has one; otherwise the table is.
    for m in cov.get("row_sums") or []:
        printed = {_number_key(p) for p in m["printed"]}
        ref = next((label_of[r] for r, v in extracted_fields.items()
                    if r in label_of and _number_key(v) in printed), None)
        flagged.append(_flag(
            ref or f'{m["table"]}[total]', ", ".join(m["printed"][:3]),
            f'the {m["rows"]} extracted rows sum to {m["row_sum"]} in column '
            f'{m["column"]!r}, but the page prints a total of '
            f'{", ".join(m["printed"][:3])} - a row may be missing or wrong'))
    for ref, why in cov["flag_slots"].items():
        flagged.append(_flag(label_of.get(ref, ref), "", f"{EMPTY_FLAGGED}: {why}"))
    attention = list(cov["reasons"])
    for n, why in sorted(page_failed.items()):
        attention.append(
            f"The field slots could not be extracted ({why}); only table rows "
            f"were read." if n == 0 else
            f"Page {n} could not be extracted ({why}); the table rows printed "
            f"on it are missing. The other pages were kept.")
    for fl in contract_after:
        if fl["kind"] in (C.MISSING_TABLE, C.EMPTY_TABLE):
            names = ", ".join(repr(x) for x in fl["tables"])
            attention.append(f"The model's answer did not include the rows of "
                             f"table {names}, and a second request did not "
                             f"return them either.")
    for name, rr in cov["rows"].items():
        for n in rr["no_matching_table"]:
            if len(nums) > 1:
                notes.append(f"no matching table on page {n} (table {name!r})")
    values_need_review = (
        bool(ungrounded) or review_gate or bool(dropped) or bool(merged_columns)
        or bool(regions_warned) or bool(empty_rows) or bool(off_schema_keys)
        or check_review or bool(cov["flag_slots"]))
    for t in attention:
        notes.append(f"NEEDS ATTENTION: {t}")

    needs_review = (bool(ungrounded) or bool(unanswered) or review_gate
                    or bool(dropped) or bool(merged_columns)
                    or bool(regions_warned)
                    or bool(empty_rows) or bool(off_schema_keys)
                    or bool(total_rows)
                    or check_review
                    # THE REVIEW INVARIANT: any value that requires review
                    # makes the document require review — every reason code,
                    # fields and rows alike, no exceptions (amount_unreadable
                    # used to be one). tests/test_review_invariant.py.
                    or any(field_prov[ref]["review_required"]
                           for ref in extracted_fields if ref in field_prov)
                    or any(r.get("_review_required")
                           for rows in tables_out.values() for r in rows)
                    # Scans always need review: a machine's reading is
                    # unverified however well it grounds, and a page that
                    # yielded nothing is a page nobody has read.
                    or any(o != "native" for o in value_origins)
                    or (origin_mode and any(o != "native"
                                            for o in page_origins.values())))

    r = DocumentExtractionResult(filename=file_path.name)
    r.document_type = default_doc_type
    r.success = True
    r.processing_time_ms = int((time.time() - start) * 1000)

    # The label-keyed projection. A label two slots share (a matrix template's
    # `Principal` under 2023 and under 2024) used to collapse to one entry, so
    # the second value vanished from everything that reads by label — the
    # results grid, the combined and per-file exports, the flat table. Such a
    # label is qualified by its column heading, or by its cell reference when
    # the heading does not separate it. A label used once is unchanged.
    label_uses = {}
    for f in slots["fields"]:
        label_uses[f["row_label"]] = label_uses.get(f["row_label"], 0) + 1
    kv = {}
    for ref, v in extracted_fields.items():
        slot = next((f for f in slots["fields"] if f["ref"] == ref), None)
        key = slot["row_label"] if slot else ref
        if slot and label_uses.get(key, 0) > 1:
            head = str(slot.get("col_header") or "").strip()
            key = f"{key} ({head})" if head else f"{key} [{ref}]"
        if key in kv:
            key = f"{key} [{ref}]"
        kv[key] = {"value": v, "confidence": conf_map.get(ref, confident), "ref": ref}

    ed = {
        "document_type": default_doc_type,
        "overall_confidence": overall,
        "extraction_method": "slot_directed",
        "layout_sections": {},
        "extracted_fields": extracted_fields,
        # Kept apart from `extracted_data`, which a cell edit overwrites whole.
        "field_provenance": {ref: field_prov[ref] for ref in extracted_fields
                             if ref in field_prov},
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
            "reanchored_count": reanchored,
            "overflow_entries": overflow,
            # B2.2: labels the page does not print word for word (information).
            "label_wording": AL.diagnostics(slots, all_lines),
            "opening_row_count": opening_rows,
            "duplicate_total_row_count": duplicate_total_rows,
            "copied_column_count": copied_cols,
            # What the family's validators record at document level
            # (routing_checksum, micr_band_unreadable, ...).
            **check_validation,
            "dropped_row_count": dropped,
            # I4 — a row dropped because none of its values reached a column
            # this template has, and the values discarded for being keyed with
            # a column name it does not have.
            "empty_row_count": empty_rows,
            # Part 3.5 — a table's own total line, left out on arithmetic
            "total_row_count": total_rows,
            "off_schema_key_count": off_schema_keys,
            # One entry per band that more than one region matched:
            # {table, pages, kept_page, kept_rows, left_out}.
            "regions": regions_warned,
            "unbound_row_count": sum(r["left_out"] for r in regions_warned),
            "merged_column_count": merged_columns,
            "overprinted_count": overprinted,
            "unwitnessed_count": unwitnessed,
            "low_confidence_cells": low_cells,
            "graded_cells": graded,
            "low_confidence_ratio": round(low_ratio, 4),
            "document_needs_review": review_gate,
            "grounded_count": max(0, total_cells - ungrounded),
            # {file page: origin} and {file page: that page's own gate}, for
            # the pages this result was extracted from.
            **({"page_origins": dict(page_origins), "page_gates": page_gates}
               if origin_mode else {}),
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
        # I5 — {cell_ref: {source, page}} for every inferred label the page
        # actually prints. Recorded, never required; a label the document does
        # not print simply has no entry. See extractor._label_provenance.
        "inferred_label_provenance": (
            (template_data or {}).get("inferred_label_provenance")
            if (template_data or {}).get("inferred") else None),
        "raw_llm_responses": [getattr(resp, "raw_text", "")] if resp else [],
    }
    for name, rows in tables_out.items():
        ed[f"{name}_rows"] = rows

    # ── STATE AND DIAGNOSTICS (Run A, A0/A4/A8) ──
    # READY: nothing outstanding. NEEDS_REVIEW: values to confirm.
    # NEEDS_ATTENTION: the page holds something the extraction does not — a
    # missing table or section, unplaced amounts, unread pages. FAILED is set
    # where the call itself failed, above. `needs_review` keeps its old
    # meaning for every older reader; `document_state` is the new truth.
    ed["attention"] = [{"id": f"att-{i + 1}", "text": t, "disposition": None}
                       for i, t in enumerate(attention)]
    ed["document_state"] = ("NEEDS_ATTENTION" if attention else
                            "NEEDS_REVIEW" if (values_need_review or any(
                                o != "native" for o in value_origins)) else
                            "READY")
    if attention:
        ed["needs_review"] = True
    usage = C.summarise(attempts)
    from_page = {}
    for ref, p in ed["field_provenance"].items():
        if p.get("page") is not None:
            from_page[p["page"]] = from_page.get(p["page"], 0) + 1
    for rows in tables_out.values():
        for row in rows:
            if row.get("_page") is not None:
                from_page[row["_page"]] = from_page.get(row["_page"], 0) + 1
    ledger = {}
    for n in nums:
        pg = inventory["pages"].get(n) or {}
        if pg.get("unreadable") or n in page_failed:
            ledger[str(n)] = "failed"
        elif from_page.get(n) or pg.get("amounts") or pg.get("widget_values")                 or pg.get("dated_rows") or pg.get("item_rows"):
            ledger[str(n)] = "processed"
        else:
            ledger[str(n)] = "processed_empty"
    ed["diagnostics"] = {
        "attempts": attempts,
        "usage": usage,
        "contract": {"first": contract_first, "after": contract_after,
                     "retried_slots": retry_ids, "retried_tables": retry_tables},
        "inventory": inventory["totals"],
        "coverage": {k: cov[k] for k in ("reasons", "flag_slots", "absent",
                                          "empty_bands", "widget_values",
                                          "widget_unplaced", "unplaced_amounts",
                                          "unplaced_amount_count", "rows")},
        "pages": ledger,
    }
    if resp is not None and usage["total_tokens"] is not None:
        # tokens_used is what the worker stores: every attempt of this
        # document, thinking tokens included.
        try:
            resp.tokens_used = usage["total_tokens"]
        except AttributeError:
            pass
    r.extracted_data = ed
    r.extraction_response = resp
    _log("RESULT", f"slot-directed: {len(kv)} fields, "
                   f"{sum(len(v) for v in tables_out.values())} table rows, {overall}")
    return [r]
