"""No-template names: the page's own printed labels (Run T, owner priority).

Inference names every column and field it designs, and its names drift from
the page: a column printed `INVOICE` came back `Invoice Number`, a heading
nobody printed (`Description` over a column of row labels) was written as if
the page said it. In no-template mode the sheet's headers are the page's:

  * a column whose own heading the page prints over its values is called
    exactly that (the model's name is replaced);
  * a column with no heading printed over it keeps a neutral name, MARKED
    inferred (the export's amber header and its comment);
  * a field label the page does not print, whose value is printed after a
    `Label:` on its own line, is called by that label; otherwise it is marked
    inferred.

Applied to the finished result only (rows' keys, the slot map, a COPY of the
inferred grid, the label-keyed projection). The prompt, the shape and the
model's answer are untouched, so nothing a later document of the batch is
asked changes, and every cached answer stays valid.
"""
from __future__ import annotations

import copy
import re

NO_HEADING = ("the page prints no heading over this column; the name is the "
              "engine's - please check it")
NO_LABEL = ("the page prints no label for this value; the name is the "
            "engine's - please check it")

_LABEL_BEFORE = re.compile(r"([A-Za-z][A-Za-z0-9 .#/&'()\-]{0,40}?)\s*:\s*$")


def _flat(s) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().casefold()


def column_renames(headers, bands, rows, line_of_row, all_lines):
    """({old header: printed heading}, [headers the page prints no heading
    over]). Read off the document's heading line (`bands.words`, the line
    `text_layer.column_bands` matched): the heading words over a column's
    values, not inside another matched heading. Nothing is renamed to a name
    another column of the table already has."""
    from text_layer import line_page, locate
    words = list(getattr(bands, "words", ()) or ())
    if not rows:
        return {}, []
    if not words:
        # none of the model's names is printed, so no heading line was
        # matched: the heading line is the figure-free line of two or more
        # words directly above the table's first row (within three lines)
        first = min((line_of_row[id(r)] for r in rows if id(r) in line_of_row), default=None)
        if first is None:
            return {}, []
        for i in range(first - 1, max(-1, first - 4), -1):
            ln = all_lines[i]
            if line_page(ln) != line_page(all_lines[first]):
                break
            if len(ln) >= 2 and not any(re.search(r"\d", str(w.get("text", ""))) for w in ln):
                words = list(ln)
                break
        if not words:
            return {}, []
    taken = list(bands.values()) if bands else []
    renames, unprinted = {}, []
    names = {_flat(h) for h in headers}
    for h in headers:
        if h in bands:
            continue
        spans = []
        for r in rows:
            v = str(r.get(h, "") or "").strip()
            ln_no = line_of_row.get(id(r))
            if not v or ln_no is None:
                continue
            got = locate(v, all_lines[ln_no])
            if got:
                spans.append(got)
        if not spans:
            continue
        x0, x1 = min(a for a, _b in spans), max(b for _a, b in spans)
        over = [w for w in words
                if min(x1, float(w["x1"])) - max(x0, float(w["x0"])) > 0
                and not any(min(b, float(w["x1"])) - max(a, float(w["x0"])) > 0
                            for a, b in taken)
                and re.search(r"[A-Za-z]", str(w.get("text", "")))]
        if not over:
            unprinted.append(h)
            continue
        new = " ".join(str(w["text"]) for w in over).strip()
        if _flat(new) == _flat(h) or _flat(new) in names:
            continue
        renames[h] = new
        names.add(_flat(new))
    return renames, unprinted


def field_label(value, source, all_lines):
    """The label the page prints before `value` on its own line ("Account
    Number: 6547" -> "Account Number"), or None."""
    from text_layer import find_line
    v = str(value or "").strip()
    if not v:
        return None
    for quote in (source, v):
        ln = find_line(all_lines, quote) if quote else None
        if not ln:
            continue
        text = " ".join(str(w.get("text", "")) for w in ln)
        i = text.find(v)
        if i <= 0:
            continue
        m = _LABEL_BEFORE.search(text[:i])
        if m:
            label = m.group(1).strip()
            if re.search(r"[A-Za-z]{2}", label):
                return label
    return None


def printed_anywhere(label, all_lines) -> bool:
    from text_layer import find_line
    return bool(label and find_line(all_lines, label))


def apply(ed, table_renames, field_renames):
    """Rename in the finished result: table rows' keys, the slot map, a copy
    of the inferred grid, the label-keyed projection, `inferred_headers`."""
    if not table_renames and not field_renames:
        return ed
    grid = copy.deepcopy(ed.get("inferred_grid") or {})
    cells = grid.get("cells") or {}
    smap = copy.deepcopy(ed.get("slot_map") or {})
    for t in smap.get("tables") or []:
        ren = table_renames.get(t.get("name")) or {}
        if not ren:
            continue
        hr = t.get("header_row")
        for c in t.get("columns") or []:
            key = c.get("key") or c.get("header")
            if key in ren:
                new = ren[key]
                cell = cells.get(f"{hr},{c.get('col')}")
                if cell is not None and str(cell.get("value") or "").strip() == str(c.get("header")):
                    cell["value"] = new
                c["header"] = new
                if "key" in c:
                    c["key"] = new
        for r in ed.get(f"{t['name']}_rows") or []:
            for old, new in ren.items():
                if old in r:
                    r[new] = r.pop(old)
            if isinstance(r.get("_ungrounded"), list):
                r["_ungrounded"] = [ren.get(k, k) for k in r["_ungrounded"]]
    for f in smap.get("fields") or []:
        new = field_renames.get(f.get("ref"))
        if not new:
            continue
        old = f.get("row_label")
        for cell in cells.values():
            if str(cell.get("value") or "").strip() == str(old):
                cell["value"] = new
                break
        f["row_label"] = new
        kv = ed.get("extracted_data") or {}
        if old in kv and new not in kv:
            kv[new] = kv.pop(old)
    if ed.get("inferred_grid") is not None:
        ed["inferred_grid"] = grid
    ed["slot_map"] = smap
    ed["printed_renames"] = {"tables": table_renames, "fields": field_renames}
    return ed
