"""The slot writer, the inferred-sheet writer and the export dispatcher `_write_excel`.

Moved verbatim from app/api/routes/extract.py (round 13); extract.py re-exports every name.
"""

import app.services.paths  # noqa: F401  (engine on sys.path)
from app.services.excel_cells import _apply_cell_style
from app.services.excel_cells import _apply_template_merges
from app.services.excel_cells import _find_template_dimensions
from app.services.excel_cells import _fit_columns
from app.services.excel_cells import _ref_to_rowcol
from app.services.excel_legacy import _write_form_excel
from app.services.excel_legacy import _write_layout_excel
from app.services.excel_legacy import _write_mixed_excel
from app.services.excel_legacy import _write_table_excel
from app.services.excel_cells import cell_format
from app.services.excel_cells import coerce_cell_value
from app.services.excel_cells import keep_precision_note
from app.services.excel_cells import money_hint
from app.services.excel_cells import precision_flag
from app.services.excel_cells import us_money_document
from app.services.excel_cells import DATE_FORMAT, date_note, date_order_of, excel_date
from app.services.excel_cells import provenance_edited_note
from app.services.excel_cells import provenance_note
from app.services.excel_cells import provenance_note_size
import re
from template_shape import cells_text_of, placeholder_at
from row_groups import rows_with_subtotals
# --imports-end--


def _with_subtotals(ed):
    """Run R, R1: the document as the writer sees it - each grouped band's
    rows with its printed subtotals interleaved. The stored rows are never
    changed: every check, count and sum reads `<band>_rows` without them."""
    if not isinstance(ed, dict) or not any(k.endswith("_subtotals") for k in ed):
        return ed
    out = dict(ed)
    for k in ed:
        if k.endswith("_subtotals"):
            name = k[: -len("_subtotals")]
            out[f"{name}_rows"] = rows_with_subtotals(ed, name)
    return out


#: Blank rows between two documents' blocks on one sheet (Run C, C1.3). The
#: same for every template and every row count, so a reader — or a formula —
#: can find the next block without guessing.
GAP_BETWEEN_DOCS = 3

#: The header strip opening each document's block (Run C, C1.2): its fill,
#: used only on a strip cell the template gave no fill of its own.
STRIP_FILL = "FFE7E9EE"

#: Labels that name a document's own number, for the header strip. Matched
#: against the slot's row label; the first one holding a value wins.
_DOC_NUMBER_LABEL = re.compile(
    r"\b(invoice|statement|cheque|check|receipt|order|po|document|doc|bill|"
    r"payslip|pay\s*slip|voucher|reference|ref)\b.*\b(no|number|num|#|id)\b"
    r"|\b(invoice|po|cheque|check|statement)\s*#", re.I)


def document_number_of(ed) -> tuple[str, str]:
    """(label, value) of the document's own number when a slot holds one."""
    if not isinstance(ed, dict):
        return "", ""
    fields = ed.get("extracted_fields") or {}
    for f in (ed.get("slot_map") or {}).get("fields") or []:
        label = str(f.get("row_label") or "")
        value = str(fields.get(f.get("ref"), "") or "").strip()
        if value and _DOC_NUMBER_LABEL.search(label):
            return label, value
    return "", ""


def _write_excel(ws, doc_results, sheet_data, template_regions, openpyxl_mod,
                 provenance=True, marks=True, audit=False,
                 show_filename=True):
    """Route to the correct writer based on template regions primary_mode.
    Always uses the template structure for routing — never relies on AI output
    flags which can be stale or wrong from a previous extraction run."""
    cells_tpl = sheet_data.get("cells", {})
    col_widths = sheet_data.get("colWidths", [])
    max_r, max_c = _find_template_dimensions(cells_tpl)

    # Deterministic writer routing that mirrors the extraction routing.
    # The authoritative signal is the template_type saved in extraction_json:
    #   structural        -> layout writer
    #   labeled | mixed   -> form/mixed/table writer (by primary_mode)
    #   (no template/flat is handled by the export endpoint via _write_flat_table)
    # Legacy jobs (extracted before template_type was persisted) carry no
    # template_type — fall back to the previous behaviour (layout_sections present
    # -> layout writer) so already-extracted balance sheets still export correctly.
    def _has_layout(d):
        ed = d.get_extracted_data()
        ls = ed.get("layout_sections") if isinstance(ed, dict) else None
        return isinstance(ls, dict) and any(
            isinstance(s, dict) and s.get("rows") for s in ls.values()
        )

    template_type = ""
    for d in doc_results:
        ed = d.get_extracted_data()
        if isinstance(ed, dict) and ed.get("template_type"):
            template_type = ed["template_type"]
            break

    primary_mode = (template_regions or {}).get("primary_mode", "form_kv")

    if template_type == "slot":
        print("[EXPORT] routing: template_type=slot -> slot writer "
              "(values written to the addresses they were requested for)", flush=True)
        _write_slot_excel(ws, doc_results, sheet_data, cells_tpl, openpyxl_mod,
                          provenance=provenance, marks=marks, audit=audit,
                          show_filename=show_filename)
        _fit_columns(ws, col_widths)
        return
    # Every other writer marks through one SheetMarks (app/core/export_marks):
    # the same fills, comments and Review status column as the slot writer.
    from app.core.export_marks import SheetMarks
    sm = SheetMarks(ws, enabled=marks, status_column=audit)
    if template_type == "structural":
        print("[EXPORT] routing: template_type=structural -> layout-mode writer", flush=True)
        _write_layout_excel(ws, doc_results, sheet_data, cells_tpl, openpyxl_mod,
                            marks=sm)
        sm.finish()
        _fit_columns(ws, col_widths)
        return
    if template_type in ("labeled", "mixed"):
        # field path — never the layout writer, even if a stale layout_sections exists
        print(f"[EXPORT] routing: template_type={template_type} -> "
              f"form/mixed/table writer (primary_mode={primary_mode})", flush=True)
    else:
        # legacy (no template_type) — preserve prior layout-detection behaviour
        if any(_has_layout(d) for d in doc_results):
            print("[EXPORT] routing: layout-mode writer (legacy layout_sections)", flush=True)
            _write_layout_excel(ws, doc_results, sheet_data, cells_tpl, openpyxl_mod,
                                marks=sm)
            sm.finish()
            _fit_columns(ws, col_widths)
            return
        print(f"[EXPORT] routing: legacy primary_mode={primary_mode}", flush=True)

    if primary_mode == "table":
        _write_table_excel(ws, doc_results, sheet_data, cells_tpl, template_regions, openpyxl_mod,
                           marks=sm)
    elif primary_mode == "mixed":
        _write_mixed_excel(ws, doc_results, sheet_data, cells_tpl, max_r, max_c, template_regions, openpyxl_mod,
                           marks=sm)
    else:
        # form_with_targets, form_kv, two_column — all use form writer
        _write_form_excel(ws, doc_results, sheet_data, cells_tpl, max_r, max_c, openpyxl_mod,
                          marks=sm)
    sm.finish()
    _fit_columns(ws, col_widths)


def _write_inferred_sheets(wb, ws, doc_results, openpyxl_mod, provenance=True,
                           marks=True, audit=False, show_filename=True):
    """Phase 3 — export a job that ran with no template, using the template the
    engine inferred for each document.

    Documents whose inferred shape matches share ONE sheet and stack in it;
    genuinely different shapes get their own sheet. Never one sheet per
    document when the shapes match. Returns False if nothing was inferred.
    """
    groups = {}
    for d in doc_results:
        ed = d.get_extracted_data()
        if not isinstance(ed, dict):
            continue
        grid = ed.get("inferred_grid")
        if not (isinstance(grid, dict) and grid.get("cells")):
            continue
        sig = ed.get("shape_signature") or "shape"
        groups.setdefault(sig, {"grid": grid, "docs": [],
                                "title": (ed.get("inferred_template") or {}).get("title", "")})
        groups[sig]["docs"].append(d)
    if not groups:
        return False

    used_titles = set()

    def _sheet_title(raw, idx):
        base = re.sub(r"[\\/*?:\[\]]", " ", str(raw or "")).strip() or f"Sheet {idx}"
        base = base[:28] or f"Sheet {idx}"
        title, n = base, 2
        while title.casefold() in used_titles:
            title = f"{base[:25]} {n}"
            n += 1
        used_titles.add(title.casefold())
        return title

    print(f"[EXPORT] no template: {len(doc_results)} document(s) share "
          f"{len(groups)} inferred shape(s)", flush=True)

    for i, (sig, g) in enumerate(groups.items()):
        sheet = ws if i == 0 else wb.create_sheet()
        sheet.title = _sheet_title(g["title"], i + 1)
        # the sheet's title is a template or document title: its index only
        print(f"[EXPORT]   shape {sig}: {len(g['docs'])} document(s) "
              f"-> sheet {i + 1}", flush=True)
        _write_slot_excel(sheet, g["docs"], g["grid"], g["grid"].get("cells", {}),
                          openpyxl_mod, provenance=provenance, marks=marks,
                          audit=audit, show_filename=show_filename)
    return True


def _document_hint_of(ed):
    """The decimal separator a stored result's own numbers agree on, or None."""
    from app.services.excel_cells import document_hint_of
    return document_hint_of(ed)


def _interior_rows(t, cells_tpl) -> dict:
    """{template row: [(col, text)]} for static text typed inside a row
    band's own cells (a subtotal line drawn within the table)."""
    cols = [c["col"] for c in t.get("columns") or []]
    if not cols:
        return {}
    out = {}
    for key, cell_def in (cells_tpl or {}).items():
        if not isinstance(cell_def, dict) or cell_def.get("mergeParent"):
            continue
        try:
            r, c = map(int, str(key).split(","))
        except ValueError:
            continue
        text = str(cell_def.get("value") or "").strip()
        if (t["start_row"] <= r <= t["end_row"] and min(cols) <= c <= max(cols)
                and text and not placeholder_at(cells_text_of(cells_tpl), r, c)):
            out.setdefault(r, []).append((c, text))
    return out


def _band_layout(t, n, interior) -> list:
    """The rows a band is written as: ("rec", k) for record k, ("static", r)
    for the interior template row r. Template rows are walked in order; an
    interior row keeps its place, each record takes the next free row,
    unused free rows are dropped, and records beyond them follow."""
    out, k = [], 0
    for r in range(t["start_row"], t["end_row"] + 1):
        if r in interior:
            out.append(("static", r))
        elif k < n:
            out.append(("rec", k))
            k += 1
    out += [("rec", i) for i in range(k, n)]
    return out


def _template_slot_map(sheet_data) -> dict:
    """The slot map the template itself implies (no values): what a document
    with no stored slot map is laid out with."""
    try:
        from slot_extractor import _table_map, enumerate_slots
        slots = enumerate_slots(sheet_data or {})
    except Exception:
        return {}
    return {"fields": [{k: f.get(k) for k in ("slot_id", "ref", "row_label", "section")}
                       for f in slots.get("fields") or []],
            "tables": [_table_map(t) for t in slots.get("tables") or []]}


def _dress_block(ws, top, height, max_c, ed, filename, index, show_name,
                 slot_map, thick, spare_col):
    """The header strip on a block's first row and the closing border under
    its last (C1.2). `top` is the 0-based output row of the block's first row.

    The strip names the source file and, when a slot holds it, the document's
    own number. It is written into the rightmost EMPTY cell of the first row
    that is not a slot and lies right of everything the template typed there,
    so it never covers a label or a value; with no such cell it goes one
    column past everything the export writes. A demo export (`show_name`
    false) names the block by its position instead of the stored temp name.
    """
    from copy import copy
    from openpyxl.cell import MergedCell
    from openpyxl.styles import PatternFill

    def strip(cell):
        font, border = copy(cell.font), copy(cell.border)
        font.bold, border.top = True, thick
        cell.font, cell.border = font, border
        if cell.fill is None or cell.fill.fill_type is None:
            cell.fill = PatternFill(fill_type="solid", fgColor=STRIP_FILL)

    r0, r1 = top + 1, top + height                 # 1-based, inclusive
    for c in range(1, max_c + 2):
        cell = ws.cell(row=r0, column=c)
        if not isinstance(cell, MergedCell):
            strip(cell)
    for c in range(1, max_c + 2):
        cell = ws.cell(row=r1, column=c)
        if not isinstance(cell, MergedCell):
            border = copy(cell.border)
            border.bottom = thick
            cell.border = border

    label, number = document_number_of(ed)
    name = filename if (show_name and filename) else f"Document {index}"
    text = f"{name} · {label} {number}" if number else name
    slot_cols = set()
    for f in slot_map.get("fields") or []:
        rc = _ref_to_rowcol(f.get("ref", ""))
        if rc and rc[0] == 0:
            slot_cols.add(rc[1] + 1)
    typed = [c for c in range(1, max_c + 2)
             if ws.cell(row=r0, column=c).value not in (None, "")]
    for c in range(max_c + 1, 0, -1):
        cell = ws.cell(row=r0, column=c)
        if typed and c <= max(typed):
            break
        if isinstance(cell, MergedCell) or c in slot_cols or cell.value not in (None, ""):
            continue
        cell.value = text
        return
    cell = ws.cell(row=r0, column=spare_col + 1)
    if not isinstance(cell, MergedCell) and cell.value in (None, ""):
        cell.value = text
        strip(cell)


def _write_slot_excel(ws, doc_results, sheet_data, cells_tpl, openpyxl_mod,
                      provenance=False, marks=True, audit=None,
                      show_filename=True):
    """
    Writer for slot-directed extraction.

    There is no placement logic here, and that is the point: every value was
    requested for a specific address and is written to that address. The only
    computed thing is the row shift: a band is written with the document's
    ACTUAL row count (Run C, C1), so rows below it move down when there are
    more rows than the template reserved and UP when there are fewer — unused
    reserved rows are not written and the totals block sits directly under the
    last real row. Blank rows the template draws OUTSIDE a band are kept.

    BLOCKS (C1). Each document is one block: its first row is the header
    strip (bold, a fill where the template gave none, a thick top border)
    carrying the source file name and the document's own number when a slot
    holds one; a thick bottom border closes it; GAP_BETWEEN_DOCS blank rows
    separate blocks. The strip is the template's own first row rather than a
    row inserted above it, so a value is at the same address in a one-document
    export as in the template.

    AUDIT COLUMNS (C2). The Source and Review status columns are written only
    when `audit` is true. `audit=None` follows `provenance`, so a caller that
    asks for provenance explicitly gets today's export unchanged; the download
    route passes `audit` explicitly (its `include_audit` parameter).

    REVIEW MARKS (`marks`, on by default). An export must never present a
    value a person still owes a look — unverified, low, empty and flagged, or
    carrying `review_required` — as a clean final value. Each such cell gets a
    fill and a comment naming its status and reasons (app/core/review.py, the
    same classification the review screen uses); an edited or reviewed value
    gets its own fill. A "Review status" column right of the sheet says, per
    row, whether anything in it needs review, and its header counts the
    values that do. Returns that count.

    It also carries provenance (I2), unless `provenance=False`: a Source column
    right of the template naming the document and file page of every row that
    holds extracted values, and a comment on every extracted value quoting the
    words it was read from. "Values only" meant a merged block, a wrong region
    or a second document arrived with nothing saying where it came from, and
    the file is where an accountant checks a figure. A job stored before this
    carries no provenance and exports exactly as it did.
    """
    from openpyxl.cell import MergedCell

    # The sheet's extent is the static text PLUS every slot the shape found.
    # _find_template_dimensions counts only cells that carry text, which was
    # right when an empty value cell was flagged extractTarget. Under the one
    # rule (text = label, empty = slot) a value cell carries neither text nor a
    # flag, so a template whose value column has no heading — a plain list of
    # "Label | <empty>" rows — collapsed to column A and every extracted value
    # was dropped at export. The slots say where the values go, so they define
    # the extent alongside the labels.
    max_r, max_c = _find_template_dimensions(cells_tpl)
    # A merge is part of the extent too. `_find_template_dimensions` counts
    # content cells, and a heading merged across A:D has content only in A —
    # so the sheet stopped short of the range and the merge was dropped for
    # being outside it. `template_shape._used_range` already widens for merges
    # on the shape side; this is the same fact on the writer side.
    for key, span in (sheet_data.get("merges") or {}).items():
        try:
            mr, mc = map(int, str(key).split(","))
            max_r = max(max_r, mr + max(1, int((span or {}).get("rows") or 1)) - 1)
            max_c = max(max_c, mc + max(1, int((span or {}).get("cols") or 1)) - 1)
        except (ValueError, AttributeError, TypeError):
            continue
    for doc in doc_results:
        ed = _with_subtotals(doc.get_extracted_data())
        if not isinstance(ed, dict):
            continue
        sm = ed.get("slot_map") or {}
        for f in sm.get("fields") or []:
            rc = _ref_to_rowcol(f.get("ref", ""))
            if rc:
                max_r, max_c = max(max_r, rc[0]), max(max_c, rc[1])
        for t in sm.get("tables") or []:
            max_r = max(max_r, int(t.get("end_row", 0)))
            if t.get("orientation") == "columns":
                # A transposed table overflows SIDEWAYS: more records than the
                # template drew columns for widens the sheet instead of
                # lengthening it.
                records = len(ed.get(f"{t['name']}_rows") or [])
                max_c = max(max_c, int(t.get("start_col", 0)) + max(records - 1, 0),
                            int(t.get("end_col", 0)))
            for col in t.get("columns") or []:
                max_c = max(max_c, int(col.get("col", 0)))

    if audit is None:
        audit = bool(provenance)
    show_source = bool(provenance and audit)
    show_status = bool(marks and audit)
    doc_offset = 0
    # I2 — the Source column sits one past the template's full extent, so it
    # can never land on a cell the template or a band owns.
    source_col = max_c + 1
    # The Review status column comes after it (or takes its place when the
    # export carries no Source column).
    status_col = source_col + 1 if show_source else source_col
    from openpyxl.styles import Side
    _thick = Side(style="thick", color="FF1E2130")
    doc_index = 0
    from app.core import review as _review
    row_status = {}           # output row -> [status word, ...]
    unresolved_total = 0

    #: the decimal separator the document being written uses, from its own
    #: unambiguous numbers (engine/amounts.document_hint); per document.
    doc_hint = [None]
    doc_us = [False]          # Run E, E14: the document writes money the US way
    doc_order = [None]        # Run G, G6: the day/month order the record fixes

    def put(r, c, value, label=""):
        cell = ws.cell(row=r + 1, column=c + 1)
        if isinstance(cell, MergedCell):
            return None
        # G6: a date slot holding one unambiguous date is a real date
        d, note = excel_date(value, label, doc_order[0])
        if d is not None:
            cell.value = d
            cell.number_format = DATE_FORMAT
            return cell
        if note:
            cell.value = str(value).strip()
            date_note(cell, note)
            return cell
        hint = money_hint(label, doc_hint[0], doc_us[0], value)
        out = coerce_cell_value(value, label, hint)
        if out is not None:
            cell.value = out
            # D8 — the cell keeps the number AND the notation the document
            # printed it with. Without this the export drops the currency
            # symbol and the trailing cents, which is what an accountant
            # actually looks at.
            fmt = cell_format(value, label, hint)
            if fmt:
                cell.number_format = fmt
            precision_flag(cell, value, hint)
            return cell
        return None

    for doc in doc_results:
        ed = _with_subtotals(doc.get_extracted_data())
        doc_hint[0] = _document_hint_of(ed)
        doc_us[0] = us_money_document(ed)
        doc_order[0] = date_order_of(ed)
        if not isinstance(ed, dict):
            continue
        slot_map = ed.get("slot_map") or {}
        if not slot_map:
            # Run D, D12: a document that FAILED stores no slot map. Its block
            # is still the template's, laid out with the template's own tables
            # holding no rows — not the reserved rows of a template nobody
            # filled.
            slot_map = _template_slot_map(sheet_data)
        tables = slot_map.get("tables") or []
        fields = ed.get("extracted_fields") or {}

        filename = str(getattr(doc, "filename", "") or "")
        field_prov = ed.get("field_provenance") or {}
        conf_map = (ed.get("validation") or {}).get("confidence_map") or {}
        source_rows = {}          # output row -> set of pages
        doc_reviewed = _review.document_reviewed(ed)
        flagged_refs = {str(f.get("ref")) for f in
                        ((ed.get("validation") or {}).get("flagged_fields") or [])
                        if isinstance(f, dict)}

        def mark(cell, r, c, st):
            """The review mark on one written value (see the docstring)."""
            nonlocal unresolved_total
            if not marks:
                return
            if not st["resolved"]:
                unresolved_total += 1
            m = _review.export_mark(st)
            if r is not None:
                row_status.setdefault(r, []).append(m[0] if m else "OK")
            if m is None:
                return
            if cell is None:
                cell = ws.cell(row=r + 1, column=c + 1) if r is not None else None
                if cell is None or isinstance(cell, MergedCell):
                    return
            from openpyxl.comments import Comment
            from openpyxl.styles import PatternFill
            if m[1]:
                cell.fill = PatternFill(fill_type="solid", fgColor=m[1])
            if m[2] is None:
                return            # a corrected value: final, no warning note
            if st["status"] == "edited" and cell.comment:
                return            # the edited note already says so, and what it replaced
            text = m[2] + (f"\n\n{cell.comment.text}" if cell.comment else "")
            w, h = provenance_note_size(text)
            cell.comment = Comment(text, "DocAgent", width=w, height=h)

        def attach(cell, source, page, grounded, confidence, out_r,
                   edited=False, original=""):
            """The comment on one written value, and its row's Source entry.

            An EDITED value was typed by a person. It gets a comment saying so
            and naming what it replaced, never the replaced words presented as
            its source, and its page does not go into the row's Source cell:
            the value did not come from that page.
            """
            if not provenance or cell is None or not filename:
                return
            from openpyxl.comments import Comment
            if edited:
                text = provenance_edited_note(original, page, filename)
            else:
                text = provenance_note(source, page, filename, grounded=grounded,
                                       confidence=confidence)
            text = keep_precision_note(cell, text)
            w, h = provenance_note_size(text)
            cell.comment = Comment(text, "DocAgent", width=w, height=h)
            if out_r is not None:
                source_rows.setdefault(out_r, set()).update(
                    {page} if page and not edited else set())

        # how far each template row moves, given the band's ACTUAL row count
        # (C1): down when the document has more rows than were reserved, UP
        # when it has fewer — the unused reserved rows are not written. A
        # document with two lines has two; nothing is invented to fill the
        # space. A transposed table never moves rows — it grows to the right —
        # so it contributes no shift.
        #
        # Run D, D7: bands that SHARE ROWS (two tables side by side) are one
        # group. The rows below the group move by the group's LARGEST change,
        # so when the left table grows and the right does not, both stay on
        # their own rows and nothing below lands inside the longer one.
        # Run D, D12 (T11): a static row typed INSIDE a table (`Subtotal |
        # =SUM(...)`) keeps its place; records are written around it. Each
        # table's written rows are `layouts[name]`, in order.
        layouts = {}
        for t in tables:
            if t.get("orientation") == "columns":
                continue
            n = len(ed.get(f"{t['name']}_rows") or [])
            layouts[t["name"]] = _band_layout(t, n, _interior_rows(t, cells_tpl))
        groups = []                     # [[first row, end row, delta]]
        for t in tables:
            if t.get("orientation") == "columns":
                continue
            band = t["end_row"] - t["start_row"] + 1
            grown = len(layouts[t["name"]])
            top = t.get("header_row", t["start_row"])
            g = next((g for g in groups if top <= g[1] and t["end_row"] >= g[0]), None)
            if g is None:
                groups.append([top, t["end_row"], grown - band])
            else:
                g[0], g[1] = min(g[0], top), max(g[1], t["end_row"])
                g[2] = max(g[2], grown - band)
        shifts = [(end, delta) for _top, end, delta in groups]

        def out_row(tr):
            return tr + sum(ov for end, ov in shifts if tr > end)

        # Cells the table itself will fill, which must not also get static text.
        # A row-oriented band owns whole rows; a transposed one owns only its
        # record columns — its heading column IS the template's static labels
        # and has to survive.
        band_rows, band_cells = set(), set()
        for t in tables:
            if t.get("orientation") == "columns":
                band_cells.update(
                    (r, c) for r in range(t["start_row"], t["end_row"] + 1)
                    for c in range(t["start_col"], max_c + 1))
            else:
                band_rows.update(range(t["start_row"], t["end_row"] + 1))
                # Run D, D8: a row band owns its OWN COLUMNS on its rows; a
                # field drawn beside it on those rows is written like any other
                cols = [c["col"] for c in t.get("columns") or []]
                if cols:
                    band_cells.update(
                        (r, c) for r in range(t["start_row"], t["end_row"] + 1)
                        for c in range(min(cols), max(cols) + 1))
                else:
                    band_cells.update((r, c) for r in range(t["start_row"], t["end_row"] + 1)
                                      for c in range(0, max_c + 1))

        # 1. static template text, at its shifted position
        for key, cell_def in cells_tpl.items():
            if not isinstance(cell_def, dict) or cell_def.get("mergeParent"):
                continue
            try:
                tr, tc = map(int, str(key).split(","))
            except ValueError:
                continue
            if tr > max_r or tc > max_c or (tr, tc) in band_cells:
                continue
            text = str(cell_def.get("value") or "").strip()
            # Run D, D11: a placeholder (`[enter name]`, `____`, `TBD`) marks a
            # slot; it is replaced by the value, never copied into the export.
            if text and not placeholder_at(cells_text_of(cells_tpl), tr, tc):
                put(doc_offset + out_row(tr), tc, text)

        # 1b. THE LOOK — including inside a band.
        #
        # Style used to be applied in the loop above, which `continue`s past
        # every band row before it gets there. A TABLE TEMPLATE BORDERS ITS
        # BODY: the band is the part of the sheet a user draws a box around,
        # and it was the one part that arrived unstyled. D13 was verified on a
        # form template, which has no band, so the gap was invisible.
        #
        # The look travels with a cell whether or not it holds text — a
        # bordered empty value cell is a box the user drew, and it is the cells
        # WITHOUT text that the slots fill.
        styles = {}
        for key, cell_def in cells_tpl.items():
            if not isinstance(cell_def, dict) or cell_def.get("mergeParent"):
                continue
            try:
                tr, tc = map(int, str(key).split(","))
            except ValueError:
                continue
            if cell_def.get("style"):
                styles[(tr, tc)] = cell_def["style"]

        def dress(out_r, out_c, src):
            st = styles.get(src)
            if not st:
                return
            cell = ws.cell(row=doc_offset + out_r + 1, column=out_c + 1)
            if not isinstance(cell, MergedCell):
                _apply_cell_style(cell, st, openpyxl_mod)

        for (tr, tc) in styles:
            if tr > max_r or tc > max_c:
                continue
            if (tr, tc) in band_cells:
                continue
            dress(out_row(tr), tc, (tr, tc))

        # A band takes the document's row count, so the rows the user drew
        # are not the rows that get written. Each drawn row keeps its own look;
        # rows BEYOND what was drawn take the look of the band's FIRST body
        # row, because that is the row the user drew as "a row of this table".
        # Repeating the LAST one instead would stamp a closing bottom border
        # onto every overflow row and draw the table as a stack of one-row
        # boxes. Reserved rows the document does not fill are not written, so
        # they are not dressed either (C1).
        for t in tables:
            rows_n = len(ed.get(f"{t['name']}_rows") or [])
            if t.get("orientation") == "columns":
                first, last = t["start_col"], t["end_col"]
                for i in range(max(last - first + 1, rows_n)):
                    src_c = first + i if i <= last - first else first
                    for r in range(t["start_row"], t["end_row"] + 1):
                        dress(out_row(r), first + i, (r, src_c))
                continue
            height = t["end_row"] - t["start_row"] + 1
            cols = [c["col"] for c in t.get("columns") or []]
            span = range(min(cols), max(cols) + 1) if cols else range(0, max_c + 1)
            base = out_row(t["start_row"] - 1) + 1
            interior = _interior_rows(t, cells_tpl)
            if interior:
                # D12 (T11): the layout keeps each interior row where it was
                # drawn — its text and its look — and records fill the rest
                free = [r for r in range(t["start_row"], t["end_row"] + 1)
                        if r not in interior] or [t["start_row"]]
                for j, (kind, v) in enumerate(layouts[t["name"]]):
                    src_r = v if kind == "static" else free[v if v < len(free) else 0]
                    for c in span:
                        dress(base + j, c, (src_r, c))
                    if kind == "static":
                        for c, text in interior[v]:
                            put(doc_offset + base + j, c, text)
                continue
            for i in range(rows_n):
                src_r = t["start_row"] + (i if i < height else 0)
                if i == rows_n - 1 and rows_n < height:
                    src_r = t["end_row"]      # the drawn closing row, border and all
                for c in span:              # the band's own columns (D8)
                    dress(base + i, c, (src_r, c))

        # 2. field slots, each at the exact address it was asked for
        slot_label = {f.get("ref"): f.get("row_label", "")
                      for f in (slot_map.get("fields") or [])}
        # B4 (overnight): EVERY slot, not only the ones holding a value. An
        # empty slot the engine flagged is counted in the Legend as "empty and
        # flagged" and must be the grey cell, with its comment, that the
        # Legend describes (job 48 said 12 and showed none).
        all_refs = list(fields) + [r for r in slot_label if r and r not in fields]
        for ref in all_refs:
            value = fields.get(ref, "")
            rc = _ref_to_rowcol(ref)
            if rc is None:
                continue
            tr, tc = rc
            if tr > max_r or tc > max_c:
                continue
            out_r = doc_offset + out_row(tr)
            cell = put(out_r, tc, value, slot_label.get(ref, ""))
            prov = field_prov.get(ref)
            if prov:
                attach(cell, prov.get("source"), prov.get("page"),
                       prov.get("grounded"), conf_map.get(ref), out_r,
                       edited=bool(prov.get("edited")) or conf_map.get(ref) == "edited",
                       original=prov.get("original_value", ""))
            p = prov or {}
            mark(cell, out_r, tc, _review.value_status(
                value, conf_map.get(ref), review_required=bool(p.get("review_required")),
                reasons=p.get("review_reasons") or [],
                flagged=slot_label.get(ref, "") in flagged_refs or ref in flagged_refs,
                reviewed=doc_reviewed or bool(p.get("reviewed")),
                disposition=_review._mark_disposition(p.get("reviewed"))))

        # 3. table rows, in their band, by column header address
        for t in tables:
            rows = ed.get(f"{t['name']}_rows") or []
            if t.get("orientation") == "columns":
                # Transposed: record i is a COLUMN, each field a fixed row. A
                # record has no row of its own for a Source cell, so its
                # provenance travels in the comments only.
                for i, rec in enumerate(rows):
                    c = t["start_col"] + i
                    for f in t.get("fields") or []:
                        cell = put(doc_offset + out_row(f["row"]), c,
                                   rec.get(f["header"], ""), f.get("header", ""))
                        if "_source" in rec:
                            attach(cell, rec.get("_source"), rec.get("_page"),
                                   f["header"] not in (rec.get("_ungrounded") or []),
                                   rec.get("_confidence"), None,
                                   edited=f["header"] in (rec.get("_edited") or []),
                                   original=(rec.get("_original") or {}).get(f["header"], ""))
                        if cell is not None:
                            mark(cell, None, c, _review.value_status(
                            rec.get(f["header"], ""),
                            "edited" if f["header"] in (rec.get("_edited") or []) else (
                                "low" if f["header"] in (rec.get("_ungrounded") or [])
                                else rec.get("_confidence")),
                            review_required=bool(rec.get("_review_required")),
                            reasons=rec.get("_review_reasons") or [],
                            reviewed=(doc_reviewed or bool(rec.get("_reviewed"))
                                      or bool(_review.cell_mark(rec, f["header"]))),
                            disposition=_review._mark_disposition(
                                _review.cell_mark(rec, f["header"]))))
                continue
            header_row = t.get("header_row", t["start_row"])
            if show_source and rows and header_row < t["start_row"] and any(
                    "_source" in r for r in rows):
                hc = ws.cell(row=doc_offset + out_row(header_row) + 1,
                             column=source_col + 1)
                if not isinstance(hc, MergedCell) and hc.value is None:
                    hc.value = "Source"
            at = {v: j for j, (kind, v) in enumerate(layouts.get(t["name"]) or [])
                  if kind == "rec"}
            for i, row in enumerate(rows):
                # placed from the row ABOVE the band: a band reserving no rows (D12)
                # has start_row past end_row, and must not move by its own growth;
                # an interior static row keeps its place (`layouts`)
                r = doc_offset + out_row(t["start_row"] - 1) + 1 + at.get(i, i)
                for col in t["columns"]:
                    key = col.get("key") or col["header"]
                    cell = put(r, col["col"], row.get(key, ""), col.get("header", ""))
                    if "_source" in row:
                        attach(cell, row.get("_source"), row.get("_page"),
                               key not in (row.get("_ungrounded") or []),
                               row.get("_confidence"), r,
                               edited=key in (row.get("_edited") or []),
                               original=(row.get("_original") or {}).get(key, ""))
                    st = _review.value_status(
                            row.get(key, ""),
                            "edited" if key in (row.get("_edited") or []) else (
                                "low" if key in (row.get("_ungrounded") or [])
                                else row.get("_confidence")),
                            review_required=bool(row.get("_review_required")),
                            reasons=row.get("_review_reasons") or [],
                            reviewed=(doc_reviewed or bool(row.get("_reviewed"))
                                      or bool(_review.cell_mark(row, key))),
                            disposition=_review._mark_disposition(_review.cell_mark(row, key)))
                    if cell is not None:
                        mark(cell, r, col["col"], st)
                    if cell is not None and row.get("_subtotal"):
                        from copy import copy as _copy
                        _f = _copy(cell.font)
                        _f.bold = True
                        cell.font = _f

        # 3b. one Source cell per row that received a value with provenance
        for out_r, pages in (source_rows.items() if show_source else ()):
            sc = ws.cell(row=out_r + 1, column=source_col + 1)
            if isinstance(sc, MergedCell) or sc.value is not None:
                continue
            shown = sorted(pages)
            sc.value = (f"{filename} · p.{', '.join(str(p) for p in shown)}"
                        if shown else filename)

        # 4. the template's own merges, last, so nothing is written into a
        #    cell that a merge has since swallowed
        def _addr(tr, tc):
            if tr > max_r or tc > max_c:
                return None
            return (doc_offset + out_row(tr) + 1, tc + 1)

        _apply_template_merges(ws, sheet_data.get("merges"), _addr, band_rows,
                               openpyxl_mod)
        # Run E, E4 (C1): a ONE-ROW merge wholly inside a row band's body
        # (`B4:C4` widening an entry cell) describes a row of the table, so it
        # is re-created on every record row written — never over a cell
        # holding a value, which a merge would erase.
        for t in tables:
            if t.get("orientation") == "columns":
                continue
            recs = ed.get(f"{t['name']}_rows") or []
            at = {v: j for j, (kind, v) in enumerate(layouts.get(t["name"]) or [])
                  if kind == "rec"}
            for key, span in (sheet_data.get("merges") or {}).items():
                try:
                    tr, tc = map(int, str(key).split(","))
                    nr = int((span or {}).get("rows") or 1)
                    nc = int((span or {}).get("cols") or 1)
                except (ValueError, AttributeError, TypeError):
                    continue
                if nr != 1 or nc < 2 or tc + nc - 1 > max_c:
                    continue
                if not (t["start_row"] <= tr <= t["end_row"]):
                    continue
                for i in range(len(recs)):
                    r = doc_offset + out_row(t["start_row"] - 1) + 1 + at.get(i, i)
                    if any(ws.cell(row=r + 1, column=c + 1).value not in (None, "")
                           for c in range(tc + 1, tc + nc)):
                        continue
                    try:
                        ws.merge_cells(start_row=r + 1, start_column=tc + 1,
                                       end_row=r + 1, end_column=tc + nc)
                    except Exception:
                        continue

        block_height = max(1, max_r + 1 + sum(ov for _, ov in shifts))
        doc_index += 1
        _dress_block(ws, doc_offset, block_height, max_c, ed, filename,
                     doc_index, show_filename, slot_map, _thick,
                     spare_col=max_c + 1 + int(show_source) + int(show_status))
        doc_offset += block_height + GAP_BETWEEN_DOCS

    # 5. the Review status column: a header counting what needs review, and
    #    one word per row that received a value
    if show_status:
        head = (f"Review status — {unresolved_total} value"
                f"{'' if unresolved_total == 1 else 's'} need"
                f"{'s' if unresolved_total == 1 else ''} review"
                if unresolved_total else "Review status — nothing needs review")
        for r, words in sorted(row_status.items()):
            word = next((w for w in ("Needs review", "Edited", "Reviewed")
                         if w in words), "OK")
            if r == 0:
                head += f" (row 1: {word})"
                continue
            sc = ws.cell(row=r + 1, column=status_col + 1)
            if not isinstance(sc, MergedCell) and sc.value is None:
                sc.value = word
        hc = ws.cell(row=1, column=status_col + 1)
        if not isinstance(hc, MergedCell):
            hc.value = head
    return unresolved_total
