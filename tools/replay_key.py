"""The replay answer key, and right / wrong / missing on the replay (Run Q Phase 3, item 8).

    backend\\.venv\\Scripts\\python.exe tools\\replay_key.py [--save before.json] [--compare before.json] [job ...]

Ground truth comes only from what a PERSON did, stored in
local_docs/raw/<job>/docs/*.json:

  * a value edited in review (`confidence: edited`, a row's `_edited` cells,
    the edit log's `new`) is the corrected value;
  * in a document a person marked reviewed (`review.document_reviewed`),
    every value they left standing is accepted as correct;
  * local_docs/answers_extra.csv (values read off the documents by hand).

Each keyed document is replayed (tools/replay_raw.py: the stored model answer,
the post-model code on disk, no network) and scored:

  right    the replay holds the key's value
  wrong    the replay holds a different value
  missing  the key has a value and the replay none
  extra    a reviewed document's slot the person left empty, or a table row
           the person never had, now holds a value

Rows the replay cannot produce because a later model call has no stored
answer show as missing in every run alike, so before/after stays comparable.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "local_docs" / "raw"
EXTRA = ROOT / "local_docs" / "answers_extra.csv"


def norm(v) -> str:
    return re.sub(r"\s+", " ", str(v if v is not None else "")).strip().casefold()


def _ed(doc):
    e = doc.get("extraction_json") or {}
    if isinstance(e, str):
        e = json.loads(e or "{}")
    return e or {}


def _tables(ed):
    out = {}
    for k, v in ed.items():
        if k.endswith("_rows") and isinstance(v, list) and k != "table_rows" or k == "table_rows":
            if isinstance(v, list):
                rows = [r for r in v if isinstance(r, dict)]
                if rows:
                    out["table" if k == "table_rows" else k[:-5]] = rows
    return out


def _cols(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def _fields(ed):
    out = {}
    for label, v in (ed.get("extracted_data") or {}).items():
        val = v.get("value") if isinstance(v, dict) else v
        if isinstance(val, (str, int, float)) and str(val).strip():
            out[label.casefold()] = str(val)
    return out


def key_from_doc(doc, extra_fields=None):
    """{"kind", "fields": {label: value}, "tables": {name: [row]},
    "cells": [(table, row_index, column, value)]}, or None."""
    ed = _ed(doc)
    reviewed = bool((ed.get("review") or {}).get("document_reviewed"))
    if reviewed:
        k = {"kind": "reviewed", "fields": _fields(ed),
             "tables": {t: [_cols(r) for r in rows] for t, rows in _tables(ed).items()},
             "cells": []}
    else:
        fields = {label.casefold(): str(v.get("value"))
                  for label, v in (ed.get("extracted_data") or {}).items()
                  if isinstance(v, dict) and v.get("confidence") == "edited"}
        cells = [(t, i, c, str(r.get(c, "")))
                 for t, rows in _tables(ed).items() for i, r in enumerate(rows)
                 for c in (r.get("_edited") or [])]
        k = {"kind": "edited", "fields": fields, "tables": {}, "cells": cells}
    # hand-read answers are matched the way tools/score_runs.py matches them
    # (a field to the slot whose label holds its words, format-tolerant)
    k["answers"] = list((extra_fields or {}).items())
    if k["answers"] and not (k["fields"] or k["tables"] or k["cells"]):
        k["kind"] = "answers"
    if not (k["fields"] or k["tables"] or k["cells"] or k["answers"]):
        return None
    return k


def score_doc(key, replay_ed):
    s = {"right": 0, "wrong": 0, "missing": 0, "extra": 0, "wrong_items": [], "missing_items": []}
    got = {label: v for label, v in _fields(replay_ed).items()}
    for label, want in key["fields"].items():
        have = got.get(label, "")
        if not str(have).strip():
            s["missing"] += 1
            s["missing_items"].append(label)
        elif norm(have) == norm(want):
            s["right"] += 1
        else:
            s["wrong"] += 1
            s["wrong_items"].append((label, want, have))
    if key["kind"] == "reviewed":
        s["extra"] += sum(1 for label, v in got.items() if label not in key["fields"])
    if key.get("answers"):
        import score_runs
        vals, rows = score_runs._values(replay_ed), score_runs._rows(replay_ed)
        for field, want in key["answers"]:
            verdict, _flag, note = score_runs.score_field(field, want, vals, rows)
            c = {"correct": "right"}.get(verdict, verdict)
            s[c] += 1
            if c == "wrong":
                s["wrong_items"].append((field, want, note))
            elif c == "missing":
                s["missing_items"].append(f"{field} ({note})")
    rtab = _tables(replay_ed)
    for t, krows in key["tables"].items():
        rrows = [_cols(r) for r in rtab.get(t, [])]
        k_left, r_left = [], list(range(len(rrows)))
        for kr in krows:
            sig = {c: norm(v) for c, v in kr.items()}
            hit = next((j for j in r_left
                        if all(norm(rrows[j].get(c, "")) == sig[c] for c in sig)), None)
            if hit is None:
                k_left.append(kr)
            else:
                r_left.remove(hit)
                s["right"] += sum(1 for v in kr.values() if str(v).strip())
        for kr in k_left:
            cols = [c for c, v in kr.items() if str(v).strip()]
            best, bj = 0, None
            for j in r_left:
                n = sum(1 for c in cols if norm(rrows[j].get(c, "")) == norm(kr[c]))
                if n > best:
                    best, bj = n, j
            if bj is not None and 2 * best >= len(cols):
                r_left.remove(bj)
                for c in cols:
                    have = rrows[bj].get(c, "")
                    if norm(have) == norm(kr[c]):
                        s["right"] += 1
                    elif not str(have).strip():
                        s["missing"] += 1
                    else:
                        s["wrong"] += 1
                        s["wrong_items"].append((f"{t}.{c}", kr[c], have))
            else:
                s["missing"] += len(cols)
                s["missing_items"].append(f"{t} row {kr}")
        for j in r_left:
            s["extra"] += sum(1 for v in rrows[j].values() if str(v).strip())
    for t, i, c, want in key["cells"]:
        rows = [_cols(r) for r in rtab.get(t, [])]
        if any(norm(r.get(c, "")) == norm(want) for r in rows):
            s["right"] += 1
        elif i < len(rows) and str(rows[i].get(c, "")).strip():
            s["wrong"] += 1
            s["wrong_items"].append((f"{t}[{i}].{c}", want, rows[i].get(c)))
        else:
            s["missing"] += 1
            s["missing_items"].append(f"{t}[{i}].{c}")
    return s


def load_extra(path=EXTRA):
    out = {}
    if not path.exists():
        return out
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            vals = list(row.values())
            if len(vals) >= 3 and vals[0]:
                out.setdefault(Path(vals[0]).name.casefold(), {})[vals[1]] = vals[2]
    return out


def keys_for_job(job_id, extra):
    from replay_raw import load_job
    out = []
    for doc in load_job(job_id)["docs"]:
        name = (doc.get("original_filename") or doc.get("filename") or "")
        k = key_from_doc(doc, extra.get(Path(name).name.casefold()))
        if k:
            out.append((doc, k))
    return out


def run(job_ids):
    sys.path.insert(0, str(ROOT / "tools"))
    import replay_raw
    replay_raw._setup()
    extra = load_extra()
    per = {}
    for jid in job_ids:
        if not replay_raw.has_raw(jid):
            continue
        keyed = keys_for_job(jid, extra)
        if not keyed:
            continue
        td = replay_raw.template_data_of(replay_raw.load_job(jid)["template"])
        for doc, k in keyed:
            name = doc.get("original_filename") or doc.get("filename")
            src = replay_raw.find_source(name)
            if not src or not doc.get("raw_llm_response"):
                continue
            outs = replay_raw.replay_doc(doc, td, src)
            best = max((score_doc(k, ed) for ed, _m, _r in outs),
                       key=lambda s: (s["right"], -s["wrong"]), default=None)
            if best:
                best["kind"] = k["kind"]
                per[f"{jid}/{doc.get('id')} {name}"] = best
    return per


def totals(per):
    return {c: sum(s[c] for s in per.values()) for c in ("right", "wrong", "missing", "extra")}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("jobs", nargs="*")
    ap.add_argument("--save")
    ap.add_argument("--compare")
    ap.add_argument("--detail", action="store_true")
    a = ap.parse_args(argv)
    save = Path(a.save).resolve() if a.save else None
    compare = Path(a.compare).resolve() if a.compare else None
    jobs = a.jobs or sorted((p.name for p in RAW.iterdir() if p.is_dir()), key=int)
    per = run(jobs)
    before = json.loads(compare.read_text(encoding="utf-8")) if compare else {}
    for name, s in per.items():
        b = before.get(name)
        line = " ".join(f"{c} {s[c]}" + (f" (was {b[c]})" if b and b[c] != s[c] else "")
                        for c in ("right", "wrong", "missing", "extra"))
        print(f"{name} [{s['kind']}]: {line}")
        if a.detail:
            for w in s["wrong_items"][:8]:
                print("   wrong", w)
            for m in s["missing_items"][:8]:
                print("   missing", str(m)[:160])
    t = totals(per)
    print(f"TOTAL {len(per)} documents: " + " ".join(
        f"{c} {t[c]}" + (f" (was {totals(before)[c]})" if before else "") for c in t))
    if save:
        save.write_text(json.dumps(per, default=str, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
