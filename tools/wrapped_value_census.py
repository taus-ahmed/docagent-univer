"""Multi-line values beside a label across the corpus (Run S, 3c review).

    backend\\.venv\\Scripts\\python.exe tools\\wrapped_value_census.py s1 s3

For every FIELD value in two cached corpus runs (tools/corpus_metrics.py
results: `before` and `after`), decides from the source PDF's own lines
whether the value is a MULTI-LINE VALUE BESIDE A LABEL: the page's in-column
reading (text_layer.canonical_value) spells it without crossing a gutter,
no single printed line holds it whole, and its first words follow a label
(`Label:`) on the line where it starts. For each such field it reports the
level before and after, and the answer key's verdict where one exists
(tools/replay_key.py: what a person edited or accepted).

Prints the census per half (dev / report) and the changes, and writes
local_docs/corpus_metrics/wrapped_census_<before>_<after>.json.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "local_docs" / "corpus_metrics"


def _load(tag):
    out = {}
    for p in (OUT / f"{tag}_results").glob("*.json"):
        rec = json.loads(p.read_text(encoding="utf-8"))
        out[p.stem] = rec
    return out


def _lines_of(src):
    import pdfplumber
    from text_layer import read_page, flatten_pages
    with pdfplumber.open(str(src)) as pdf:
        return flatten_pages([read_page(pg)[1] for pg in pdf.pages])


def _line_str(ln):
    return " ".join(str(w.get("text", "")) for w in ln)


def is_wrapped_beside_label(value, lines) -> bool:
    from text_layer import canonical_value
    v = str(value or "").strip()
    if len(v.split()) < 2:
        return False
    canon = canonical_value(v, lines)
    if not canon or canon[1]:
        return False
    flat = re.sub(r"\s+", " ", v).casefold()
    texts = [_line_str(ln) for ln in lines if ln]
    if any(flat in re.sub(r"\s+", " ", t).casefold() for t in texts):
        return False                       # printed whole on one line
    head = " ".join(v.split()[:2]).casefold()
    return any(re.search(r":\s*" + re.escape(head), t.casefold()) for t in texts)


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    before, after = (argv + ["s1", "s3"])[:2]
    sys.path.insert(0, str(ROOT / "tools"))
    import replay_raw
    import replay_key as K
    replay_raw._setup()
    extra = K.load_extra()
    B, A = _load(before), _load(after)
    rows = []
    cache_lines = {}
    for key, rec in sorted(A.items()):
        meta, ed = rec["meta"], rec["ed"]
        src = replay_raw.find_source(meta["file"])
        if not src or src.suffix.lower() != ".pdf":
            continue
        if meta["file"] not in cache_lines:
            try:
                cache_lines[meta["file"]] = _lines_of(src)
            except Exception:
                cache_lines[meta["file"]] = []
        lines = cache_lines[meta["file"]]
        bed = (B.get(key) or {}).get("ed") or {}
        lab = {f["ref"]: f["row_label"] for f in (ed.get("slot_map") or {}).get("fields") or []}
        # the answer key for this document (fields only), if any
        job = replay_raw.load_job(meta["job"])
        doc = next((d for d in job["docs"] if str(d.get("id")) == str(meta["doc"])), None)
        keyed = K.key_from_doc(doc, extra.get(Path(meta["file"]).name.casefold())) if doc else None
        kf = (keyed or {}).get("fields") or {}
        for ref, v in (ed.get("extracted_fields") or {}).items():
            if not is_wrapped_beside_label(v, lines):
                continue
            label = lab.get(ref, ref)
            lv_a = ((ed.get("validation") or {}).get("confidence_map") or {}).get(ref)
            lv_b = ((bed.get("validation") or {}).get("confidence_map") or {}).get(ref)
            v_b = (bed.get("extracted_fields") or {}).get(ref)
            want = kf.get(str(label).casefold())
            verdict = None if want is None else (
                "right" if K.norm(want) == K.norm(v) else "wrong")
            rows.append({"job": meta["job"], "file": meta["file"], "half": meta["half"],
                         "label": label, "value": v, "before_value": v_b,
                         "level_before": lv_b, "level_after": lv_a, "key": verdict})
    docs = {(r["job"], r["file"]) for r in rows}
    files = {r["file"] for r in rows}
    print(f"multi-line values beside a label: {len(rows)} fields, {len(docs)} job documents, "
          f"{len(files)} distinct files")
    for half in ("dev", "report"):
        hs = [r for r in rows if r["half"] == half]
        low_b = sum(1 for r in hs if r["level_before"] == "low")
        low_a = sum(1 for r in hs if r["level_after"] == "low")
        kw_b = sum(1 for r in hs if r["key"] == "wrong" and r["value"] == r["before_value"])
        kr = sum(1 for r in hs if r["key"] == "right")
        kw = sum(1 for r in hs if r["key"] == "wrong")
        print(f"  {half}: {len(hs)} fields; Low before {low_b} -> after {low_a}; "
              f"key right {kr}, key wrong {kw}")
    for r in rows:
        if r["level_before"] != r["level_after"]:
            print(f"  changed: job {r['job']} {r['file'][:30]} {r['label']!r}: "
                  f"{r['level_before']} -> {r['level_after']} (key {r['key']})")
    (OUT / f"wrapped_census_{before}_{after}.json").write_text(
        json.dumps(rows, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
