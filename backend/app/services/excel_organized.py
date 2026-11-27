"""Organized layout writer (Run R, Part 2, v1) - docs/ORGANIZED_LAYOUT_SPEC.md.

Writes `engine/organized_layout.layout()` onto a worksheet: each cell at the
row and column the page puts it, with the page's bold / italic / size,
headers centred, money and dates typed, no fills. OFF by default: reached
only through `GET /api/jobs/{id}/export?layout=organized` and
tools/organized_export.py; the default export never calls it.
"""
from __future__ import annotations

import app.services.paths  # noqa: F401  (engine on sys.path)


def write_layout(ws, lay, filename=None, start_row=1):
    """Writes every page of `lay` from `start_row` (1-based); one blank row
    between pages. Returns the next free row."""
    from openpyxl.styles import Alignment, Border, Font, Side
    r0 = start_row
    max_col = 0
    for cells in lay.get("pages") or []:
        last = 0
        for c in cells:
            cell = ws.cell(row=r0 + c["row"], column=c["col"] + 1, value=c["value"])
            if isinstance(c["value"], str) and (c.get("as_text") or c["value"][:1] in ("=", "+", "-", "@")):
                # Run T1, 3e: printed text beginning = + - @ is TEXT, never a
                # formula (stored as a string, with Excel's quote prefix)
                cell.data_type = "s"
                cell.quotePrefix = True
            cell.font = Font(bold=bool(c.get("bold")), italic=bool(c.get("italic")),
                             underline="single" if c.get("underline") else None,
                             size=c.get("size") or 11)
            if c.get("border_bottom") == "thick":
                cell.border = Border(bottom=Side(style="thick"))
            if c.get("number_format"):
                cell.number_format = c["number_format"]
            if c.get("align"):
                cell.alignment = Alignment(horizontal=c["align"])
            last = max(last, c["row"])
            max_col = max(max_col, c["col"] + 1)
        r0 += last + 2
    if filename:
        fc = ws.cell(row=start_row, column=max_col + 1, value=filename)
        fc.font = Font(bold=True)
    _fit(ws)
    return r0


def _fit(ws):
    from openpyxl.utils import get_column_letter
    widths = {}
    for row in ws.iter_rows():
        for c in row:
            if c.value is None:
                continue
            n = len(c.value.strftime("%m/%d/%Y")) if hasattr(c.value, "strftime") \
                else len(f"{c.value:,.2f}") if isinstance(c.value, float) else len(str(c.value))
            size = (c.font.sz or 11) if c.font else 11
            widths[c.column] = max(widths.get(c.column, 0), n * size / 11 + 2)
    for col, w in widths.items():
        ws.column_dimensions[get_column_letter(col)].width = max(8, min(60, w))


def organized_workbook(sources):
    """sources: [(display name, pdf path or None)]. One sheet per document
    the layout can read; the rest are listed on a 'Not organized' sheet with
    the reason (a scan, a missing file), never silently dropped."""
    return organized_result(sources)[0]


# Why a document was not laid out, as a code the UI can name in words.
SOURCE_MISSING, NO_TEXT_LAYER, UNREADABLE = "source_missing", "no_text_layer", "unreadable"


def organized_result(sources):
    """`organized_workbook`, plus what the route needs to answer honestly:
    (workbook, documents laid out, [(name, code, reason)] not laid out)."""
    import openpyxl
    from organized_layout import layout
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    missed, laid_out = [], 0
    for name, path in sources:
        if path is None:
            missed.append((name, SOURCE_MISSING, "the source file is no longer stored"))
            continue
        if not str(path).lower().endswith(".pdf"):
            missed.append((name, NO_TEXT_LAYER, "not a PDF: an image has no text layer to lay out"))
            continue
        try:
            lay = layout(path)
        except Exception as e:                    # one document, never the file
            missed.append((name, UNREADABLE, f"could not be read ({type(e).__name__})"))
            continue
        if not lay["pages"]:
            missed.append((name, NO_TEXT_LAYER, "; ".join(lay["skipped"]) or "no text layer"))
            continue
        title = (str(name).rsplit(".", 1)[0] or "Document")[:31]
        base, k = title, 2
        while title in wb.sheetnames:
            title = f"{base[:28]} {k}"
            k += 1
        ws = wb.create_sheet(title)
        write_layout(ws, lay, filename=name)
        laid_out += 1
        for why in lay["skipped"]:
            missed.append((name, NO_TEXT_LAYER, why))
    if missed:
        ws = wb.create_sheet("Not organized")
        ws.cell(row=1, column=1, value="Not laid out from the page").font =             openpyxl.styles.Font(bold=True)
        for i, (name, _code, why) in enumerate(missed, 2):
            ws.cell(row=i, column=1, value=name)
            ws.cell(row=i, column=2, value=why)
    if not wb.sheetnames:
        wb.create_sheet("Not organized")
    return wb, laid_out, missed


# ── Run T1, 3h: the structure layout behind ?layout=organized ────────────────

NO_PERCEPTION = "no_perception"


def structure_result(sources):
    """sources: [(display name, DocumentResult or None, pdf path or None)].
    (workbook, documents laid out, [(name, code, reason)] not laid out).

    Each document's page is read from its STORED perception (2f) - the
    uploaded file is only a fallback for records stored before Run T1 -
    and laid out by engine/structure_engine: compact per-region grids,
    one header row per table, from the stored model plan when there is
    one, else from geometry. A `Layout check` sheet says, per page, which
    plan was used, every flag verification raised, and every printed line
    left out with its reason."""
    import openpyxl
    from openpyxl.styles import Font
    import structure_engine as S
    from app.services import perception_store as PS
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    missed, laid_out, checks = [], 0, []
    for name, doc, path in sources:
        perc = PS.stored(doc) if doc is not None else None
        if perc is None:
            if path is None:
                missed.append((name, SOURCE_MISSING,
                               "the source file is no longer stored"))
                continue
            if not str(path).lower().endswith(".pdf"):
                missed.append((name, NO_TEXT_LAYER,
                               "not a PDF: an image has no text layer to lay out"))
                continue
            try:
                import perception as P
                perc = P.read_document(path)
            except Exception as e:
                missed.append((name, UNREADABLE, f"could not be read ({type(e).__name__})"))
                continue
        try:
            lay = S.layout_document(perc, plans=S.stored_plans(perc))
        except Exception as e:                    # one document, never the file
            missed.append((name, UNREADABLE, f"could not be laid out ({type(e).__name__})"))
            continue
        if not lay["pages"]:
            missed.append((name, NO_TEXT_LAYER, "; ".join(lay["skipped"]) or "no text layer"))
            continue
        title = (str(name).rsplit(".", 1)[0] or "Document")[:31]
        base, k = title, 2
        while title in wb.sheetnames:
            title = f"{base[:28]} {k}"
            k += 1
        ws = wb.create_sheet(title)
        write_layout(ws, lay, filename=name)
        laid_out += 1
        for why in lay["skipped"]:
            missed.append((name, NO_TEXT_LAYER, why))
        checks.append((name, lay))
    if checks:
        ws = wb.create_sheet("Layout check")
        ws.cell(row=1, column=1, value="Document").font = Font(bold=True)
        ws.cell(row=1, column=2, value="What").font = Font(bold=True)
        ws.cell(row=1, column=3, value="Detail").font = Font(bold=True)
        r = 2
        for name, lay in checks:
            for pg, src in sorted(lay["plan_source"].items()):
                ws.cell(row=r, column=1, value=name)
                ws.cell(row=r, column=2, value=f"page {pg} plan")
                ws.cell(row=r, column=3, value="model plan, checked against the geometry"
                        if src == "model" else "from the page's geometry (no model plan)")
                r += 1
            for f in lay["flags"]:
                ws.cell(row=r, column=1, value=name)
                ws.cell(row=r, column=2, value="check")
                ws.cell(row=r, column=3, value=f)
                r += 1
            for e in lay["excluded"]:
                ws.cell(row=r, column=1, value=name)
                ws.cell(row=r, column=2, value=f"left out (page {e.get('page')})")
                c = ws.cell(row=r, column=3, value=f"{e['text']} - {e['reason']}")
                if str(e["text"])[:1] in ("=", "+", "-", "@"):
                    c.data_type = "s"
                r += 1
    if missed:
        ws = wb.create_sheet("Not organized")
        ws.cell(row=1, column=1, value="Not laid out from the page").font = Font(bold=True)
        for i, (name, _code, why) in enumerate(missed, 2):
            ws.cell(row=i, column=1, value=name)
            ws.cell(row=i, column=2, value=why)
    if not wb.sheetnames:
        wb.create_sheet("Not organized")
    return wb, laid_out, missed
