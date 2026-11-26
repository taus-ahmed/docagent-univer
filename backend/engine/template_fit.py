"""Run Q Phase 3 (Q11): does the template fit the document? Said, never silent.

Two failures used to pass without a word:

  * an IGNORED FORM - a composite brokerage statement prints Forms 1099-DIV,
    -MISC, -INT and -B, the template covers 1099-INT and DIV, and the other
    two forms' values were simply not extracted (job 53). A form the document
    prints twice or more, of a family the template does name, and which the
    template never names, is listed in a visible note;
  * a WRONG TEMPLATE - a 1099-B run with a Purchase Order template returns
    empty or misfiled slots (job 59). When the template's own document type
    scores NOTHING on the page's keywords and another type scores at least
    two, the document gets one attention item: "This does not look like a
    Purchase Order".

Both are keyword evidence, so both only SAY: no value is changed or dropped.
"""
from __future__ import annotations

import re

#: a tax form id as printed (the families an instructions page names in
#: passing, like Form 1040 or W-9, are left out: they are references)
_FORM = re.compile(r"\b(1099-[A-Z]{1,4}|1098(?:-[A-Z]{1,2})?|W-2G?|SSA-1099|1042-S)\b")


def _norm_form(s):
    return s.upper()


#: a form's own printed title, for a form whose id the page leaves out
_TITLES = (("1099-B", r"proceeds\s+from\s+broker"), ("1099-DIV", r"dividends\s+and\s+distributions"),
           ("1099-INT", r"\binterest\s+income\b"), ("1099-MISC", r"\bmiscellaneous\s+income\b"),
           ("1099-NEC", r"nonemployee\s+compensation"), ("W-2", r"wage\s+and\s+tax\s+statement"))


def printed_forms(text):
    """Form ids the document PRINTS as forms, in first-seen order: an id that
    opens a line ("Form 1099-DIV* 2026 Dividends..."), an id printed twice, or
    a form's own title ("Proceeds From Broker and Barter Exchange"). An id
    mentioned once mid-sentence is a reference, not a form."""
    text = str(text or "")
    hits = []                                   # (position, form)
    count = {}
    for m in _FORM.finditer(text):
        f = _norm_form(m.group(1))
        count[f] = count.get(f, 0) + 1
        line_start = text.rfind("\n", 0, m.start()) + 1
        if re.fullmatch(r"\s*(?:form\s+)?", text[line_start:m.start()], re.I):
            hits.append((m.start(), f))
    for m in _FORM.finditer(text):
        f = _norm_form(m.group(1))
        if count[f] >= 2:
            hits.append((m.start(), f))
    for f, pat in _TITLES:
        m = re.search(pat, text, re.I)
        if m:
            hits.append((m.start(), f))
    out = []
    for _p, f in sorted(hits):
        if f not in out:
            out.append(f)
    return out


def _named(template):
    """Form ids the template names: in its name or any label. `1099-INT and
    DIV` names 1099-DIV too - a suffix list after a 1099 prefix."""
    blob = " ".join([str(template.get("name") or "")]
                    + [str(x) for x in template.get("cells_text") or []])
    out = {_norm_form(m.group(1)) for m in _FORM.finditer(blob)}
    for m in re.finditer(r"\b1099-([A-Z]{1,4})((?:\s*(?:,|and|&|/)\s*[A-Z]{1,4}\b)+)", blob):
        for suf in re.findall(r"[A-Z]{1,4}", m.group(2)):
            out.add(f"1099-{suf}")
    return out


def template_cells_text(template_data):
    """Every label the template holds, from whichever shape it was parsed into."""
    out = []
    grid = (template_data or {}).get("grid") or (template_data or {}).get("layout") or {}
    for c in (grid.get("cells") or {}).values():
        v = c.get("value") if isinstance(c, dict) else None
        if v:
            out.append(str(v))
    for c in (template_data or {}).get("columns") or []:
        out.append(str(c.get("name") if isinstance(c, dict) else c))
    return out


def ignored_forms(text, template):
    named = _named(template)
    if not named:
        return []                     # the template names no form: no verdict
    fams = {f.split("-")[0] for f in named}
    return [f for f in printed_forms(text) if f not in named and f.split("-")[0] in fams]


_AMT = re.compile(r"(?<![\d.,])\(?-?\$?\s?(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2}\)?(?![\d,])")


def form_amounts(text, form):
    """Run R, R3: the amounts printed in `form`'s part of the document - from
    the first line naming it to the first line naming another printed form
    after it. The template covers no value of that form by definition, so
    every one of them is a figure the export does not hold."""
    text = str(text or "")
    starts = []
    for f in printed_forms(text):
        m = re.search(rf"(?m)^.*\b{re.escape(f)}\b", text)
        if m:
            starts.append((m.start(), f))
    starts.sort()
    mine = next((i for i, (_p, f) in enumerate(starts) if f == form), None)
    if mine is None:
        return []
    a = starts[mine][0]
    b = starts[mine + 1][0] if mine + 1 < len(starts) else len(text)
    return [re.sub(r"[\s$()]", "", m.group(0)) for m in _AMT.finditer(text[a:b])]


def _scores(text):
    from app.services.prompt_registry import PROMPT_REGISTRY, _hint_in
    low = str(text or "")[:5000].lower()
    out = {}
    for t, entry in PROMPT_REGISTRY.items():
        if t != "other":
            out[t] = sum(1 for h in entry.get("auto_classify_hints", []) if _hint_in(h, low))
    return out


_STOP = {"the", "and", "for", "of", "to", "in", "on", "at", "no", "number", "date",
         "amount", "total", "name", "address", "box", "line", "per", "a", "an", "or"}


def slot_labels(slot_map) -> list:
    """The template's own words: field labels and table column headings."""
    out = [f.get("row_label") for f in (slot_map or {}).get("fields") or []]
    for t in (slot_map or {}).get("tables") or []:
        out += [c.get("header") for c in t.get("columns") or []]
    return [str(x) for x in out if str(x or "").strip()]


def _sig(label):
    return [w for w in re.findall(r"[a-z]{3,}", str(label).casefold()) if w not in _STOP]


def label_fraction(text, labels):
    """(fraction, labels with words, labels printed): a label is PRINTED when
    at least half of its significant words appear in the text as whole words.
    Labels with no significant word ("No.", "Box 1") are not counted."""
    words = set(re.findall(r"[a-z]{3,}", str(text or "").casefold()))
    counted = [_sig(x) for x in labels]
    counted = [c for c in counted if c]
    hit = sum(1 for c in counted if sum(w in words for w in c) * 2 >= len(c))
    return ((hit / len(counted)) if counted else 1.0), len(counted), hit


#: Run S, 3b: a template whose own labels the document barely prints. Chosen
#: on the corpus (tools/template_label_fit.py): every right template prints
#: well over this share of its labels; the wrong-template jobs print under it.
LABEL_FIT_MIN = 0.25
LABEL_FIT_MIN_LABELS = 6


def label_mismatch(text, labels, template_name=None):
    """'Most of this template's labels are not on the page' or None."""
    frac, n, hit = label_fraction(text, labels)
    if n < LABEL_FIT_MIN_LABELS or frac >= LABEL_FIT_MIN:
        return None
    name = f" {template_name!r}" if template_name else ""
    return (f"This document prints only {hit} of the {n} labels of the template{name} "
            f"({round(100 * frac)}%): it may be the wrong template for this "
            f"document. Check that the right template was chosen.")


def type_mismatch(text, template_type):
    """'This does not look like a <type> ...' or None."""
    from app.services.prompt_registry import PROMPT_REGISTRY, _display
    t = str(template_type or "").strip().lower()
    if not t or t == "other" or t not in PROMPT_REGISTRY:
        return None
    sc = _scores(text)
    if sc.get(t, 0) > 0:
        return None
    best, n = max(sc.items(), key=lambda kv: kv[1], default=(None, 0))
    if not best or n < 2 or best == t:
        return None
    return (f"This does not look like a {_display(t).split(' / ')[0]}: the template is "
            f"for a {_display(t).split(' / ')[0]}, but the document reads as a "
            f"{_display(best)}, and nothing on it names a "
            f"{_display(t).split(' / ')[0].lower()}. Check that the right template "
            f"was chosen.")


def apply(results, file_path, template_data):
    """Adds the two verdicts to every slot-path result of one file."""
    if not template_data or not str(file_path).lower().endswith(".pdf"):
        return results
    try:
        import pdfplumber
        with pdfplumber.open(str(file_path)) as pdf:
            text = "\n".join(p.extract_text() or "" for p in pdf.pages)
    except Exception:
        return results
    tpl = {"name": template_data.get("name"), "cells_text": template_cells_text(template_data)}
    wrong = type_mismatch(text, template_data.get("doc_type"))
    if not wrong:
        # Run S, 3b: the hint vocabulary can tie or stay silent on a garbled
        # page (jobs 61/65: a pay stub under a purchase-order template scored
        # 1 hint each for two other types); the template's OWN labels can't
        sm = None
        for r in results:
            ed = getattr(r, "extracted_data", None)
            if isinstance(ed, dict) and ed.get("slot_map"):
                sm = ed["slot_map"]
                break
        # a page that draws its text as outlines has no labels in its text
        # layer to count (ADP W-2, jobs 82/83/113: 2 of 30, right template)
        try:
            from text_layer import outlined_pages
            outlined = bool(outlined_pages(file_path))
        except Exception:
            outlined = True               # cannot tell: say nothing
        if sm and not outlined:
            wrong = label_mismatch(text, slot_labels(sm), template_data.get("name"))
    ignored = ignored_forms(text, tpl)
    if not (wrong or ignored):
        return results
    for r in results:
        ed = getattr(r, "extracted_data", None)
        if not isinstance(ed, dict) or "attention" not in ed:
            continue
        notes = ed.setdefault("validation_notes", [])
        if wrong:
            att = ed["attention"]
            att.append({"id": f"att-{len(att) + 1}", "text": wrong, "disposition": None})
            notes.append(f"NEEDS ATTENTION: {wrong}")
            ed["document_state"] = "NEEDS_ATTENTION"
        if ignored:
            say = (f"The document also prints Form {', '.join(ignored)}, which this "
                   f"template does not cover: no value of "
                   f"{'that form' if len(ignored) == 1 else 'those forms'} was "
                   f"extracted.")
            for f in ignored:
                figs = form_amounts(text, f)
                if figs:
                    say += (f" Form {f} prints {len(figs)} amount"
                            f"{'' if len(figs) == 1 else 's'}: {', '.join(figs[:14])}"
                            + (f" and {len(figs) - 14} more" if len(figs) > 14 else "")
                            + ".")
            notes.append(say)
            ed.setdefault("not_captured", []).append(say)
            ed.setdefault("validation", {}).setdefault("flagged_fields", []).append(
                {"ref": "document", "value": "", "reason": say})
            if ed.get("document_state") == "READY":
                ed["document_state"] = "NEEDS_REVIEW"
        ed["needs_review"] = True
        if hasattr(r, "needs_review"):
            r.needs_review = True
    return results
