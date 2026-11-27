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


def column_renames(headers, bands, rows, line_of_row, all_lines, skip=()):
    """({old header: printed heading}, [headers the page prints no heading
    over]). CONSERVATIVE on purpose - a wrong rename is worse than a kept
    name:

      * only on the heading line `text_layer.column_bands` CONFIRMED (two or
        more of the table's headings printed on it); no other line is ever
        taken for a heading (a row label or a section title is not one);
      * never a column in `skip` (group columns: their values are printed
        on a group line, not under the heading line);
      * the column's values (two or more located on their own lines) must
        sit under exactly ONE heading phrase - words separated by no more
        than word spacing - lying inside no other matched heading, and that
        phrase must not end in ':' (a title, not a heading);
      * nothing is renamed to a name another column already has.
    """
    from text_layer import line_page, locate
    words = list(getattr(bands, "words", ()) or ())
    if not rows:
        return {}, []
    taken = list(bands.values()) if bands else []
    fallback = False
    if not words:
        # none of the model's names is printed, so no heading line was
        # confirmed. The line directly above the table's first row (same
        # page, within three lines, no digit) is taken for it only when at
        # least TWO of its phrases each sit over a different column's values
        # (checked below): a row label or a section title is one phrase.
        first = min((line_of_row[id(r)] for r in rows if id(r) in line_of_row), default=None)
        if first is None:
            return {}, []
        for i in range(first - 1, max(-1, first - 4), -1):
            ln = all_lines[i]
            if line_page(ln) != line_page(all_lines[first]):
                break
            if len(ln) >= 2 and not any(re.search(r"\d", str(w.get("text", ""))) for w in ln):
                words, fallback = list(ln), True
                break
        if not words:
            return {}, []

    def inside_taken(w):
        return any(min(b, float(w["x1"])) - max(a, float(w["x0"])) > 0 for a, b in taken)
    phrases, cur = [], []
    for w in words:
        if inside_taken(w) or not re.search(r"[A-Za-z]", str(w.get("text", ""))):
            if cur:
                phrases.append(cur)
            cur = []
            continue
        if cur and float(w["x0"]) - float(cur[-1]["x1"]) > 6.0:
            phrases.append(cur)
            cur = []
        cur.append(w)
    if cur:
        phrases.append(cur)
    # the heading line's neighbours: a heading WRAPPED over two lines ("Average"
    # over "Ticket") is not renamed to one of its halves
    hl = next((i for i, ln in enumerate(all_lines) if ln is words or (
        ln and words and ln[0] is words[0])), None)
    near = []
    if hl is not None:
        h_ln = max(1.0, max(float(w["bottom"]) - float(w["top"]) for w in all_lines[hl]))
        for j in (hl - 1, hl + 1):
            if 0 <= j < len(all_lines) and line_page(all_lines[j]) == line_page(all_lines[hl]) \
                    and abs(float(all_lines[j][0]["top"]) - float(all_lines[hl][0]["top"])) \
                    <= 1.5 * h_ln \
                    and not any(re.search(r"\d", str(w.get("text", ""))) for w in all_lines[j]):
                near += [w for w in all_lines[j] if re.search(r"[A-Za-z]", str(w.get("text", "")))]
    renames, unprinted = {}, []
    names = {_flat(h) for h in headers}
    # every column's values' x span, from the lines its rows were read from
    span_of = {}
    for h in headers:
        spans = []
        for r in rows:
            v = str(r.get(h, "") or "").strip()
            ln_no = line_of_row.get(id(r))
            if not v or ln_no is None:
                continue
            got = locate(v, all_lines[ln_no])
            if got:
                spans.append(got)
        if len(spans) >= 2:
            span_of[h] = (min(a for a, _b in spans), max(b for _a, b in spans))

    def _over(ph, sp):
        return min(sp[1], float(ph[-1]["x1"])) - max(sp[0], float(ph[0]["x0"])) > 0
    texts = [_flat(" ".join(str(w["text"]) for w in ph)) for ph in phrases]
    for h in headers:
        if h in bands or h in skip or h not in span_of:
            continue
        over = [k for k, ph in enumerate(phrases) if _over(ph, span_of[h])]
        if not over:
            unprinted.append(h)
            continue
        if len(over) != 1:
            continue
        ph = phrases[over[0]]
        # a phrase over SEVERAL columns is a group heading, and one printed
        # more than once on the line ("Items | Amount" under each group) is a
        # sub-heading: neither is this column's own name
        if sum(1 for g, sp in span_of.items() if g != h and g not in skip and _over(ph, sp)) \
                or texts.count(texts[over[0]]) > 1:
            continue
        p0, p1 = float(ph[0]["x0"]), float(ph[-1]["x1"])
        if any(min(p1, float(w["x1"])) - max(p0, float(w["x0"])) > 0 for w in near):
            continue                   # a wrapped heading: keep the model's whole name
        new = " ".join(str(w["text"]) for w in ph).strip()
        if new.endswith(":") or _flat(new) == _flat(h) or _flat(new) in names:
            continue
        renames[h] = new
        names.add(_flat(new))
    if fallback and len(renames) + sum(1 for h in headers if h in bands) < 2:
        return {}, []                  # the line above is not a heading line
    return renames, (unprinted if not fallback or renames else [])


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
    renamed_fields = {}
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
        renamed_fields[f.get("ref")] = {"from": old, "to": new}
        kv = ed.get("extracted_data") or {}
        if old in kv and new not in kv:
            kv[new] = kv.pop(old)
    if ed.get("inferred_grid") is not None:
        ed["inferred_grid"] = grid
    ed["slot_map"] = smap
    ed["printed_renames"] = {"tables": table_renames, "fields": renamed_fields}
    return ed
