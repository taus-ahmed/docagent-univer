"""Form boxes (Run T2, Stage 3): a fillable form's values next to the labels
of the boxes that hold them.

A fillable form prints its labels as text and keeps what was typed in
WIDGETS (AcroForm fields: name, rect, value; `perception.widget_words`
places each value as a word at its widget's rect). Read line by line, a
widget value lands in whatever printed line shares its height - beside
another box's label, or glued to another widget's value - so the export
held the labels and lost which value belonged to which.

Here a page that carries widget VALUES is read by its drawn boxes:

  * every word gets the box enclosing it: the nearest drawn edge to its
    left, right, above and below (the page's own ruling, `page["edges"]`);
  * boxes that touch are one FORM; two forms printed on one page are two
    regions, each with its own anchor;
  * a box is one FIELD: its printed words are the label (a label set in
    pieces - a code letter per line, stacked - is read back as one word),
    its widget words are the value; a lone currency sign joins the value;
  * boxes sharing a top are written side by side, `label | value`, like any
    label/value line; every box's label is written, filled or not.

Pages with no widget value are not touched (the normal path reads them),
and nothing here reads vocabulary: only edges, boxes and word origins.
"""
from __future__ import annotations

import statistics

TOL = 2.0
_CURRENCY = {"$", "€", "£", "¥", "₹"}


def has_widget_values(page) -> bool:
    return any(w.get("origin") == "widget" and not w.get("checkbox") for w in page["words"])


def box_of(word, edges, tol: float = TOL):
    """(x0, top, x1, bottom) of the drawn box around a word, or None when
    the page draws no edge on some side of it."""
    # located by its CENTRE: a widget's rect often overruns the frame it is
    # drawn in by a few points, and must still land in that frame
    cx = (word["x0"] + word["x1"]) / 2
    cy = (word["top"] + word["bottom"]) / 2
    left = [x for y0, y1, x in edges["v"] if x <= cx and y0 - tol <= cy <= y1 + tol]
    right = [x for y0, y1, x in edges["v"] if x >= cx and y0 - tol <= cy <= y1 + tol]
    up = [y for x0, x1, y in edges["h"] if y <= cy and x0 - tol <= cx <= x1 + tol]
    down = [y for x0, x1, y in edges["h"] if y >= cy and x0 - tol <= cx <= x1 + tol]
    if not (left and right and up and down):
        return None
    return (round(max(left), 1), round(max(up), 1), round(min(right), 1), round(min(down), 1))


def _touch(a, b, tol=TOL) -> bool:
    return a[0] <= b[2] + tol and b[0] <= a[2] + tol and a[1] <= b[3] + tol and b[1] <= a[3] + tol


def _forms(boxes) -> list:
    """Boxes grouped into forms: connected by touching."""
    boxes = list(boxes)
    parent = list(range(len(boxes)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            if _touch(boxes[i], boxes[j]):
                parent[find(i)] = find(j)
    groups = {}
    for i, b in enumerate(boxes):
        groups.setdefault(find(i), []).append(b)
    return sorted(groups.values(), key=lambda g: min(b[1] for b in g))


def label_text(words) -> str:
    """A box's printed words in reading order, a label set in pieces read
    back whole: consecutive lines that are each ONE short piece (1-2
    characters) at one left edge, stacked, are one word."""
    ws = sorted(words, key=lambda w: (w["baseline"], w["x0"]))
    lines = []
    for w in ws:
        if lines and abs(w["baseline"] - lines[-1][-1]["baseline"]) <= 0.4 * (w.get("size") or 8):
            lines[-1].append(w)
        else:
            lines.append([w])
    parts, stack = [], []

    def flush():
        if stack:
            parts.append("".join(w["text"] for w in stack))
            stack.clear()
    for ln in lines:
        one = len(ln) == 1 and len(ln[0]["text"]) <= 2
        if one and (not stack or abs(ln[0]["x0"] - stack[-1]["x0"]) <= 3.0):
            stack.append(ln[0])
            continue
        flush()
        if one:
            stack.append(ln[0])
            continue
        parts.append(" ".join(w["text"] for w in sorted(ln, key=lambda w: w["x0"])))
    flush()
    return " ".join(p for p in parts if p)


def form_regions(page) -> list:
    """[{"line_ids", "fields": [{"box", "label_ids", "value_ids"}]}] for a
    page with widget values, one per form; [] otherwise. A line belongs to
    a form when every word on it sits in one of that form's boxes."""
    if not has_widget_values(page) or not page.get("edges"):
        return []
    edges = page["edges"]
    by_box = {}
    word_box = {}
    seen = []
    for w in page["words"]:
        b = box_of(w, edges)
        if b is None:
            continue
        # one box drawn with edges a fraction of a point apart (59.9 / 60.0)
        # is one box
        b = next((s for s in seen if all(abs(p - q) <= 1.5 for p, q in zip(s, b))), b)
        if b not in seen:
            seen.append(b)
        word_box[w["id"]] = b
        by_box.setdefault(b, []).append(w)
    if not any(w.get("origin") == "widget" for ws in by_box.values() for w in ws):
        return []
    # a box is a FIELD box only when it is small against the page: the
    # page's outer frame encloses everything and is no field
    area = float(page.get("width") or 612) * float(page.get("height") or 792)
    fields = {b: ws for b, ws in by_box.items() if (b[2] - b[0]) * (b[3] - b[1]) < 0.25 * area}
    groups = _forms(fields)
    gof = {b: gi for gi, g in enumerate(groups) for b in g}
    by_id = {w["id"]: w for w in page["words"]}
    # a line belongs to the form most of its BOXED words sit in; its words
    # outside every box become label-only fields of that form (so a widget
    # value never falls back to the line-by-line reading and glues to a
    # label beside it)
    line_group, loose = {}, {}
    for ln in page["lines"]:
        gs = [gof[word_box[i]] for i in ln["word_ids"] if word_box.get(i) in gof]
        if not gs:
            continue
        g = max(set(gs), key=gs.count)
        line_group[ln["id"]] = g
        rest = [by_id[i] for i in ln["word_ids"] if word_box.get(i) not in gof
                or gof[word_box[i]] != g]
        if rest:
            loose.setdefault(g, []).append(rest)
    out = []
    for gi, group in enumerate(groups):
        line_ids = [ln["id"] for ln in page["lines"] if line_group.get(ln["id"]) == gi]
        if not line_ids:
            continue
        in_lines = {i for ln in page["lines"] if ln["id"] in line_ids for i in ln["word_ids"]}
        fl = []
        for b in sorted(group, key=lambda b: (b[1], b[0])):
            ws = [w for w in fields[b] if w["id"] in in_lines]
            if ws:
                fl += _box_fields(b, ws)
        for ws in loose.get(gi, []):
            signs = [w for w in ws if w["text"] in _CURRENCY]
            ws = [w for w in ws if w not in signs]
            if not ws:
                fl.append({"box": [0, 0, 0, 0], "label_ids": [], "value_ids": [],
                           "dropped_ids": [w["id"] for w in signs]})
                continue
            x0, x1 = min(w["x0"] for w in ws), max(w["x1"] for w in ws)
            t, bt = min(w["top"] for w in ws), max(w["bottom"] for w in ws)
            fl.append({"box": [x0, t, x1, bt], "label_ids": [w["id"] for w in ws],
                       "value_ids": [], "dropped_ids": [w["id"] for w in signs]})
        _claim_labels(fl)
        if any(f["value_ids"] for f in fl):
            out.append({"line_ids": line_ids, "fields": fl})
    return out


def _claim_labels(fl) -> None:
    """A value whose box prints no label takes the label-only field
    directly ABOVE it (their boxes overlap in x; nothing between): a form
    that prints a field's label in one frame and its value in the frame
    under it. The emptied label field is removed."""
    for f in fl:
        if f["label_ids"] or not f["value_ids"]:
            continue
        x0, t, x1, _b = f["box"]
        above = [g for g in fl if g is not f and g["label_ids"] and not g["value_ids"]
                 and g["box"][3] <= t + TOL and min(x1, g["box"][2]) - max(x0, g["box"][0]) > 0]
        if not above:
            continue
        g = max(above, key=lambda g: g["box"][3])
        if t - g["box"][3] > 3 * max(1.0, g["box"][3] - g["box"][1]):
            continue
        f["label_ids"] = g["label_ids"]
        f["box"] = [min(x0, g["box"][0]), g["box"][1], max(x1, g["box"][2]), f["box"][3]]
        g["label_ids"] = []


def _box_fields(b, ws) -> list:
    """The fields of one box. One label and its widget values make one
    field; a box printing SEVERAL labels with several values (a name line,
    then a street line, in one frame) gives each widget to the label line
    directly above it. A lone currency sign joins the value beside it, or,
    with no value in the box, is left out (`dropped_ids`)."""
    vals = [w for w in ws if w.get("origin") == "widget"]
    labs = [w for w in ws if w.get("origin") != "widget"]
    signs = [w for w in labs if w["text"] in _CURRENCY]
    labs = [w for w in labs if w not in signs]
    tvals = [w for w in vals if not w.get("checkbox")]
    lines = []
    for w in sorted(labs, key=lambda w: (w["baseline"], w["x0"])):
        if lines and abs(w["baseline"] - lines[-1][-1]["baseline"]) <= 0.4 * (w.get("size") or 8):
            lines[-1].append(w)
        else:
            lines.append([w])
    if len(tvals) >= 2 and len(lines) >= 2:
        subs = [{"labs": ln, "vals": []} for ln in lines]
        for v in vals:
            above = [s for s in subs if max(w["bottom"] for w in s["labs"]) <= v["top"] + 2.0]
            s = max(above, key=lambda s: max(w["bottom"] for w in s["labs"])) if above else subs[0]
            s["vals"].append(v)
        out = []
        for s in subs:
            t = min(w["top"] for w in s["labs"])
            out.append({"box": [b[0], t, b[2], b[3]], "label_ids": [w["id"] for w in s["labs"]],
                        "value_ids": [w["id"] for w in s["vals"]], "dropped_ids": []})
        if signs:
            tgt = next((f for f in out if f["value_ids"]), out[0])
            tgt["value_ids"] = [w["id"] for w in signs] + tgt["value_ids"]
        return out
    return [{"box": list(b), "label_ids": [w["id"] for w in labs],
             "value_ids": ([w["id"] for w in signs] if tvals else []) + [w["id"] for w in vals],
             "dropped_ids": [] if tvals else [w["id"] for w in signs]}]


def field_rows(page, fields) -> list:
    """Fields grouped into sheet rows: boxes whose tops agree (within the
    page's usual text height) side by side, left to right."""
    sizes = [w.get("size") or 8 for w in page["words"]]
    tol = 0.6 * (statistics.median(sizes) if sizes else 8)
    rows = []
    for f in sorted(fields, key=lambda f: (f["box"][1], f["box"][0])):
        if rows and abs(f["box"][1] - rows[-1][0]["box"][1]) <= tol:
            rows[-1].append(f)
        else:
            rows.append([f])
    return [sorted(r, key=lambda f: f["box"][0]) for r in rows]
