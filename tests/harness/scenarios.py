"""
Scenario fixtures — the shapes the gold corpus cannot see.

The ten gold documents in `tests/gold/labels/` measure accuracy on shapes that
already worked. Five conditions the defect analysis names are not in that set
at all, and one of them is the product's own core use case:

    grouped_one_band        group headers, line items, section totals and the
                            grand total in ONE band. Every gold template splits
                            its groups into separate bands, so the commonest
                            shape in accounting has never been measured.
    wrapped_values          figures the PDF wrapped inside a narrow box.
    selection_markers       a ticked option and an unticked one, both printed.
    no_invention_vs_semantic_match
                            one document asking the SAME mechanism to fill a
                            differently-worded label and to refuse a plausible
                            substitute.
    multi_document          three invoices in one file.

DELIBERATELY NOT WIRED INTO THE MAIN HARNESS. Adding these to the gold set
would move the headline accuracy number and make it incomparable with every
figure recorded before today, while mixing "how well does it do the things it
does" with "does it do these things at all". They are scored separately and
reported separately.

A scenario is one JSON file under `tests/fixtures/scenarios/`. It names either
a corpus PDF (`pdf`), several to merge (`merge`), or an inline text layer
(`text`) for a condition no corpus document contains.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from tests.harness import bootstrap as _bs

SCENARIO_DIR = _bs.REPO_DIR / "tests" / "fixtures" / "scenarios"


def load(name=None):
    files = sorted(SCENARIO_DIR.glob("*.json"))
    out = []
    for f in files:
        if name and f.stem != name:
            continue
        s = json.loads(f.read_text(encoding="utf-8"))
        s["name"] = f.stem
        out.append(s)
    return out


# ── reading the document ────────────────────────────────────────────────────

def document(scenario, tmp_dir):
    """(page_texts, page_lines) for whatever the scenario points at."""
    if scenario.get("text"):
        return [scenario["text"]], []

    import pdfplumber
    from text_layer import read_page

    path = path_for(scenario, tmp_dir)
    from text_layer import acroform_widgets
    widgets = acroform_widgets(path)
    texts, lines = [], []
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages):
            t, ln, _ = read_page(page, widgets.get(i) or [])
            texts.append(t)
            lines.append(ln)
    return texts, lines


def path_for(scenario, tmp_dir):
    """The file on disk this scenario reads, building it if it is a merge."""
    if scenario.get("merge"):
        from pypdf import PdfReader, PdfWriter
        out = Path(tmp_dir) / f"{scenario['name']}.pdf"
        if not out.exists():
            w = PdfWriter()
            for n in scenario["merge"]:
                for p in PdfReader(str(_bs.PDF_DIR / n)).pages:
                    w.add_page(p)
            w.write(str(out))
        return out
    if scenario.get("fixture_pdf"):
        return _bs.REPO_DIR / "tests/fixtures" / scenario["fixture_pdf"]
    return _bs.PDF_DIR / scenario["pdf"] if scenario.get("pdf") else None


def run(scenario, tmp_dir, orchestrator):
    """The real pipeline on one scenario.

    `via: "pipeline"` goes through `run_extraction` from a real file, which is
    the only way to exercise anything happening BEFORE slot extraction —
    document boundaries above all. Everything else calls `run_slot_extraction`
    directly, which is cheaper and keeps the scenario's own text layer.

    Returns `extracted_data`, or a LIST of them when the file held several
    documents.
    """
    import time

    from slot_extractor import run_slot_extraction
    from template_shape import compute_shape

    grid = scenario["grid"]
    if scenario.get("via") == "pipeline":
        from extractor import run_extraction
        results = run_extraction(
            orchestrator, path_for(scenario, tmp_dir),
            {"mode": "layout", "layout": grid,
             "doc_type": scenario.get("doc_type", "")})
        return [r.extracted_data for r in results]

    texts, lines = document(scenario, tmp_dir)
    shape = compute_shape(grid, log=lambda _m: None)
    return run_slot_extraction(
        orchestrator, f"{scenario['name']}.pdf",
        {"layout": grid, "shape": shape}, None, page_images=[],
        doc_text="\n\n".join(texts), doc_text_pages=texts,
        file_type="digital_pdf", default_doc_type=scenario.get("doc_type", ""),
        start=time.time(), page_lines=lines)[0].extracted_data


# ── scoring ─────────────────────────────────────────────────────────────────

def _norm(v):
    """Compare on content, not on how the number was spelled."""
    t = re.sub(r"\s+", " ", str(v or "")).strip()
    if not t:
        return ""
    bare = t.replace(",", "")
    for sym in "$£€₹¥":
        bare = bare.replace(sym, "")
    try:
        return f"{float(bare):.4f}"
    except ValueError:
        return t.casefold()


def score(scenario, ed):
    """(percent, [(what, expected, got, ok)]) — one line per checked cell.

    A scenario whose file held several documents is scored on the FIRST of
    them; `extras` is what checks the others are there at all.
    """
    checks = []
    expect = scenario.get("expect") or {}
    if isinstance(ed, list):
        ed = ed[0] if ed else {}

    by_label = {k: d.get("value", "")
                for k, d in (ed.get("extracted_data") or {}).items()}

    for label, want in (expect.get("fields") or {}).items():
        got = by_label.get(label, "")
        checks.append((f"field {label!r}", want, got,
                       _norm(got) == _norm(want)))

    for table, rows in (expect.get("tables") or {}).items():
        got_rows = ed.get(f"{table}_rows") or []
        # match on the first column, which is the row's own identity
        index = {}
        for r in got_rows:
            keys = [k for k in r if not k.startswith("_")]
            if keys:
                index.setdefault(_norm(r.get(keys[0])), r)
        for want_row in rows:
            got = index.get(_norm(want_row[0]))
            if got is None:
                checks.append((f"{table} row {want_row[0]!r}",
                               " | ".join(want_row), "ROW MISSING", False))
                continue
            keys = [k for k in got if not k.startswith("_")]
            for i, want in enumerate(want_row):
                g = got.get(keys[i], "") if i < len(keys) else ""
                checks.append((f"{table}[{want_row[0]}].{keys[i] if i < len(keys) else i}",
                               want, g, _norm(g) == _norm(want)))

    ok = sum(1 for _, _, _, good in checks if good)
    pct = (100.0 * ok / len(checks)) if checks else 0.0
    return pct, checks


def extras(scenario, ed):
    """Scenario-specific checks that are not cell comparisons."""
    out = []
    blob = json.dumps(ed, ensure_ascii=False)

    first = ed[0] if isinstance(ed, list) and ed else ed
    want_docs = (scenario.get("expect") or {}).get("documents")
    if want_docs:
        got = len(ed) if isinstance(ed, list) else 1
        out.append((f"the file is read as {want_docs} documents",
                    got == want_docs, str(got)))
    if isinstance(ed, list):
        ed = ed[0] if ed else {}

    for label in scenario.get("must_stay_empty") or []:
        got = ((ed.get("extracted_data") or {}).get(label) or {}).get("value", "")
        out.append((f"{label!r} must stay empty", not str(got).strip(),
                    repr(got)))

    # Checked against the extracted VALUES, not the whole payload: a source
    # span legitimately quotes the entire line an option sits on, unselected
    # neighbours included, and that is evidence rather than an answer.
    values = " | ".join(
        str((d or {}).get("value", ""))
        for d in ((first if isinstance(ed, list) else ed)
                  .get("extracted_data") or {}).values())
    for phrase in scenario.get("negated") or []:
        out.append((f"{phrase!r} (an UNSELECTED option) must not be reported",
                    phrase.casefold() not in values.casefold(), phrase))

    for label in scenario.get("structure_rows") or []:
        out.append((f"structure row {label!r} present",
                    label.casefold() in blob.casefold(), label))

    want = (scenario.get("expect") or {}).get("invoice_numbers")
    if want:
        found = sorted(set(re.findall(r"INV-2024-\d+", blob)))
        out.append((f"all {len(want)} documents represented",
                    sorted(want) == found, ", ".join(found) or "none"))
    return out
