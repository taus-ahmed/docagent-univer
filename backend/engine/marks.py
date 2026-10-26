"""What is printed ON a document rather than in it (Part 3.4): stamps, and
regions nobody can read.

STAMPS. A cheque marked VOID, a form marked SPECIMEN, an invoice stamped PAID
or COPY is still a document with values on it — and those values must not
reach a sheet as if the document were live. A stamp is a LINE consisting of
the mark (and at most a date or a few stars), so the words inside ordinary
text ("Amount Paid", "customer copy", "cancelled cheques returned") are not
stamps:

  void_marker   VOID, SPECIMEN, SAMPLE, TEST ONLY, NON-NEGOTIABLE, CANCELLED,
                DUPLICATE, COPY — the document is not the live original
  paid_marker   PAID — settled; paying it again is the risk

Both are document-level: every value of the record carries the reason and the
record goes to review. Nothing is hidden or dropped.

OBSCURED. A region painted over or too dark to read yields no text, and an
answer for a slot there can only be invented:
  native page   a dark FILLED rectangle (at least 30 x 6 pt) in the page's
                drawing layer — a redaction bar. Words beneath it are in the
                text layer but not on the page a person sees.
  scanned page  the page image near-black or without contrast, or carrying
                solid dark blocks the size of a redaction bar.
Values read from beneath a bar are blanked and flagged; empty slots of a
record with such a region are flagged — `redacted_or_obscured` — so an empty
cell says WHY it is empty.
"""
from __future__ import annotations

import base64
import io
import re

VOID_MARKER, PAID_MARKER = "void_marker", "paid_marker"
REDACTED = "redacted_or_obscured"

_VOID = ("VOID", "SPECIMEN", "SAMPLE", "TEST ONLY", "NON-NEGOTIABLE",
         "NON NEGOTIABLE", "NOT NEGOTIABLE", "CANCELLED", "CANCELED",
         "DUPLICATE", "COPY", "DUPLICATE COPY")
_STAMP = re.compile(
    r"^[\s*#\-–—=_.:|]*(?P<mark>" + "|".join(re.escape(w) for w in sorted(
        _VOID + ("PAID",), key=len, reverse=True)) + r")"
    r"(?:[\s*#\-–—=_.:|]*(?:ON\s+)?[0-9]{1,4}[/.\-][0-9]{1,2}[/.\-][0-9]{1,4})?"
    r"[\s*#\-–—=_.:|]*$")


def stamps(page_texts):
    """{"void": [(page, MARK)], "paid": [(page, "PAID")]} — 1-based pages of
    the given list. A stamp is a whole line in CAPITALS."""
    out = {"void": [], "paid": []}
    for p, text in enumerate(page_texts or [], 1):
        for line in str(text or "").splitlines():
            m = _STAMP.match(line.strip())
            if not m:
                continue
            mark = re.sub(r"\s+", " ", m.group("mark"))
            out["paid" if mark == "PAID" else "void"].append((p, mark))
    return out


# ── obscured regions ───────────────────────────────────────────────────────

_MIN_W, _MIN_H = 30.0, 6.0


def _dark(color):
    if color is None:
        return False
    if isinstance(color, (int, float)):
        return float(color) <= 0.2
    vals = [float(c) for c in color if isinstance(c, (int, float))]
    if len(vals) == 4:                                     # CMYK: K high
        return vals[3] >= 0.8 or all(v >= 0.8 for v in vals[:3])
    return bool(vals) and all(v <= 0.2 for v in vals)


def native_bars(pdf_path, page_numbers=None):
    """{file page: {"bars": [bbox], "hidden": [word]}} for native pages
    carrying dark filled rectangles; `hidden` are the text-layer words whose
    centre lies under one."""
    import pdfplumber
    out = {}
    with pdfplumber.open(str(pdf_path)) as pdf:
        nums = page_numbers or range(1, len(pdf.pages) + 1)
        for n in nums:
            if not 1 <= n <= len(pdf.pages):
                continue
            page = pdf.pages[n - 1]
            bars = [(r["x0"], r["top"], r["x1"], r["bottom"]) for r in page.rects
                    if r.get("fill") and _dark(r.get("non_stroking_color"))
                    and r["x1"] - r["x0"] >= _MIN_W and r["bottom"] - r["top"] >= _MIN_H
                    and (r["x1"] - r["x0"]) * (r["bottom"] - r["top"])
                    < 0.5 * float(page.width) * float(page.height)]
            if not bars:
                continue
            hidden = []
            for w in page.extract_words():
                cx, cy = (w["x0"] + w["x1"]) / 2, (w["top"] + w["bottom"]) / 2
                if any(x0 <= cx <= x1 and t <= cy <= b for x0, t, x1, b in bars):
                    hidden.append(w["text"])
            out[n] = {"bars": bars, "hidden": hidden}
    return out


def image_obscured(b64):
    """None, "page" (near-black or no contrast) or "regions" (solid dark
    blocks the size of a redaction bar) for one page image."""
    try:
        from PIL import Image, ImageStat
        img = Image.open(io.BytesIO(base64.b64decode(b64))).convert("L")
    except Exception:
        return None
    w = 400
    img = img.resize((w, max(1, int(img.height * w / max(1, img.width)))))
    st = ImageStat.Stat(img)
    mean, std = st.mean[0], st.stddev[0]
    if mean < 40 or std < 8:
        return "page"
    # 8 x 8 blocks at 400 px wide (~ 11 pt on a letter page): a block that is
    # entirely dark is not a character; three in a row is a bar.
    px = img.load()
    bw = 8
    cols, rows = img.width // bw, img.height // bw
    dark = [[False] * cols for _ in range(rows)]
    for by in range(rows):
        for bx in range(cols):
            tot = n = 0
            for y in range(by * bw, by * bw + bw, 2):
                for x in range(bx * bw, bx * bw + bw, 2):
                    tot += px[x, y]
                    n += 1
            dark[by][bx] = tot / n < 45
    for row in dark:
        run = 0
        for d in row:
            run = run + 1 if d else 0
            if run >= 3:
                return "regions"
    return None


# ── applying them to a record ──────────────────────────────────────────────

def _add_reason(holder, key, reason, required_key):
    rs = holder.setdefault(key, [])
    if reason not in rs:
        rs.append(reason)
    holder[required_key] = True


def _every_value(ed, reason):
    for p in (ed.get("field_provenance") or {}).values():
        _add_reason(p, "review_reasons", reason, "review_required")
    for key, rows in ed.items():
        if key.endswith("_rows") and isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict):
                    _add_reason(row, "_review_reasons", reason, "_review_required")


def _hidden(value, hidden):
    toks = {t for t in re.split(r"\s+", str(value or "").strip()) if t}
    return bool(toks & hidden)


def apply(ed, page_texts, pdf_path=None, page_numbers=None, page_images=None,
          page_origins=None):
    """Stamps and obscured regions, said on one record (`extracted_data`)."""
    if not isinstance(ed, dict):
        return ed
    val = ed.setdefault("validation", {})
    notes = ed.setdefault("validation_notes", [])
    numbers = list(page_numbers or range(1, len(page_texts or []) + 1))

    st = stamps(page_texts)
    for kind, reason, said in (("void", VOID_MARKER, "is marked {m} — not the live "
                                "original; its values are shown for checking only"),
                               ("paid", PAID_MARKER, "is stamped {m} — it has been "
                                "settled; do not pay it again")):
        if st[kind]:
            marks_ = sorted({m for _p, m in st[kind]})
            pages = sorted({numbers[p - 1] for p, _m in st[kind] if p - 1 < len(numbers)})
            val.setdefault("document_marks", {})[reason] = {"marks": marks_, "pages": pages}
            _every_value(ed, reason)
            notes.append(f"this document {said.format(m=' / '.join(marks_))} "
                         f"(page {', '.join(map(str, pages))})")
            ed["needs_review"] = True

    origins = page_origins or {}
    native = [n for n in numbers if origins.get(n, "native") == "native"]
    bars = {}
    if pdf_path and native and str(pdf_path).lower().endswith(".pdf"):
        try:
            bars = native_bars(pdf_path, native)
        except Exception:
            bars = {}
    dark = {}
    for i, b64 in enumerate(page_images or []):
        n = numbers[i] if i < len(numbers) else i + 1
        if origins.get(n, "ocr") != "native":
            v = image_obscured(b64)
            if v:
                dark[n] = v
    if not bars and not dark:
        return ed

    hidden = {w for v in bars.values() for w in v["hidden"]
              if any(ch.isdigit() for ch in w) or len(w) >= 3}
    blanked = []
    fields = ed.get("extracted_fields") or {}
    data = ed.get("extracted_data") or {}
    cmap = val.setdefault("confidence_map", {})
    prov = ed.setdefault("field_provenance", {})
    flagged = val.setdefault("flagged_fields", [])
    label_of = {f.get("ref"): f.get("row_label") for f in
                ((ed.get("slot_map") or {}).get("fields") or [])}
    for ref, v in list(fields.items()):
        if hidden and _hidden(v, hidden):
            fields[ref] = ""
            for lab, ent in data.items():
                if isinstance(ent, dict) and ent.get("ref") == ref:
                    ent["value"] = ""
            cmap[ref] = "low"
            p = prov.setdefault(ref, {})
            p["source"] = ""
            _add_reason(p, "review_reasons", REDACTED, "review_required")
            blanked.append(ref)
    for key, rows in ed.items():
        if key.endswith("_rows") and isinstance(rows, list) and hidden:
            for row in rows:
                if not isinstance(row, dict):
                    continue
                hit = [k for k, c in row.items() if not str(k).startswith("_") and _hidden(c, hidden)]
                for k in hit:
                    row[k] = ""
                if hit:
                    row["_confidence"] = "low"
                    _add_reason(row, "_review_reasons", REDACTED, "_review_required")
                    blanked.append(f"{key}:{','.join(hit)}")
    flagged_refs = {f.get("ref") for f in flagged if isinstance(f, dict)}
    for ref, lab in label_of.items():
        if str(fields.get(ref) or "").strip():
            continue
        p = prov.setdefault(ref, {"source": ""})
        _add_reason(p, "review_reasons", REDACTED, "review_required")
        if ref not in flagged_refs:
            flagged.append({"ref": ref, "value": "", "reason":
                            f"{lab or ref}: empty — part of the page is painted over "
                            f"or too dark to read, so this value may be there"})
    pages = sorted(set(bars) | set(dark))
    val[REDACTED] = {"pages": pages, "blanked": blanked,
                     "scan_pages": {str(k): v for k, v in dark.items()}}
    notes.append(f"page(s) {', '.join(map(str, pages))} carry a region painted over or "
                 f"too dark to read; {len(blanked)} value(s) read from beneath it were "
                 f"blanked, and every empty slot says why it is empty")
    ed["needs_review"] = True
    return ed
