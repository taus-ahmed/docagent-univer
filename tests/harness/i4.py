"""
I4 evidence runs — the same document against a template whose band columns do
NOT match the table it points at.

    python -m tests.harness.i4 --mode record      # live, costs money
    python -m tests.harness.i4 --mode replay      # offline, from the cache

WHY A SEPARATE RUNNER. The recorded corpus cannot see I4. Across all 374 cached
responses — 166 with tables, 1,807 rows — the model never once returned a row
keyed differently from its table's other rows, so the precondition for the
silent drop at `slot_extractor.py:1016` is never met. That is not evidence the
defect is rare; it is evidence that every template in the corpus was drawn to
fit the document it was pointed at. A user's template is not.

So this runner perturbs the TEMPLATE and leaves everything else alone. Three
variants of each gold band, and the third is the control that decides the
design:

    narrowed   fewer columns than the document's table has — the label column
               and the last value column, the middle dropped. Only for bands of
               3+ columns; R5 refuses a one-column table.
    widened    two columns the document does not have at all.
    reworded   the SAME columns under different words. A legitimate template:
               a user writes "Particulars" where the document prints
               "Description". Nothing is missing and nothing is extra.

`reworded` is the noise measurement. If the model answers a reworded template
with the document's own words rather than the template's, then off-schema keys
are ordinary on correct templates, and a flag per key would fire on templates
that are not wrong — which is the same class of bug as the silent failure it
would replace. In that case the signal has to be per ROW.

NO DOCUMENT-SPECIFIC CONSTANTS. `_SYNONYM` is a generic accounting word list
applied by lookup to whatever heading a band has; `_EXTRA` is two generic
column names. Neither mentions a document, and a heading outside the list is
rewritten by role (label column -> "Particulars", value column -> "Value"),
not by name.

EVERY LIVE RUN STORES ITS RAW RESPONSE, twice — the same rule as round2.py:

  tests/llm_cache/<key>.json      what replay serves, keyed by the full request
  tests/fixtures/i4_raw/<run>.json  the same answer, readable, with the commit,
                                  model and time — so it can be argued with,
                                  not just replayed
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import io
import json
import re
import subprocess
import time
from collections import Counter

from tests.harness import bootstrap as bs

RAW_DIR = bs.TESTS_DIR / "fixtures" / "i4_raw"

#: Generic accounting synonyms — a wording difference a real user would write,
#: not a renaming of any particular document's columns.
_SYNONYM = {
    "description": "Particulars",
    "item / description": "Particulars",
    "item": "Particulars",
    "amount": "Value",
    "date": "Posted",
    "type": "Kind",
    "qty": "Units",
    "unit": "UoM",
    "unit price": "Rate",
    "unit cost": "Rate",
    "total": "Line Total",
    "debit": "Withdrawals",
    "credit": "Deposits",
    "balance": "Running Balance",
    "category": "Class",
}

#: Columns no accounting document in the corpus prints. Deliberately plausible:
#: a column a user might draw and the document simply does not have.
_EXTRA = ["Ref", "Notes"]

VARIANTS = ("narrowed", "widened", "reworded")


# ── grid surgery ─────────────────────────────────────────────────────────────

def _cell(grid, r, c):
    return (grid.get("cells") or {}).get(f"{r},{c}")


def _set(grid, r, c, value):
    grid.setdefault("cells", {})[f"{r},{c}"] = {"value": value, "style": {}}


def _drop(grid, r, c):
    (grid.get("cells") or {}).pop(f"{r},{c}", None)


def _reword(header, role):
    """A different word for the same column. Role decides the fallback, so a
    section heading ("CURRENT ASSETS") becomes a generic label heading rather
    than being left alone — the point is that NO template heading matches the
    document's printed one."""
    h = re.sub(r"\s+", " ", str(header or "").strip()).casefold()
    if h in _SYNONYM:
        return _SYNONYM[h]
    return "Particulars" if role == "label" else "Value"


def perturb(grid, bands, variant):
    """(grid, note) — the same template with its band columns perturbed.

    Returns (None, why) when the variant does not apply to this template.
    """
    g = copy.deepcopy(grid)
    touched = []
    for b in bands:
        if b.get("orientation") == "columns":
            # A transposed band's headings run DOWN its first column. Perturbing
            # it is a different experiment (the writer transposes, the model
            # does not), and it is not what I4 was observed on.
            continue
        cols = b.get("columns") or []
        hr = b["header_row"]
        if variant == "reworded":
            # A 2-column band takes its NAME from its label heading, so
            # rewording that heading renames the band — and five balance-sheet
            # sections all reworded to "Particulars" collapse into one key in
            # `tables_out`, which would destroy the measurement rather than
            # perturb it. The value column is the one the model keys its
            # amounts under and is reworded in every case.
            skip = {cols[0]["col"]} if len(cols) == 2 else set()
            for c in cols:
                if c["col"] in skip:
                    continue
                _set(g, hr, c["col"], _reword(c["header"], c.get("role")))
            touched.append(b["name"])
        elif variant == "widened":
            last = max(c["col"] for c in cols)
            for i, extra in enumerate(_EXTRA, 1):
                _set(g, hr, last + i, extra)
            touched.append(b["name"])
        elif variant == "narrowed":
            if len(cols) < 3:
                continue          # R5: a table needs two columns
            # The middle headings are not merely deleted: a gap in the heading
            # row is not a narrower band, it is NO band — detection reads a run
            # of adjacent headings, so deleting the middle ones leaves two
            # columns that are not next to each other and the band disappears.
            # The kept pair is made adjacent instead, which is what a user
            # drawing a two-column version of the same table actually draws.
            first, last = cols[0], cols[-1]
            for c in cols:
                _drop(g, hr, c["col"])
            _set(g, hr, first["col"], first["header"])
            _set(g, hr, first["col"] + 1, last["header"])
            touched.append(b["name"])
    if not touched:
        return None, f"{variant} does not apply to this template"
    return g, f"{variant}: {', '.join(touched)}"


# ── running ──────────────────────────────────────────────────────────────────

def _commit():
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True,
                              cwd=str(bs.REPO_DIR)).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def template_data_for(grid, doc_type):
    """A grid -> template_data, exactly as production loads a saved template."""
    from app.api.routes.extract import _parse_template
    from app.models.models import ColumnTemplate
    tpl = ColumnTemplate(name="i4", document_type=doc_type,
                         description=json.dumps(grid), columns_json="[]")
    return _parse_template(tpl)


def plan(labels):
    """[(run_id, label, variant, grid, note)] — every run this would make."""
    from template_shape import compute_shape
    out = []
    for label in labels:
        grid = json.loads((bs.TEMPLATES_DIR / label["template"])
                          .read_text(encoding="utf-8"))
        shape = compute_shape(grid, log=lambda _m: None)
        bands = shape.get("repeat_bands") or []
        if not bands:
            continue                      # nothing to perturb (the cheque)
        for variant in VARIANTS:
            g, note = perturb(grid, bands, variant)
            if g is None:
                continue
            out.append((f'{label["document_id"]}__{variant}', label, variant,
                        g, note))
    return out


def run_one(label, grid, cache, capture):
    """The real pipeline on one perturbed template. Returns (results, log)."""
    from tests.harness.runner import run_pipeline
    td = template_data_for(grid, label["document_type"])
    capture.clear()
    results, log = run_pipeline(label, td)
    return results, log, td


# ── measurement ──────────────────────────────────────────────────────────────

def _norm(s):
    return re.sub(r"[^a-z0-9]+", "", str(s or "").casefold())


def _tokens(s):
    return set(re.findall(r"[a-z0-9]+", str(s or "").casefold()))


def wording_difference(key, band_keys, headers_printed):
    """Is this off-schema key the same COLUMN under a different word?

    Two ways to be one, and both are 'the model answered the right column and
    called it something else':
      - it fuzzy-matches one of the band's own keys, or
      - it matches a heading the DOCUMENT prints, which is what the model was
        reading when it chose the word.
    Anything else names something the band has no column for at all — `Label`
    on a five-column band — and is a real mismatch.
    """
    k, kt = _norm(key), _tokens(key)
    for cand in list(band_keys) + list(headers_printed):
        c, ct = _norm(cand), _tokens(cand)
        if not c or not k:
            continue
        if c == k:
            return True
        if len(c) >= 4 and len(k) >= 4 and (c in k or k in c):
            return True
        if kt and ct and len(kt & ct) / len(kt | ct) >= 0.5:
            return True
    return False


def classify_row(cells, band_keys):
    """What kind of row is this, judged only from the answer."""
    on = [h for h in band_keys if str(cells.get(h, "") or "").strip()]
    off = [k for k in cells
           if k not in band_keys and k not in ("source", "page")
           and str(cells.get(k) or "").strip()]
    text = " ".join(str(v) for v in cells.values()).casefold()
    bits = []
    if not on and off:
        bits.append("every key off-schema")
    elif not on:
        bits.append("empty in the answer too")
    if re.search(r"\b(total|subtotal|sum|balance|net|gross)\b", text):
        bits.append("total/subtotal line")
    filled = [v for v in cells.values() if str(v or "").strip()]
    if len(filled) == 1:
        bits.append("single cell — label-only or value-only")
    return ", ".join(bits) or "ordinary data row"


def measure(label, variant, results, parsed_list, note):
    """One row of the report, per band."""
    from slot_extractor import table_headers
    rows = []
    for n, r in enumerate(results):
        ed = getattr(r, "extracted_data", None) or {}
        val = ed.get("validation") or {}
        flags = [f for f in (val.get("flagged_fields") or []) if isinstance(f, dict)]
        parsed = parsed_list[n] if n < len(parsed_list) else (
            parsed_list[-1] if parsed_list else {})
        resp_tables = (parsed or {}).get("tables") or {}
        printed = _printed_headings(ed)
        for t in (ed.get("slot_map") or {}).get("tables") or []:
            name = t["name"]
            keys = table_headers(t)
            raw = resp_tables.get(name)
            if not isinstance(raw, list) and len(resp_tables) == 1:
                raw = next(iter(resp_tables.values()))
            if not isinstance(raw, list):
                raw = []
            raw = [x for x in raw if isinstance(x, dict)]
            kept = ed.get(f"{name}_rows")
            if kept is None and name == "table":
                kept = ed.get("table_rows")
            kept = kept or []
            acct = len([f for f in flags
                        if str(f.get("ref", "")).startswith(f"{name}[")
                        and ("dropped" in str(f.get("ref"))
                             or "not bound" in str(f.get("ref")))])
            silent = max(0, len(raw) - len(kept) - acct)

            off_total, off_wording, off_mismatch = 0, 0, 0
            off_keys = Counter()
            for x in raw:
                c = x.get("cells") if isinstance(x.get("cells"), dict) else x
                for k in c:
                    if k in keys or k in ("source", "page"):
                        continue
                    if not str(c.get(k) or "").strip():
                        continue
                    off_total += 1
                    off_keys[k] += 1
                    if wording_difference(k, keys, printed):
                        off_wording += 1
                    else:
                        off_mismatch += 1

            dropped = []
            if silent:
                seen = Counter(str(k0.get("_source") or "") for k0 in kept)
                for x in raw:
                    s = str(x.get("source") or "")
                    if seen[s]:
                        seen[s] -= 1
                        continue
                    c = x.get("cells") if isinstance(x.get("cells"), dict) else x
                    c = {k: v for k, v in c.items() if k not in ("source", "page")}
                    dropped.append({"cells": c, "source": s,
                                    "kind": classify_row(c, keys)})
            rows.append({
                "document": label["document_id"], "variant": variant,
                "band": name, "band_keys": keys, "note": note,
                "returned": len(raw), "kept": len(kept), "accounted": acct,
                "silent": silent,
                "off_schema_cells": off_total,
                "off_schema_wording": off_wording,
                "off_schema_mismatch": off_mismatch,
                "off_schema_keys": dict(off_keys),
                "rows_with_off_schema_key": sum(
                    1 for x in raw
                    for c in [x.get("cells") if isinstance(x.get("cells"), dict) else x]
                    if any(k not in keys and k not in ("source", "page")
                           and str(c.get(k) or "").strip() for k in c)),
                "dropped_rows": dropped,
                "needs_review": bool(ed.get("needs_review")),
                "dropped_row_count": val.get("dropped_row_count"),
            })
    return rows


def _printed_headings(ed):
    """Whatever the DOCUMENT itself calls its columns, as far as the result
    records it — the band headings grounding read off the page."""
    out = set()
    for k, v in (ed or {}).items():
        if k.endswith("_rows") and isinstance(v, list):
            for r in v:
                if isinstance(r, dict):
                    out.update(x for x in r if not str(x).startswith("_"))
    return out


# ── entry point ──────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", choices=["record", "replay", "live"],
                    default="replay")
    ap.add_argument("--docs", default="", help="comma-separated document ids")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the plan and the perturbed band keys; no calls")
    args = ap.parse_args()

    bs.bootstrap()
    bs.chdir_backend()
    import slot_extractor
    from template_shape import compute_shape
    from tests.harness.llm_cache import LLMCache
    from tests.harness.runner import load_labels

    only = {d.strip() for d in args.docs.split(",") if d.strip()} or None
    labels = load_labels(only)
    todo = plan(labels)

    if args.dry_run:
        for run_id, label, variant, grid, note in todo:
            sh = compute_shape(grid, log=lambda _m: None)
            from slot_extractor import table_headers
            print(f"{run_id}")
            print(f"   {note}")
            for b in sh.get("repeat_bands") or []:
                print(f"   band {b['name']!r}: {table_headers(b)}")
            gate = sh.get("coverage", {})
            if gate.get("warnings") or gate.get("blocking"):
                print(f"   gate: warn={len(gate.get('warnings') or [])} "
                      f"block={len(gate.get('blocking') or [])}")
        print(f"\n{len(todo)} runs planned")
        return

    captured = []
    orig = slot_extractor._llm_json

    def spy(*a, **k):
        parsed, resp = orig(*a, **k)
        captured.append(parsed)
        return parsed, resp

    slot_extractor._llm_json = spy

    cache = LLMCache(mode=args.mode)
    cache.install()
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    report = []
    try:
        for run_id, label, variant, grid, note in todo:
            cache.context = f"i4:{run_id}"
            print(f"[I4] {run_id} — {note}", flush=True)
            try:
                results, log, td = run_one(label, grid, cache, captured)
            except Exception as e:
                print(f"[I4]   FAILED: {type(e).__name__}: {str(e)[:160]}")
                continue
            rows = measure(label, variant, results, list(captured), note)
            report.extend(rows)
            for row in rows:
                print(f"[I4]   band={row['band']!r} returned={row['returned']} "
                      f"kept={row['kept']} accounted={row['accounted']} "
                      f"SILENT={row['silent']} off_schema_cells="
                      f"{row['off_schema_cells']} "
                      f"(wording={row['off_schema_wording']} "
                      f"mismatch={row['off_schema_mismatch']})", flush=True)
            if args.mode in ("record", "live"):
                (RAW_DIR / f"{run_id}.json").write_text(json.dumps({
                    "run": run_id, "document": label["document_id"],
                    "pdf": label["pdf"], "variant": variant, "note": note,
                    "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "commit": _commit(), "mode": args.mode,
                    "grid": grid,
                    "calls": [{"method": m, "key": k, "source": s}
                              for m, k, s in cache.calls[-4:]],
                    "answers": captured,
                    "measurement": rows,
                }, indent=1, ensure_ascii=False), encoding="utf-8")
    finally:
        cache.uninstall()
        slot_extractor._llm_json = orig

    summarise(report)
    out = bs.TESTS_DIR / "reports" / "i4.json"
    out.write_text(json.dumps({
        "commit": _commit(), "mode": args.mode,
        "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "runs": report}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\nreport: {out}")


def summarise(report):
    by_variant = {}
    for r in report:
        v = by_variant.setdefault(r["variant"], Counter())
        for k in ("returned", "kept", "accounted", "silent",
                  "off_schema_cells", "off_schema_wording",
                  "off_schema_mismatch", "rows_with_off_schema_key"):
            v[k] += r[k]
        v["bands"] += 1
    print("\n" + "=" * 78)
    print(f"{'variant':10s} {'bands':>5s} {'rows':>5s} {'kept':>5s} "
          f"{'acct':>5s} {'SILENT':>7s} {'offcell':>8s} {'wording':>8s} "
          f"{'mismat':>7s} {'offrows':>8s}")
    for v in VARIANTS:
        c = by_variant.get(v)
        if not c:
            continue
        print(f"{v:10s} {c['bands']:5d} {c['returned']:5d} {c['kept']:5d} "
              f"{c['accounted']:5d} {c['silent']:7d} {c['off_schema_cells']:8d} "
              f"{c['off_schema_wording']:8d} {c['off_schema_mismatch']:7d} "
              f"{c['rows_with_off_schema_key']:8d}")
    tot = Counter()
    for c in by_variant.values():
        tot.update(c)
    print(f"{'TOTAL':10s} {tot['bands']:5d} {tot['returned']:5d} "
          f"{tot['kept']:5d} {tot['accounted']:5d} {tot['silent']:7d} "
          f"{tot['off_schema_cells']:8d} {tot['off_schema_wording']:8d} "
          f"{tot['off_schema_mismatch']:7d} {tot['rows_with_off_schema_key']:8d}")

    drops = [(r["document"], r["variant"], r["band"], d)
             for r in report for d in r["dropped_rows"]]
    print(f"\nrows dropped silently: {len(drops)}")
    for doc, var, band, d in drops:
        print(f"  {doc} [{var}] {band}: {d['kind']}")
        print(f"      {d['cells']}")

    print("\noff-schema keys, by key:")
    keys = Counter()
    for r in report:
        for k, n in (r["off_schema_keys"] or {}).items():
            keys[k] += n
    for k, n in keys.most_common(30):
        print(f"  {n:4d}  {k!r}")


if __name__ == "__main__":
    main()
