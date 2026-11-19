"""Fillable-form fields as a first-class lane (Run B, B1).

Run A wrote each filled widget's value into the page text where it sits, as
bare words. That made the value visible, and ambiguous: `irs_w2_mod11.pdf`
reads ``10-8763214 10535`` on one line - the EIN and Box 1 side by side, with
nothing saying which is which - and the model answered `Box c Employer Name`
with ``R AND R FARM 10535 21 BEECH TREE FARM ...``.

A widget is better evidence than that. It is one value in one box, and the
form prints that box's label right above it. This module turns each filled
widget into an ENTRY - ``{label, value, page, box, role}`` - so that:

* the prompt can say ``1 Wages, tips, other compensation: 10535`` instead of
  leaving the model to pair labels and numbers by position;
* a slot the model leaves empty, or answers differently, while a matching
  widget holds a value is filled FROM the widget (`match`). The value is read
  from the file, not by the model, and is reported as machine-read.

Label: the printed words directly above the widget's rectangle and inside
its horizontal span (IRS forms print each box's caption at the top of the
box), stacked up to four lines; the widget's tooltip (`/TU`) and field name
(`/T`) are kept as extra matching text, because a field name such as
``f1_008[0]`` says nothing while ``Form W2 line 1`` says a lot.

Matching is by MEANING, conservatively: a box id (``Box 1``, ``Box c``,
``Box 12a``) on both sides must agree; the slot's significant words must
overlap the entry's, and an overlap made only of generic words (``number``,
``name``, ``amount``) is not a match. A combined name-and-address box is split
into its name (first line) and its address (the remaining lines, joined with
", "), and separate street / city widgets under one party's name are joined
into one address.
"""
from __future__ import annotations

import re

_PHONE = re.compile(r"^\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}$")
_BOX_LEAD = re.compile(r"^(\d{1,2}[a-z]?|[a-f])$")
_BOX_IN = re.compile(r"\b(?:box|line)\s*\.?\s*(\d{1,2}[a-z]?|[a-f])\b", re.I)
_STOP = {"and", "or", "the", "of", "for", "from", "to", "in", "on", "at", "by",
         "no", "incl", "including", "apt", "etc", "if", "see", "instructions",
         "box", "form", "line", "s", "a", "an", "is", "this", "your"}
#: Words that name a KIND of value rather than which one. An overlap made only
#: of these is not evidence (`Account Number` is not `identification number`).
_GENERIC = {"number", "name", "amount", "total", "date", "code", "id", "no",
            "information", "type", "other", "value"}
#: Word-level synonyms on the SLOT side (B2's vocabulary, the tax-form part):
#: a template says TIN where the form prints "identification number".
_SYNONYMS = {"tin": {"identification"}, "ssn": {"social", "security"},
             "ein": {"employer", "identification"}, "wages": {"compensation"},
             "lender": {"recipient"}, "borrower": {"payer"}}
_ADDRESS_PART = re.compile(r"\b(street|city|town|zip|postal|address)\b", re.I)


def words_of(text) -> list[str]:
    s = str(text or "").casefold().replace("’", "'")
    s = re.sub(r"'s\b", "", s)
    return [w for w in re.split(r"[^0-9a-z]+", s) if w and w not in _STOP]


def box_id(label: str, *extra: str):
    """The form-box id a label names, or None. A printed caption leads with
    it (`1 Wages…`, `c Employer's name…`); a slot or tooltip says `Box 1`."""
    s = str(label or "").strip().casefold()
    m = _BOX_IN.search(s)
    if m:
        return m.group(1).lower()
    first = s.split(" ", 1)[0].rstrip(".") if s else ""
    if _BOX_LEAD.match(first) and len(s.split()) > 1:
        return first
    for e in extra:
        m = _BOX_IN.search(str(e or ""))
        if m:
            return m.group(1).lower()
    return None


def printed_label(words, w, max_lines=4):
    """The caption printed directly above widget `w` (pdfplumber words)."""
    h = float(w["bottom"]) - float(w["top"])
    cand = [x for x in words
            if float(x["x0"]) >= float(w["x0"]) - 8
            and float(x["x0"]) < float(w["x1"]) - 2
            and float(x["bottom"]) <= float(w["top"]) + 0.6 * h + 2
            and float(x["top"]) >= float(w["top"]) - 60]
    if not cand:
        return ""
    lines = []
    for x in sorted(cand, key=lambda x: -float(x["bottom"])):
        for ln in lines:
            if abs(float(ln[0]["bottom"]) - float(x["bottom"])) < 3:
                ln.append(x)
                break
        else:
            lines.append([x])
    lines.sort(key=lambda ln: -float(ln[0]["bottom"]))     # nearest first
    picked = [lines[0]]
    for ln in lines[1:max_lines]:
        gap = float(picked[-1][0]["top"]) - float(ln[0]["bottom"])
        if gap > 4:
            break
        picked.append(ln)
    picked.reverse()
    return " ".join(" ".join(x["text"] for x in sorted(ln, key=lambda x: float(x["x0"])))
                    for ln in picked)


def _lines(value: str) -> list[str]:
    return [ln.strip() for ln in re.split(r"[\r\n]+", str(value or "")) if ln.strip()]


def _party(label: str) -> list[str]:
    """Possessive party words: `RECIPIENT'S/LENDER'S TIN` -> recipient, lender."""
    s = str(label or "").replace("’", "'")
    return [m.casefold() for m in re.findall(r"([A-Za-z]+)'[sS]\b", s)]


def entries_for_page(words, widgets, page_no):
    """Entries for one page: `words` are the page's printed words, `widgets`
    the page's widgets from `acroform_widgets` + `acroform_field_values`."""
    base = []
    for w in widgets:
        label = printed_label(words, w)
        extra = " ".join(str(w.get(k) or "") for k in ("tooltip", "name"))
        if "value" in w:
            base.append({"label": label, "extra": extra, "page": page_no,
                         "value": str(w["value"]), "x0": float(w["x0"]),
                         "top": float(w["top"]), "bottom": float(w["bottom"]),
                         "box": box_id(label, w.get("tooltip"), w.get("name")),
                         "kind": "text"})
        else:
            # A checkbox's own label sits to its RIGHT on its line.
            right = [x for x in words
                     if float(x["x0"]) >= float(w["x1"]) - 1
                     and float(x["x0"]) <= float(w["x1"]) + 160
                     and abs((float(x["top"]) + float(x["bottom"])) / 2
                             - (float(w["top"]) + float(w["bottom"])) / 2) < 6]
            right.sort(key=lambda x: float(x["x0"]))
            text = " ".join(x["text"] for x in right[:6])
            base.append({"label": text or label, "extra": extra, "page": page_no,
                         "value": "checked" if w.get("on") else "unchecked",
                         "kind": "checkbox", "x0": float(w["x0"]),
                         "top": float(w["top"]), "bottom": float(w["bottom"]),
                         "box": None})
    out = []
    for e in base:
        out.append(dict(e, role="whole"))
        lines = [ln for ln in _lines(e["value"]) if not _PHONE.match(ln)]
        if e["kind"] == "text" and len(lines) >= 2:
            out.append(dict(e, role="name", value=lines[0]))
            out.append(dict(e, role="address", value=", ".join(lines[1:])))
    # Street + city widgets stacked in one column under a party's name.
    texts = sorted((e for e in base if e["kind"] == "text"
                    and len(_lines(e["value"])) == 1), key=lambda e: e["top"])
    used = set()
    for i, e in enumerate(texts):
        if i in used or not re.search(r"\bstreet\b", e["label"], re.I):
            continue
        run = [e]
        for j in range(i + 1, len(texts)):
            f = texts[j]
            if abs(f["x0"] - e["x0"]) <= 12 and f["top"] - run[-1]["bottom"] < 40 \
                    and _ADDRESS_PART.search(f["label"]):
                run.append(f)
                used.add(j)
            elif f["top"] > run[-1]["bottom"] + 40:
                break
        if len(run) < 2:
            continue
        owner = [f for f in texts if abs(f["x0"] - e["x0"]) <= 12
                 and f["bottom"] <= e["top"] + 2 and re.search(r"\bname\b", f["label"], re.I)]
        party = _party(owner[-1]["label"]) if owner else []
        out.append(dict(e, role="address", label=" ".join(party + ["address"]),
                        extra="", value=", ".join(_lines(r["value"])[0] for r in run)))
    return out


def _score(slot_label, entry):
    """0..1, or None when the entry cannot be this slot."""
    slot_box = box_id(slot_label)
    if slot_box and entry.get("box") and slot_box != entry["box"]:
        return None
    if slot_box and entry.get("box") != slot_box:
        return None              # a numbered box answers only its own number
    s = [w for w in words_of(slot_label) if w != slot_box]
    e = set(words_of(entry["label"])) | set(words_of(entry.get("extra")))
    if slot_box:
        e.discard(slot_box)
    if not s:
        return None
    multi = entry.get("role") == "whole" and len(_lines(entry["value"])) > 1
    wants_addr = "address" in s
    wants_name = "name" in s and not wants_addr
    role = entry.get("role")
    if wants_addr and role not in ("address",) and not (
            role == "whole" and "address" in e and "name" not in e):
        return None
    if wants_name and role == "address":
        return None
    if not wants_addr and role == "address":
        return None
    if not wants_name and role == "name":
        return None
    if multi and (wants_name or wants_addr):
        return None              # answered by the box's name / address part
    hit = [w for w in s if w in e or (_SYNONYMS.get(w, set()) & e)]
    if not hit or all(w in _GENERIC for w in hit):
        return None
    score = len(hit) / len(s)
    if slot_box and entry.get("box") == slot_box:
        score += 0.5
    return score


def match(slot_label, entries):
    """(entry, strong) for the one entry that answers this slot, or (None,
    False). `strong` is a box-id agreement or most of the slot's words: only
    a strong match may overrule a value the model gave."""
    scored = []
    for e in entries:
        if e.get("kind") != "text":
            continue
        sc = _score(slot_label, e)
        if sc is not None and sc >= 0.5:
            scored.append((sc, e))
    if not scored and "address" in words_of(slot_label):
        # A W-2 prints the employee's address under box f while the widget
        # for box e holds name AND address: same party, different box id.
        party = [w for w in words_of(slot_label) if w not in ("address", "box")
                 and not _BOX_LEAD.match(w)]
        for e in entries:
            if e.get("kind") == "text" and e.get("role") == "address" and party \
                    and all(p in words_of(e["label"] + " " + e.get("extra", ""))
                            for p in party):
                scored.append((0.6, e))
    if not scored:
        return None, False
    scored.sort(key=lambda t: -t[0])
    if len(scored) > 1 and scored[1][0] == scored[0][0] \
            and scored[1][1]["value"] != scored[0][1]["value"]:
        return None, False                       # two equally good answers
    best, e = scored[0]
    return e, best >= 1.0 or (box_id(slot_label) is not None
                              and e.get("box") == box_id(slot_label))


def prompt_block(entries) -> str:
    """The lane as the model reads it: one line per field, label first."""
    rows = []
    for e in entries:
        if e.get("role") != "whole":
            continue
        label = re.sub(r"\s+", " ", e["label"] or e.get("extra") or "form field").strip()
        value = " / ".join(_lines(e["value"])) if e["kind"] == "text" else e["value"]
        rows.append(f"  [page {e['page']}] {label}: {value}")
    if not rows:
        return ""
    return ("=== FILLED FORM FIELDS (read from the PDF's fillable fields; these "
            "values are authoritative) ===\n" + "\n".join(rows) +
            "\n=== END FORM FIELDS ===\n"
            "Template labels and the form's printed labels can be worded "
            "differently: match each slot to its form field by MEANING. For a "
            "value taken from a form field, the source is the value itself.\n")


def same_value(a, b) -> bool:
    """A model answer and a widget value saying the same thing."""
    from amounts import parse_amount
    na, nb = re.sub(r"[^0-9a-z]+", "", str(a).casefold()), \
        re.sub(r"[^0-9a-z]+", "", str(b).casefold())
    if na == nb:
        return True
    if re.fullmatch(r"[\s$€£(),.\-−0-9]+", str(a)) and re.fullmatch(r"[\s$€£(),.\-−0-9]+", str(b)):
        pa, pb = parse_amount(str(a), "."), parse_amount(str(b), ".")
        return bool(pa.ok and pb.ok and pa.value == pb.value)
    return False
