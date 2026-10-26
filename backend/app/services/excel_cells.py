"""Excel cell values, number formats, provenance comments, styles, widths and the review legend.

Moved verbatim from app/api/routes/extract.py (round 13); extract.py re-exports every name.
"""

import app.services.paths  # noqa: F401  (engine on sys.path)
from app.core.confidence import UNVERIFIED
import re
# --imports-end--


#: Excel column widths, in characters. The floor keeps a narrow column
#: readable; the ceiling stops one long note from pushing every other column
#: off the screen.
_MIN_COL_WIDTH = 8


_MAX_COL_WIDTH = 60


# DocAgentSpreadsheet.tsx's DCW — the width every column starts at.
_EDITOR_DEFAULT_COL_PX = 120


def _fit_columns(ws, col_widths=()):
    """Give EVERY written column a width (D14).

    Widths used to be applied before the writer ran, across
    `_find_template_dimensions`, which counts only cells carrying TEXT. Under
    the one rule a value column carries no text, so the extent was routinely
    narrower than the sheet the writer then filled — every column past it got
    no width at all and fell back to Excel's 8.43, truncating extracted values
    and the user's own labels. Which columns that hit depended on where the
    template happened to have headings, so it looked like auto-fit applying on
    some runs and not others.

    Running afterwards means the real extent is known: `ws.max_column` is what
    was actually written. The template's own stored width wins where there is
    one — it is the width the user dragged — and any column without one is
    fitted to its longest cell.
    """
    from openpyxl.utils import get_column_letter

    # A GRID SAVED BY THE OLD EDITOR DECLARES A WIDTH FOR EVERY COLUMN.
    # `colWidths` was initialised to Array(26).fill(120) and persisted verbatim,
    # so "the width the user dragged" was true of all 26 columns of every
    # template ever saved and the fit branch below was unreachable. The editor
    # now persists 0 for a column nobody touched; this handles the grids
    # already in the database, where a uniform array of the editor's own
    # default carries no per-column information and cannot be a choice.
    if col_widths:
        vals = [v for v in col_widths if v]
        if vals and len(set(vals)) == 1 and vals[0] == _EDITOR_DEFAULT_COL_PX:
            col_widths = ()

    for c in range(1, (ws.max_column or 0) + 1):
        stored = None
        if c - 1 < len(col_widths or []):
            try:
                px = float((col_widths or [])[c - 1] or 0)
                stored = round(px / 7) if px > 0 else None
            except (TypeError, ValueError):
                stored = None
        if stored:
            # Honoured as given. The clamp below exists to stop ONE long value
            # from dominating a sheet nobody sized; a width the user dragged is
            # not a guess to be corrected.
            width = stored
        else:
            longest = 0
            for r in range(1, (ws.max_row or 0) + 1):
                v = ws.cell(row=r, column=c).value
                if v is not None:
                    longest = max(longest, len(str(v)))
            width = max(_MIN_COL_WIDTH, min(_MAX_COL_WIDTH, longest + 2))
        ws.column_dimensions[get_column_letter(c)].width = width


def _calculate_layout(sections):
    """
    Dynamic row expansion + push-down planner. Generic for any template.

    sections: list of dicts (template order) with 0-based template rows:
      {section_label, header_row, template_start_row, template_end_row,
       extracted_rows, [total_row], [label_col_letter], [value_col_letter]}

    Side-by-side sections (sharing the same template_start_row) form ONE band and
    share the band's overflow (max over the band's sections). Each band's overflow
    pushes everything below it down.

    A4 (gap rows): every band except the last gets a "gap" of 1 when the template
    has NO blank row between this band's content (data rows + its own totals row)
    and the next band's section header. The gap shifts rows BELOW the band's
    content end (so a totals row directly under the band stays attached to it,
    while the next section header moves down one row).

    Returns layout_plan (same order as input):
      {section_label, header_row_actual, data_start_actual, data_end_actual,
       overflow, gap, content_end_row, template_start_row, template_end_row,
       label_col_letter, value_col_letter}
    """
    if not sections:
        return []
    starts = sorted({int(s["template_start_row"]) for s in sections})
    band = {}
    for start in starts:
        secs = [s for s in sections if int(s["template_start_row"]) == start]
        end = max(int(s["template_end_row"]) for s in secs)
        header = min(int(s.get("header_row", start - 1)) for s in secs)
        tpl_rows = max(1, end - start + 1)
        band_rows = max(int(s.get("extracted_rows", 0)) for s in secs)
        # Content end = last data row OR the band's own totals row directly below it.
        totals = [int(s["total_row"]) for s in secs
                  if s.get("total_row") is not None and int(s["total_row"]) > end]
        content_end = max([end] + totals)
        band[start] = {"end": end, "header": header, "content_end": content_end,
                       "overflow": max(0, band_rows - tpl_rows), "gap": 0}
    # A4 — insert a gap row before the next band's header when the template has
    # no blank row between this band's content end and that header.
    for i, start in enumerate(starts[:-1]):
        next_header = band[starts[i + 1]]["header"]
        if next_header <= band[start]["content_end"] + 1:
            band[start]["gap"] = 1
    # Cumulative shift applied to each band (overflow + gap of all bands above it).
    cum, shift_at = 0, {}
    for start in starts:
        shift_at[start] = cum
        cum += band[start]["overflow"] + band[start]["gap"]
    plan = []
    for s in sections:
        start = int(s["template_start_row"])
        b, above = band[start], shift_at[start]
        er = max(int(s.get("extracted_rows", 0)), 0)
        plan.append({
            "section_label":      s["section_label"],
            "label_col_letter":   s.get("label_col_letter", ""),
            "value_col_letter":   s.get("value_col_letter", ""),
            "header_row_actual":  b["header"] + above,
            "data_start_actual":  start + above,
            "data_end_actual":    start + above + er - 1,
            "overflow":           b["overflow"],
            "gap":                b["gap"],
            "content_end_row":    b["content_end"],
            "template_start_row": start,
            "template_end_row":   b["end"],
        })
    return plan


#: Words that make a cell an IDENTIFIER — something you quote, not something
#: you add up. Matched as whole words so "Paid" does not contain "id".
_ID_LABEL = re.compile(
    r"\b(id|ids|no|nos|num|number|#|code|ref|reference|nmls|ein|ssn|tin|itin"
    r"|routing|aba|account|acct|licen[cs]e|policy|serial|iban|swift|sort"
    r"|zip|postcode|postal|phone|tel|fax|mobile|mic|file|folio|batch)\b",
    re.I)


#: Words that make it a QUANTITY, and which WIN. "Account Balance" and
#: "Invoice Total" both contain an identifier word and are both numbers; a rule
#: that turns quantities into text is the mirror-image failure of the one it
#: fixes, and a Qty of 40 must stay a number.
_QTY_LABEL = re.compile(
    r"\b(amount|amt|total|subtotal|balance|qty|quantity|count|price|cost|rate"
    r"|sum|due|paid|payment|charge|fee|tax|discount|credit|debit|value|units"
    r"|hours|days|percent|pct)\b|%",
    re.I)


def labels_an_identifier(label) -> bool:
    """Does this cell's own label say its contents are an identifier?

    An NMLS ID of 222222 was exported as 222222.0: six digits, no leading
    zero, so the digit-shape rule below let it through as a quantity. No
    digit-shape rule can fix that on its own — 222222 is a perfectly ordinary
    number — but the column it sits in is headed "NMLS ID", and that settles
    it. The label is evidence the value does not carry.

    Quantity words WIN over identifier words, because the overlap is real and
    always resolves the same way: "Account Balance" and "Invoice Total" are
    money, "Account No" and "Invoice Number" are not.
    """
    text = str(label or "")
    if not text.strip():
        return False
    if _QTY_LABEL.search(text):
        return False
    return bool(_ID_LABEL.search(text))


def coerce_cell_value(value, label="", decimal_hint=None):
    """The value as it will actually appear in the spreadsheet cell.

    Money and numbers are written as NUMBERS: the currency symbol, thousands
    separators and accounting parentheses are notation, not content, so
    "$1,365,503" and "1,365,503" are the same cell. Anything that does not
    parse stays the string it was. Returns None for an empty value (write
    nothing).

    Public because the accuracy harness compares run-to-run stability with it.
    Two runs that differ only in how the model spelled a number produce an
    identical spreadsheet, and reporting that as an unstable field measures the
    model's formatting rather than its extraction.
    """
    if value is None or str(value).strip() == "":
        return None
    txt = str(value).strip()

    # IDENTIFIERS ARE NOT QUANTITIES. A bare run of digits with a leading zero,
    # or one longer than any realistic amount written without separators, is an
    # identifier — a routing number, an account number, a ZIP. Writing it as a
    # number silently CORRUPTS it: "021000021" becomes 21000021 and the leading
    # zero is gone, so the cheque exports a routing number that is not the
    # bank's. A quantity, by contrast, arrives with money notation on it (a
    # currency symbol, thousands separators, a decimal point, accounting
    # parentheses) or is short enough to be a count.
    # THE CELL'S OWN LABEL FIRST. A digit run in a cell headed "NMLS ID",
    # "Account No" or "Routing" is an identifier however short it is, and no
    # rule about digit shape can know that.
    if re.fullmatch(r"\d+", txt) and labels_an_identifier(label):
        return txt
    # Then the shape of the digits themselves, for a cell whose label says
    # nothing: a leading zero, or longer than any amount written without
    # separators.
    if re.fullmatch(r"\d+", txt) and (txt[0] == "0" or len(txt) >= 9):
        return txt

    # ONE PARSER (engine/amounts.py), in any locale. It used to strip every
    # comma and call float(): "1.234,56" became 1.23456 — a wrong number in
    # the client's file, silently. An amount whose notation is AMBIGUOUS
    # ("1,234" with nothing on the document to say which style it uses) stays
    # the text it was: a number cell must never hold a guess.
    from amounts import parse_amount
    a = parse_amount(txt, decimal_hint)
    if a.ok and not a.percent:
        return float(a.value)
    return txt


#: Excel number formats, by the notation the document actually used. Money
#: written in accounting parentheses keeps them; money written with a minus
#: sign keeps that.
_FMT_PLAIN = "#,##0"


def cell_format(value, label="", decimal_hint=None):
    """The Excel number format that reproduces how the document wrote it.

    `coerce_cell_value` deliberately writes money as a NUMBER, so the cell
    sums, sorts and charts. That is right, and it is also why the exported
    sheet lost the currency symbol and the trailing cents: "$7,750.00" became
    7750 on screen. A number format restores the notation without giving up
    the number — the cell still holds 7750.0, and still reads "$7,750.00".

    Deriving the format from the SOURCE STRING rather than from a setting is
    what keeps a multi-currency document honest: the symbol in the cell is the
    symbol that was printed on that line, not one chosen globally.

    Returns None when the value is not a number, or is an identifier held as
    text — a routing number has no format and must not acquire one.
    """
    if value is None:
        return None
    txt = str(value).strip()
    if not txt or coerce_cell_value(txt, label, decimal_hint) is None:
        return None
    if isinstance(coerce_cell_value(txt, label, decimal_hint), str):
        return None                       # identifier or free text

    from amounts import parse_amount
    a = parse_amount(txt, decimal_hint)
    sym = next((c for c in "$£€₹¥" if c in txt), "")
    accounting = txt.replace(sym, "").strip().startswith("(")
    frac = a.decimals
    # I6 — exactly as many decimals as the document printed. This used to floor
    # every count of 2 or more at 2, so a rate printed `$0.04116` displayed
    # `$0.04` and four others displayed `$0.00`: the cell held the full number,
    # but CSV, copy-as-values, print and anyone reading the sheet got the
    # rounded one, and nothing flagged it. Never fewer digits than the source,
    # and never more.
    base = f"#,##0.{'0' * frac}" if frac else _FMT_PLAIN
    if sym:
        base = f'"{sym}"{base}'
    if accounting:
        return f"{base}_);({base})"
    return base


#: Excel's own limit on the text of a cell comment.
_EXCEL_COMMENT_MAX = 32767


def provenance_note(source, page, filename, grounded=True, confidence=""):
    """The comment on an extracted value: the words it was read from, and where.

    The quote is shown as a quote only when it was verified against the
    document. Otherwise the comment says so first, because a hover reading like
    a verbatim quote is exactly the claim this must not make for a span that
    was never found.

    That is a statement about the QUOTE, not a confidence score. Confidence
    levels, flag reasons and review state stay in the app (test_confidence.py
    TestExportCarriesNoConfidence) — the file says where a value came from, not
    how sure the engine was.
    """
    quote = " ".join(str(source or "").split())
    where = f"{filename}, page {page}" if page else filename
    lines = []
    if confidence == UNVERIFIED:
        lines.append("Not checked: this document has no text layer, so the "
                     "quoted words could not be verified.")
    elif grounded is False:
        lines.append("Not verified: these words were not found in the document.")
    if quote:
        lines.append(f"“{quote}”")
    else:
        lines.append("No source words were quoted for this value.")
    lines.append(where)
    return "\n".join(lines)[:_EXCEL_COMMENT_MAX]


def provenance_edited_note(original, page, filename):
    """The comment on a value a person typed in place of the extracted one.

    It opens by saying what the value IS (typed, not read), then names what the
    document gave before, labelled as the replaced value, never as this cell's
    source.
    """
    where = f"{filename}, page {page}" if page else filename
    lines = ["Edited in DocAgent: typed by a person, not read from the document."]
    before = " ".join(str(original or "").split())
    lines.append(f"Replaced the extracted value “{before}” ({where})."
                 if before else f"No value had been extracted here ({where}).")
    return "\n".join(lines)[:_EXCEL_COMMENT_MAX]


def provenance_note_size(text):
    """(width, height) in points for a comment box that shows `text` whole.

    Excel draws a comment at a fixed box size and clips what does not fit, so
    the box is sized to the text. Presentation constants only: roughly 6pt per
    character of the default 9pt comment font, 13pt per line, a 360pt cap on
    width so a long quote wraps rather than running off the screen.
    """
    width = 360
    per_line = width // 6
    lines = sum(max(1, -(-len(ln) // per_line)) for ln in text.splitlines())
    return width, 13 * lines + 12


def _apply_template_merges(ws, merges, addr, band_rows, openpyxl_mod):
    """Re-create the template's merges at their shifted addresses.

    A merge is a RANGE, so it can only be re-created where the range still
    means the same thing. A merge crossing a band whose rows moved is SKIPPED:
    the writer expands a band to the document's row count, so the cells the
    range used to cover are not the cells it would cover now, and a merge
    landing on the wrong rows would hide real values behind a heading.
    """
    for key, span in (merges or {}).items():
        try:
            tr, tc = map(int, str(key).split(","))
            rows = max(1, int((span or {}).get("rows") or 1))
            cols = max(1, int((span or {}).get("cols") or 1))
        except (ValueError, AttributeError, TypeError):
            continue
        if rows == 1 and cols == 1:
            continue
        if any(r in band_rows for r in range(tr, tr + rows)):
            continue
        start, end = addr(tr, tc), addr(tr + rows - 1, tc + cols - 1)
        if not start or not end:
            continue
        try:
            ws.merge_cells(start_row=start[0], start_column=start[1],
                           end_row=end[0], end_column=end[1])
        except Exception:
            continue


def _review_status_unknown(value):
    """The status of a value the export computed itself (a template formula
    evaluated by the legacy form writer): no level, so it owes a look."""
    from app.core import review as _review
    return _review.value_status(value, None)


def _add_anomalies_sheet(wb, doc_results, demo=False):
    """An "Anomalies" sheet when the option ran (Part A3): rule, severity,
    rows, numbers and the sentence, per document. Informational: no value's
    mark changes because of an anomaly."""
    rows = []
    for d in doc_results:
        ed = d.get_extracted_data()
        for a in (ed.get("anomalies") if isinstance(ed, dict) else None) or []:
            if isinstance(a, dict):
                rows.append(["" if demo else (getattr(d, "filename", "") or ""),
                             a.get("severity", ""), a.get("rule", ""), a.get("message", ""),
                             ", ".join(a.get("rows") or []),
                             "; ".join(f"{k}={v}" for k, v in (a.get("numbers") or {}).items())])
    if not rows:
        return
    ws = wb.create_sheet("Anomalies")
    ws.append(["Document", "Severity", "Rule", "What", "Rows", "Numbers"])
    for r in rows:
        ws.append(r)
    for col, w in zip("ABCDEF", (28, 10, 22, 70, 30, 40)):
        ws.column_dimensions[col].width = w


def _add_categories_sheet(wb, doc_results, demo=False):
    """A "Categories" sheet when the categorization option ran (Part A2):
    one row per categorized table row, the category cell marked exactly as
    any other value (a model guess or "Uncategorized" is filled and
    explained). Categories are never written into the results sheet's own
    cells: the document did not print them."""
    from app.core import review as _review
    from app.core.export_marks import SheetMarks
    rows = []
    for d in doc_results:
        ed = d.get_extracted_data()
        if isinstance(ed, dict):
            name = "" if demo else (getattr(d, "filename", "") or "")
            rows += [(name, v) for v in _review.category_values(ed, _review.document_reviewed(ed))]
    if not rows:
        return
    ws = wb.create_sheet("Categories")
    ws.append(["Document", "Table", "Row", "Category", "How it was assigned"])
    sm = SheetMarks(ws)
    for name, v in rows:
        ws.append([name, v["table"], v["row"] + 1, v["value"], v["source"]])
        sm.mark(ws.cell(row=ws.max_row, column=4), v)
    sm.finish()
    for col, w in zip("ABCDE", (28, 14, 6, 22, 48)):
        ws.column_dimensions[col].width = w


def _add_review_legend(wb, doc_results, demo=False):
    """A "Legend" sheet: how many values need review, what each mark means,
    and one line per document. Added to every export, whichever writer drew
    the results sheet, so even a sheet with no per-cell marks (a legacy job,
    the image fallback) says how much of it is unchecked."""
    from openpyxl.styles import Font, PatternFill
    from app.core import review as _review
    _add_categories_sheet(wb, doc_results, demo=demo)
    _add_anomalies_sheet(wb, doc_results, demo=demo)
    lg = wb.create_sheet("Legend")
    per_doc, total = [], {"values": 0, "needs_review": 0, "low": 0,
                          "unverified": 0, "empty_flagged": 0}
    for d in doc_results:
        ed = d.get_extracted_data()
        s = _review.summarise(_review.export_values(ed if isinstance(ed, dict) else {}))
        failed = not isinstance(ed, dict) or not ed
        per_doc.append((d, s, failed))
        for k in total:
            total[k] += s[k]
    n = total["needs_review"]
    lg["A1"] = (f"{n} value{'' if n == 1 else 's'} need{'s' if n == 1 else ''} review"
                if n else "Nothing needs review")
    lg["A1"].font = Font(bold=True, size=13)
    lg["A2"] = (f"{total['low']} low · {total['unverified']} unverified · "
                f"{total['empty_flagged']} empty and flagged · "
                f"{total['values']} values in all")
    lg["A4"] = "Mark"
    lg["B4"] = "Meaning"
    lg["A4"].font = lg["B4"].font = Font(bold=True)
    r = 5
    for name, fill, meaning in _review.LEGEND:
        lg.cell(row=r, column=1, value=name)
        if fill:
            lg.cell(row=r, column=1).fill = PatternFill(fill_type="solid", fgColor=fill)
        lg.cell(row=r, column=2, value=meaning)
        r += 1
    lg.cell(row=r, column=2, value="Each marked cell carries a comment naming its "
                                   "status and the reasons.")
    r += 2
    for col, head in enumerate(("Document", "Values", "Need review", "Low",
                                "Unverified", "Empty, flagged"), 1):
        lg.cell(row=r, column=col, value=head).font = Font(bold=True)
    for i, (d, s, failed) in enumerate(per_doc, 1):
        r += 1
        name = (f"document {i}" if demo else (d.filename or f"document {i}"))
        if failed:
            name += " — FAILED, no values extracted"
        for col, v in enumerate((name, s["values"], s["needs_review"], s["low"],
                                 s["unverified"], s["empty_flagged"]), 1):
            lg.cell(row=r, column=col, value=v)
    lg.column_dimensions["A"].width = 40
    lg.column_dimensions["B"].width = 90
    return n


def _marks_or_off(ws, marks):
    """The writer's SheetMarks, or one that marks nothing (a direct caller)."""
    if marks is not None:
        return marks
    from app.core.export_marks import SheetMarks
    return SheetMarks(ws, enabled=False)


def _ref_to_rowcol(ref):
    """'B12' -> (11, 1) 0-based, or None."""
    m = re.fullmatch(r"([A-Za-z]+)(\d+)", str(ref).strip())
    if not m:
        return None
    col = 0
    for ch in m.group(1).upper():
        col = col * 26 + (ord(ch) - 64)
    return int(m.group(2)) - 1, col - 1


def _parse_hex_color(hex_color):
    if not hex_color: return None
    h = hex_color.lstrip("#")
    if len(h)==3: h="".join(ch*2 for ch in h)
    return f"FF{h.upper()}" if len(h)==6 else None


def _apply_cell_style(xl_cell, style, _openpyxl_mod):
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    fk = {}
    if style.get("bold"): fk["bold"]=True
    if style.get("italic"): fk["italic"]=True
    if style.get("underline"): fk["underline"]="single"
    if style.get("fontSize"): fk["size"]=style["fontSize"]
    if style.get("fontFamily"): fk["name"]=style["fontFamily"]
    fc = _parse_hex_color(style.get("fontColor"))
    if fc: fk["color"]=fc
    if fk:
        try: xl_cell.font = Font(**fk)
        except Exception: pass
    bg = _parse_hex_color(style.get("bgColor"))
    if bg:
        try: xl_cell.fill = PatternFill(fill_type="solid", fgColor=bg)
        except Exception: pass
    try:
        xl_cell.alignment = Alignment(
            horizontal={"left":"left","center":"center","right":"right"}.get(style.get("align",""),"left"),
            wrap_text=bool(style.get("wrap")), vertical="center"
        )
    except Exception: pass
    if style.get("borderAll"):
        t = Side(style="thin")
        try: xl_cell.border = Border(left=t,right=t,top=t,bottom=t)
        except Exception: pass


def _find_template_dimensions(cells):
    """Bounding box of the template's CONTENT cells only (non-empty value,
    extract target, or merge). The spreadsheet editor keeps style-only and
    cleared cells ({value:""}) in the saved grid — counting those inflated the
    box to the full 50x26 editor canvas and made the writers materialize dozens
    of empty (None) columns in the exported Excel (bug A6)."""
    max_r, max_c = 0, 0
    for key, cell in cells.items():
        parts = key.split(",")
        if len(parts) != 2:
            continue
        try:
            r, c = int(parts[0]), int(parts[1])
        except (ValueError, TypeError):
            continue
        if isinstance(cell, dict) and not (
                str(cell.get("value") or "").strip()
                or cell.get("extractTarget")
                or cell.get("mergeSpan") or cell.get("mergeParent")):
            continue
        max_r = max(max_r, r); max_c = max(max_c, c)
    return max_r, max_c
