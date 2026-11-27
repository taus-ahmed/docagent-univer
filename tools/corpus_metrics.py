"""Corpus-wide metrics on the stored real answers (Run S, Stage 0).

    backend\\.venv\\Scripts\\python.exe tools\\corpus_metrics.py --tag before
    backend\\.venv\\Scripts\\python.exe tools\\corpus_metrics.py --tag after --compare before

Replays EVERY job in local_docs/raw (tools/replay_raw.py: the stored model
answer, the code on disk, no network, no key) and measures each document
against its own source PDF's text layer. Never per job only: the totals are
corpus-wide, split into the two halves below.

HALVES. A document belongs to the DEV half or the REPORT half by a hash of
its FILE NAME (`half_of`), so every job of one file lands in one half and
nothing tuned on a dev file can leak into the report half. Engine changes
are developed against `dev` and reported on `report` as well.

METRICS, per document, summed:

  tokens           structural tokens printed in the text layer: numbers
                   (amounts, identifiers of 3+ digits, dates) on lines that
                   are not page furniture (a line repeated on 2+ pages, the
                   top/bottom 4% of the page) and not paragraph prose
  tokens_kept      of those, held by some value of the output
  tokens_said      not kept, but named in an attention reason or a
                   `not_captured` sentence (visible, so not silent)
  tokens_silent    neither kept nor said: "printed but not extracted",
                   and nothing tells the reader
  amounts_printed  money-shaped structural tokens (two decimals or a
                   currency symbol)
  amounts_missing  of those, not kept (said or not)
  silent_blanks    empty FIELD slots whose label the page prints, with no
                   flag, no review reason and no attention reason naming it
  low / amber      values by review status (amber = unverified/grounded and
                   review_required, the export's amber fill)
  key_right / key_wrong / false_low / wrong_high
                   against the answer key of tools/replay_key.py (what a
                   person edited or accepted, and answers_extra.csv):
                   false_low = a key-right value marked Low; wrong_high =
                   a key-wrong value at high/grounded confidence

Results go to local_docs/corpus_metrics/<tag>.json (+ .md). The replayed
results are cached in local_docs/corpus_metrics/<tag>_results/ so later
analyses (amber reasons, coverage examples) need no second replay.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "local_docs" / "corpus_metrics"
sys.path.insert(0, str(ROOT / "tools"))


def half_of(filename: str) -> str:
    h = hashlib.sha1(Path(str(filename)).name.casefold().encode("utf-8")).hexdigest()
    return "dev" if int(h[:2], 16) % 2 == 0 else "report"


# ── the page's structural tokens ───────────────────────────────────────────

_NUM = re.compile(r"\(?-?[$€£]?\d[\d,./-]*\d\)?-?|\(?[$€£]?\d\)?")
_DATE = re.compile(r"^\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?$|^\d{4}-\d{2}-\d{2}$")


def _digits(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def _amount(tok):
    t = tok.strip().strip(".,;:")
    if not re.search(r"\d", t):
        return None
    if not (re.search(r"\.\d{2}\)?-?$", t) or re.search(r"[$€£]", t)):
        return None
    s = re.sub(r"[^\d.\-()]", "", t)
    neg = s.startswith("(") or s.startswith("-") or s.endswith("-")
    s = s.strip("()-")
    try:
        v = Decimal(s)
    except InvalidOperation:
        return None
    return -v if neg else v


def token_kind(tok: str):
    t = tok.strip().strip(".,;:")
    if _amount(t) is not None:
        return "amount"
    if _DATE.match(t):
        return "date"
    if len(_digits(t)) >= 3:
        return "id"
    return None


def _lines_of(words, tol=2.5):
    words = sorted(words, key=lambda w: (round(w["top"], 1), w["x0"]))
    lines = []
    for w in words:
        if lines and abs(w["top"] - lines[-1][0]["top"]) <= tol:
            lines[-1].append(w)
        else:
            lines.append([w])
    return [sorted(l, key=lambda w: w["x0"]) for l in lines]


def _shape(text):
    return re.sub(r"\d", "#", re.sub(r"\s+", " ", text.strip().casefold()))


def is_paragraph(texts) -> bool:
    n = len(texts)
    joined = " ".join(texts).strip()
    return n >= 12 or (n >= 8 and joined.endswith((".", "?")))


def page_tokens(pdf_path):
    """[(page_no, token_text, kind, line_text)] structural tokens, or None
    when the file cannot be read."""
    try:
        import pdfplumber
    except ImportError:
        return None
    out, pages = [], []
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            for n, page in enumerate(pdf.pages, 1):
                ws = page.extract_words(keep_blank_chars=False, use_text_flow=False)
                pages.append((n, float(page.height or 792), _lines_of(ws)))
    except Exception:
        return None
    seen = {}
    for n, _h, lines in pages:
        for l in lines:
            seen.setdefault(_shape(" ".join(w["text"] for w in l)), set()).add(n)
    for n, h, lines in pages:
        for l in lines:
            texts = [w["text"] for w in l]
            line = " ".join(texts)
            top = l[0]["top"]
            if len(pages) > 1 and len(seen.get(_shape(line), ())) >= 2:
                continue                         # repeated: furniture / headings
            if top < 0.04 * h or top > 0.96 * h:
                continue
            if is_paragraph(texts):
                continue
            if re.search(r"\bpage\s+\d+(\s+of\s+\d+)?\b", line, re.I) and len(texts) <= 6:
                continue
            for t in texts:
                k = token_kind(t)
                if k:
                    out.append((n, t.strip().strip(".,;:"), k, line))
    return out


# ── what the output holds ──────────────────────────────────────────────────

def output_values(ed) -> list:
    vals = []
    for v in (ed.get("extracted_fields") or {}).values():
        vals.append(v)
    for k, rows in ed.items():
        if (k.endswith("_rows") or k.endswith("_subtotals")) and isinstance(rows, list):
            for r in rows:
                if isinstance(r, dict):
                    vals += [x for c, x in r.items() if not str(c).startswith("_")]
        if k.endswith("_group_key") and isinstance(rows, str):
            vals.append(rows)
    for e in (ed.get("extracted_data") or {}).values():
        if isinstance(e, dict):
            vals.append(e.get("value"))
    return [str(v) for v in vals if v is not None and str(v).strip()]


def said_texts(ed) -> list:
    out = [a.get("text", "") for a in ed.get("attention") or [] if isinstance(a, dict)]
    out += [str(x) for x in ed.get("not_captured") or []]
    out += [str(x) for x in ed.get("validation_notes") or []]
    return out


class Holder:
    def __init__(self, values):
        self.amounts = set()
        self.digit_strings = []
        for v in values:
            for t in re.findall(r"\(?-?[$€£]?[\d][\d,.]*\)?", v):
                a = _amount(t)
                if a is not None:
                    self.amounts.add(abs(a))
            d = _digits(v)
            if d:
                self.digit_strings.append(d)
            for t in re.findall(r"\d[\d,]*(?:\.\d+)?", v):
                try:
                    self.amounts.add(abs(Decimal(t.replace(",", ""))))
                except InvalidOperation:
                    pass

    def holds(self, tok, kind) -> bool:
        if kind == "amount":
            a = _amount(tok)
            return a is not None and abs(a) in self.amounts
        d = _digits(tok)
        return bool(d) and any(d in s for s in self.digit_strings)


def _in_said(tok, said) -> bool:
    return any(tok in s for s in said)


# ── per document ───────────────────────────────────────────────────────────

def doc_metrics(ed, source, key=None):
    from app.core import review as R
    m = {k: 0 for k in ("tokens", "tokens_kept", "tokens_said", "tokens_silent",
                        "amounts_printed", "amounts_missing", "silent_blanks",
                        "values", "low", "amber", "key_right", "key_wrong",
                        "false_low", "wrong_high")}
    toks = page_tokens(source) if str(source).lower().endswith(".pdf") else None
    holder = Holder(output_values(ed))
    said = said_texts(ed)
    examples = []
    for n, tok, kind, line in toks or []:
        m["tokens"] += 1
        kept = holder.holds(tok, kind)
        if kind == "amount":
            m["amounts_printed"] += 1
            if not kept:
                m["amounts_missing"] += 1
        if kept:
            m["tokens_kept"] += 1
        elif _in_said(tok, said):
            m["tokens_said"] += 1
        else:
            m["tokens_silent"] += 1
            if len(examples) < 12:
                examples.append(f"p{n} {tok!r} in {line[:70]!r}")
    vals = R.document_values(ed)
    for v in vals:
        if v["status"] in ("empty", "empty_flagged"):
            continue
        m["values"] += 1
        if v["status"] == "low":
            m["low"] += 1
        elif v["status"] in ("unverified", "unknown") or (v.get("review_required") and v["status"] != "low"):
            m["amber"] += 1
    # silent blanks: an empty field whose label is printed, with nothing said
    text = ""
    if toks is not None:
        try:
            import pdfplumber
            with pdfplumber.open(str(source)) as pdf:
                text = "\n".join((p.extract_text() or "") for p in pdf.pages).casefold()
        except Exception:
            text = ""
    said_all = " ".join(said).casefold()
    for v in vals:
        if v["kind"] != "field" or v["status"] != "empty":
            continue
        lab = str(v.get("label") or "").strip()
        if len(lab) >= 3 and lab.casefold() in text and lab.casefold() not in said_all:
            m["silent_blanks"] += 1
    if key is not None:
        import replay_key as K
        s = K.score_doc(key, _as_keyed(ed))
        m["key_right"], m["key_wrong"] = s["right"], s["wrong"]
        wrong_vals = {K.norm(h) for _l, _w, h in s["wrong_items"]}
        right_vals = set()
        for label, want in key.get("fields", {}).items():
            right_vals.add(K.norm(want))
        for rows in key.get("tables", {}).values():
            for r in rows:
                right_vals |= {K.norm(x) for x in r.values() if str(x).strip()}
        for v in vals:
            nv = K.norm(v.get("value"))
            if v["status"] == "low" and nv in right_vals and nv not in wrong_vals:
                m["false_low"] += 1
            if v.get("level") in ("high", "grounded") and nv in wrong_vals:
                m["wrong_high"] += 1
    return m, examples


def _as_keyed(ed):
    """Run T: the answer key names columns and fields as the result did when
    a person accepted it. A no-template result now carries the page's own
    printed names (`printed_renames`); for SCORING only, the key's names are
    put back, so a rename is not counted as a lost or a new value."""
    import copy
    ren = (ed or {}).get("printed_renames") or {}
    if not ren:
        return ed
    out = copy.deepcopy(ed)
    for tname, m in (ren.get("tables") or {}).items():
        back = {new: old for old, new in m.items()}
        for r in out.get(f"{tname}_rows") or []:
            for new, old in back.items():
                if new in r:
                    r[old] = r.pop(new)
    kv = out.get("extracted_data") or {}
    for _ref, fr in (ren.get("fields") or {}).items():
        if isinstance(fr, dict) and fr.get("to") in kv:
            kv[fr["from"]] = kv.pop(fr["to"])
    return out


def run(tag, jobs=None):
    import replay_raw
    import replay_key as K
    replay_raw._setup()
    extra = K.load_extra()
    cache = OUT / f"{tag}_results"
    cache.mkdir(parents=True, exist_ok=True)
    job_ids = sorted((int(p.name) for p in replay_raw.RAW.iterdir()
                      if p.name.isdigit() and replay_raw.has_raw(p.name)))
    if jobs:
        job_ids = [j for j in job_ids if j in set(jobs)]
    per_doc, skipped = [], []
    t0 = time.time()
    for jid in job_ids:
        job = replay_raw.load_job(jid)
        td = replay_raw.template_data_of(job["template"])
        templated = bool(job["template"])
        for doc in job["docs"]:
            name = doc.get("original_filename") or doc.get("filename") or ""
            src = replay_raw.find_source(name)
            if not src or not doc.get("raw_llm_response"):
                skipped.append(f"{jid}/{doc.get('id')} {name}: "
                               + ("no source" if not src else "no stored answer"))
                continue
            k = K.key_from_doc(doc, extra.get(Path(name).name.casefold()))
            try:
                outs = replay_raw.replay_doc(doc, td, src)
            except Exception as e:                       # a replay crash is a finding
                skipped.append(f"{jid}/{doc.get('id')} {name}: replay raised {e!r}")
                continue
            for i, (ed, _missing, _r) in enumerate(outs):
                m, ex = doc_metrics(ed, src, k if i == 0 else None)
                rec = {"job": jid, "doc": doc.get("id"), "part": i, "file": name,
                       "half": half_of(name), "templated": templated,
                       "metrics": m, "silent_examples": ex}
                per_doc.append(rec)
                (cache / f"{jid}_{doc.get('id')}_{i}.json").write_text(
                    json.dumps({"meta": rec, "ed": ed}, default=str), encoding="utf-8")
    report = {"tag": tag, "seconds": round(time.time() - t0), "docs": per_doc,
              "skipped": skipped, "totals": totals(per_doc)}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{tag}.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    return report


def totals(per_doc):
    out = {}
    for half in ("dev", "report", "all"):
        for mode in ("templated", "no_template", "all"):
            sel = [d for d in per_doc
                   if (half == "all" or d["half"] == half)
                   and (mode == "all" or d["templated"] == (mode == "templated"))]
            t = {"documents": len(sel)}
            for d in sel:
                for k, v in d["metrics"].items():
                    t[k] = t.get(k, 0) + v
            if t.get("tokens"):
                t["token_coverage"] = round(100 * t["tokens_kept"] / t["tokens"], 1)
            out[f"{half}/{mode}"] = t
    return out


COLS = ["documents", "tokens", "token_coverage", "tokens_silent", "amounts_printed",
        "amounts_missing", "silent_blanks", "values", "low", "amber",
        "key_right", "key_wrong", "false_low", "wrong_high"]


def markdown(rep, before=None):
    lines = [f"# Corpus metrics: {rep['tag']}", "",
             "| slice | " + " | ".join(COLS) + " |",
             "|---|" + "---:|" * len(COLS)]
    for sl, t in rep["totals"].items():
        b = (before or {}).get("totals", {}).get(sl) if before else None
        cells = []
        for c in COLS:
            v = t.get(c, 0)
            cells.append(f"{b.get(c, 0)}→{v}" if b is not None and b.get(c, 0) != v else f"{v}")
        lines.append(f"| {sl} | " + " | ".join(cells) + " |")
    lines += ["", f"Skipped: {len(rep['skipped'])}"] + [f"- {s}" for s in rep["skipped"]]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tag", required=True)
    ap.add_argument("--compare")
    ap.add_argument("--jobs", nargs="*", type=int)
    a = ap.parse_args(argv)
    rep = run(a.tag, a.jobs)
    before = None
    if a.compare and (OUT / f"{a.compare}.json").exists():
        before = json.loads((OUT / f"{a.compare}.json").read_text(encoding="utf-8"))
    md = markdown(rep, before)
    (OUT / f"{a.tag}.md").write_text(md, encoding="utf-8")
    sys.stdout.buffer.write(md.encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
