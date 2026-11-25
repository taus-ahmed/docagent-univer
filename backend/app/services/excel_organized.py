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
    from openpyxl.styles import Alignment, Font
    r0 = start_row
    max_col = 0
    for cells in lay.get("pages") or []:
        last = 0
        for c in cells:
            cell = ws.cell(row=r0 + c["row"], column=c["col"] + 1, value=c["value"])
            cell.font = Font(bold=bool(c.get("bold")), italic=bool(c.get("italic")),
                             size=c.get("size") or 11)
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
    import openpyxl
    from organized_layout import layout
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    missed = []
    for name, path in sources:
        if path is None:
            missed.append((name, "the source file is no longer stored"))
            continue
        if not str(path).lower().endswith(".pdf"):
            missed.append((name, "not a PDF: an image has no text layer to lay out"))
            continue
        try:
            lay = layout(path)
        except Exception as e:                    # one document, never the file
            missed.append((name, f"could not be read ({type(e).__name__})"))
            continue
        if not lay["pages"]:
            missed.append((name, "; ".join(lay["skipped"]) or "no text layer"))
            continue
        title = (str(name).rsplit(".", 1)[0] or "Document")[:31]
        base, k = title, 2
        while title in wb.sheetnames:
            title = f"{base[:28]} {k}"
            k += 1
        ws = wb.create_sheet(title)
        write_layout(ws, lay, filename=name)
        for why in lay["skipped"]:
            missed.append((name, why))
    if missed:
        ws = wb.create_sheet("Not organized")
        ws.cell(row=1, column=1, value="Not laid out from the page").font = \
            __import__("openpyxl").styles.Font(bold=True)
        for i, (name, why) in enumerate(missed, 2):
            ws.cell(row=i, column=1, value=name)
            ws.cell(row=i, column=2, value=why)
    if not wb.sheetnames:
        wb.create_sheet("Not organized")
    return wb
