"""
Read a written .xlsx back into the flat gold shape.

The harness scored the engine's in-memory result and nothing read the file the
user actually receives. That gap hid a real bug: an export that produced 34
correct labels and 34 empty cells while extraction held all 34 values. Scoring
the FILE closes it — if extraction accuracy and export accuracy diverge, the
writer is wrong, and it shows up in the same run.

The reader deliberately takes nothing from the engine's output. It is given the
template's shape (where labels and bands are meant to be) and then reads what is
actually in the cells, locating rows by their printed label text rather than by
coordinate, so a band that pushed rows down is still read correctly.
"""
from __future__ import annotations

import re
from types import SimpleNamespace


def _txt(v):
    return "" if v is None else str(v).strip()


def _norm(s):
    return re.sub(r"[^a-z0-9]+", "", str(s or "").casefold())


def _label_column(shape):
    """The column the template puts row labels in (usually A)."""
    cols = shape.get("label_columns") or [0]
    return min(cols) if cols else 0


def read_sheet(ws, shape):
    """Worksheet + template shape -> {"fields": {...}, "tables": {...}}.

    Fields are located by their label text, not by row number, so the reader
    survives a band that expanded and pushed everything below it down.
    """
    fields, tables = {}, {}
    if not shape:
        return {"fields": fields, "tables": tables}

    # index every cell by row
    rows = {}
    for row in ws.iter_rows():
        for c in row:
            if c.value is not None and _txt(c.value) != "":
                rows.setdefault(c.row - 1, {})[c.column - 1] = c.value

    # Where each band must STOP. The writer lays sections out contiguously, so
    # a band runs until the sheet shows something that is not one of its rows:
    # a blank line, the next band's heading, or a labelled field such as a
    # section total. Reading to the next blank line alone would let the first
    # band swallow the rest of the sheet.
    lcol0 = _label_column(shape)
    stops = {_norm(f["row_label"]) for f in (shape.get("field_slots") or [])
             if _txt(f.get("row_label"))}
    for b in shape.get("repeat_bands") or []:
        for c in b["columns"]:
            if _txt(c.get("header")):
                stops.add(_norm(c["header"]))
        for f in b.get("fields") or []:
            if _txt(f.get("header")):
                stops.add(_norm(f["header"]))

    # ── bands: find the header row by its printed headings ──
    band_rows = set()
    for band in shape.get("repeat_bands") or []:
        if band.get("orientation") == "columns":
            # A TRANSPOSED band runs sideways: its headings are printed down a
            # column and each record is a column. Read it the same way — locate
            # each heading by its text, then walk across — so the file is still
            # checked against gold that knows nothing about orientation.
            hcol = band["header_col"]
            rows_for = {}
            for f in band.get("fields") or []:
                want = _norm(f.get("header"))
                if not want:
                    continue
                for r in sorted(rows):
                    if r in band_rows or r in rows_for.values():
                        continue
                    if _norm(rows[r].get(hcol)) == want:
                        rows_for[f["header"]] = r
                        break
            if not rows_for:
                continue
            band_rows.update(rows_for.values())
            # A record may be blank in one field, so the record columns are the
            # union across every heading row, not just the first.
            cols = sorted({c for r in rows_for.values() for c in rows[r]
                           if c > hcol})
            out = []
            for c in cols:
                rec = {h: rows[r].get(c, "") for h, r in rows_for.items()}
                if any(_txt(v) for v in rec.values()):
                    out.append(rec)
            if out:
                tables[band["name"]] = out
            continue
        headers = [(c["col"], _txt(c["header"])) for c in band["columns"]]
        if not headers:
            continue
        hdr_row = None
        for r in sorted(rows):
            if r in band_rows:
                continue
            if all(_norm(rows[r].get(col)) == _norm(h) for col, h in headers if h):
                hdr_row = r
                break
        if hdr_row is None:
            continue
        band_rows.add(hdr_row)
        out = []
        r = hdr_row + 1
        # How far down the sheet this band's own rows can reach. The template
        # reserved `start_row..end_row`; the writer may have pushed the whole
        # block down, and `hdr_row` says by how much. Inside that reserved
        # area a row belongs to the band by construction, so the `stops` check
        # must not apply there.
        #
        # It used to apply everywhere, and a band lost every row from the first
        # one whose label also happened to be a field slot's — which inference
        # causes routinely, by proposing the same item as both a field and a
        # table row. The exported sheet was correct each time; the reader was
        # not, and it reported the writer as broken.
        shift = hdr_row - band.get("header_row", hdr_row)
        reserved_end = band.get("end_row", hdr_row) + shift
        while r <= max(rows):
            cells = rows.get(r)
            if not cells:
                break                                   # blank line ends the band
            first = _norm(cells.get(headers[0][0], cells.get(lcol0)))
            if first in stops and r > reserved_end:
                break                                   # a total, or the next band
            vals = {}
            for col, h in headers:
                key = next((c.get("key") or c["header"] for c in band["columns"]
                            if c["col"] == col), h)
                vals[key] = cells.get(col, "")
            if any(_txt(v) for v in vals.values()):
                out.append(vals)
                band_rows.add(r)
            r += 1
        if out:
            tables[band["name"]] = out

    # ── field slots: locate the printed label, read the cell beside it ──
    for slot in shape.get("field_slots") or []:
        want = _norm(slot["row_label"])
        if not want:
            continue
        for r in sorted(rows):
            if r in band_rows:
                continue
            here = rows[r]
            if _norm(here.get(slot["col"] - 1)) != want and \
                    _norm(here.get(lcol0)) != want:
                continue
            v = here.get(slot["col"], "")
            if _txt(v):
                fields[slot["row_label"]] = v
            break
    return {"fields": fields, "tables": tables}


def sheet_as_result(ws, shape):
    """Wrap a read sheet as a DocumentExtractionResult-shaped object, so the
    SAME adapter and scorer run over it as over the engine's output."""
    flat = read_sheet(ws, shape)
    ed = {"extracted_data": {k: {"value": v} for k, v in flat["fields"].items()}}
    for name, rows in flat["tables"].items():
        ed[f"{name}_rows"] = rows
    return SimpleNamespace(extracted_data=ed, filename="export.xlsx",
                           document_type="")
