"""
Accuracy runner: drive the real extraction pipeline over every labeled
document, score against gold, and report.

    python -m tests.harness.runner --mode replay            # offline, cached LLM
    python -m tests.harness.runner --mode record            # live, records cache
    python -m tests.harness.runner --mode record --repeat 3 # stability check
    python -m tests.harness.runner --docs CHQ-001847,IS-2024-Q4

Outputs:
    tests/reports/latest.json      machine-readable full results (committed baseline)
    tests/reports/latest.md        human-readable summary
    tests/reports/history/<ts>.json  timestamped copy (gitignored)

Every run diffs against the previous latest.json and lists each field whose
outcome changed; correct->anything transitions are flagged REGRESSION.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import subprocess
import time
from pathlib import Path

from tests.harness import bootstrap as bs
from tests.harness.adapter import adapt
from tests.harness.llm_cache import LLMCache
from tests.harness.scoring import normalize_string, score_document, summarize

# ── pipeline plumbing ────────────────────────────────────────────────────────


def _schema_path() -> str:
    from app.core.storage import get_storage
    p = get_storage().get_schema_path("demo_001")
    if p is None:
        cand = bs.ENGINE_DIR / "demo_accounting.yaml"
        p = cand if cand.exists() else ""
    return str(p)


def pdf_text(pdf_path) -> str:
    """Source-document text, read INDEPENDENTLY of the pipeline (same way the
    gold labels were produced). Used only to tell an invented value from a
    misplaced one."""
    try:
        import pdfplumber
        with pdfplumber.open(str(pdf_path)) as pdf:
            return "\n".join((pg.extract_text() or "") for pg in pdf.pages)
    except Exception:
        return ""


def load_labels(only=None) -> list:
    labels = []
    for f in sorted(bs.LABELS_DIR.glob("*.json")):
        lab = json.loads(f.read_text(encoding="utf-8"))
        if only and lab["document_id"] not in only:
            continue
        labels.append(lab)
    return labels


def build_template_data(label: dict, mode: str, orchestrator=None):
    """Template grid -> template_data, mirroring the production save+load flow.

    The shape is computed once at save (2a) and read back at load, so the
    harness measures the stored-shape path rather than a per-run inference the
    product would never do.
    """
    import json as _json
    from app.api.routes.extract import _parse_template
    from app.api.routes.templates import _compute_and_store_shape
    from app.models.models import ColumnTemplate

    grid = _json.loads((bs.TEMPLATES_DIR / label["template"]).read_text(encoding="utf-8"))
    tpl = ColumnTemplate(name=Path(label["template"]).stem,
                         document_type=label["document_type"],
                         description=_json.dumps(grid), columns_json="[]")
    _compute_and_store_shape(tpl)
    td = _parse_template(tpl)
    shape = (td or {}).get("shape") or {}
    return td, grid, f"needs {shape.get('required_columns', 0)} columns"


NO_TEMPLATE = "__none__"


def run_pipeline(label: dict, template_data: dict):
    """Run the real pipeline for one document; capture its stdout log."""
    from app.api.routes.extract import (_extract_image_with_template,
                                        _extract_with_template, _is_image_file)
    from orchestrator import Orchestrator

    pdf_path = bs.PDF_DIR / label["pdf"]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        orchestrator = Orchestrator(client_schema_path=_schema_path())
        if _is_image_file(pdf_path):
            results = _extract_image_with_template(orchestrator, pdf_path,
                                                   template_data)
        else:
            results = _extract_with_template(orchestrator, pdf_path,
                                             template_data)
    return results, buf.getvalue()


def _log_findings(log: str) -> dict:
    route = next((ln.strip() for ln in log.splitlines() if "[ROUTE]" in ln), "")
    return {
        "route": route,
        "engine_fallback_to_legacy": "falling back to legacy" in log,
        "fatal": "[EXTRACT] FATAL" in log,
        "replay_cache_miss": "cache miss in replay mode" in log,
    }


# ── stability (--repeat) ─────────────────────────────────────────────────────


def _flat_values(adapted: dict) -> dict:
    out = {}
    for name, v in adapted.get("fields", {}).items():
        out[f"field:{name}"] = normalize_string(v) if v is not None else None
    for tname, rows in adapted.get("tables", {}).items():
        out[f"table:{tname}:row_count"] = len(rows)
        for i, row in enumerate(rows):
            for col, v in row.items():
                out[f"table:{tname}[{i}].{col}"] = (
                    normalize_string(v) if v is not None else None)
    return out


def find_unstable(adapted_runs: list) -> list:
    """Keys whose value differs between any two runs. An unstable field cannot
    be used to judge whether a change helped."""
    if len(adapted_runs) < 2:
        return []
    flats = [_flat_values(a) for a in adapted_runs]
    keys = set().union(*[set(f) for f in flats])
    unstable = []
    for k in sorted(keys):
        vals = {json.dumps(f.get(k), ensure_ascii=False) for f in flats}
        if len(vals) > 1:
            unstable.append({"key": k, "values": sorted(vals)})
    return unstable


# ── diffing runs ─────────────────────────────────────────────────────────────


def flatten_outcomes(report: dict) -> dict:
    """{(doc, kind, name): outcome} for every scored field and table cell."""
    out = {}
    for doc_id, d in (report.get("documents") or {}).items():
        score = d.get("score") or {}
        for name, r in (score.get("fields") or {}).items():
            out[f"{doc_id} :: {name}"] = r["outcome"]
        for tname, t in (score.get("tables") or {}).items():
            for c in t.get("cells", []):
                row = c.get("row")
                loc = f"row {row}" if row is not None else f"pred_row {c.get('pred_row')}"
                out[f"{doc_id} :: {tname}[{loc}].{c['column']}"] = c["outcome"]
            out[f"{doc_id} :: {tname} :: row_count_mismatch"] = str(
                t.get("row_count_mismatch"))
    return out


def diff_runs(prev: dict, cur: dict) -> list:
    p, c = flatten_outcomes(prev), flatten_outcomes(cur)
    changes = []
    for key in sorted(set(p) | set(c)):
        a, b = p.get(key), c.get(key)
        if a == b:
            continue
        # 'correct' -> anything else is a regression, INCLUDING the field
        # vanishing from the report (b is None): a value that used to be
        # measured correct and is now not measured at all is the quietest
        # possible way to lose coverage, so it must be loud.
        regression = (a == "correct" and b != "correct")
        changes.append({"key": key, "before": a, "after": b,
                        "regression": regression})
    return changes


# ── reporting ────────────────────────────────────────────────────────────────


def _pct(x):
    return "—" if x is None else f"{100 * x:.1f}%"


def write_markdown(report: dict, path: Path):
    s = report["summary"]
    lines = []
    add = lines.append
    add(f"# Accuracy report — {report['run_id']}")
    add("")
    add(f"- git: `{report['git_commit']}`  mode: **{report['config']['mode']}**"
        f"  repeat: {report['config']['repeat']}")
    add(f"- config: {json.dumps(report['config']['env'])}")
    add("")
    o = s["overall"]
    add(f"## Overall")
    add("")
    add(f"| metric | value |")
    add(f"|---|---|")
    add(f"| **accuracy (correct / gold-valued)** | **{_pct(o['accuracy'])}** |")
    add(f"| **hallucination rate (hallucinated / extracted)** | **{_pct(o['hallucination_rate'])}** |")
    add(f"| **└ invention rate (value found NOWHERE in the PDF)** | **{_pct(o['invention_rate'])}** |")
    add(f"| └ misplacement (real content, slot gold leaves empty) | {_pct((o['hallucinated'] - o['hallucinated_ungrounded']) / max(1, o['gold_valued'] + o['hallucinated']))} |")
    add(f"| hallucinated values | {o['hallucinated']} (invented {o['hallucinated_ungrounded']}, misplaced {o['hallucinated'] - o['hallucinated_ungrounded']}) |")
    add(f"| near misses | {o['counts'].get('near', 0)} |")
    add(f"| outcome counts | {json.dumps(o['counts'])} |")
    add("")
    add("## By document type")
    add("")
    add("| document type | accuracy | halluc. rate | invented | correct | near | wrong | missed | halluc. |")
    add("|---|---|---|---|---|---|---|---|---|")
    for k, v in s["by_document_type"].items():
        c = v["counts"]
        add(f"| {k} | {_pct(v['accuracy'])} | {_pct(v['hallucination_rate'])} | "
            f"{v['hallucinated_ungrounded']} | "
            f"{c.get('correct', 0)} | {c.get('near', 0)} | {c.get('wrong', 0)} | "
            f"{c.get('missed', 0)} | {c.get('hallucinated', 0)} |")
    add("")
    add("## By field type")
    add("")
    add("| field type | accuracy | halluc. rate | invented | correct | near | wrong | missed | halluc. |")
    add("|---|---|---|---|---|---|---|---|---|")
    for k, v in s["by_field_type"].items():
        c = v["counts"]
        add(f"| {k} | {_pct(v['accuracy'])} | {_pct(v['hallucination_rate'])} | "
            f"{v['hallucinated_ungrounded']} | "
            f"{c.get('correct', 0)} | {c.get('near', 0)} | {c.get('wrong', 0)} | "
            f"{c.get('missed', 0)} | {c.get('hallucinated', 0)} |")
    add("")
    add("## Per document")
    add("")
    add("| document | type | accuracy | halluc. | invented | route | notes |")
    add("|---|---|---|---|---|---|---|")
    for doc_id, d in report["documents"].items():
        sc = d.get("score") or {}
        cnt = sc.get("counts", {})
        notes = []
        if d["log"].get("engine_fallback_to_legacy"):
            notes.append("FELL BACK TO LEGACY ENGINE")
        if d["log"].get("fatal"):
            notes.append("FATAL")
        if d["log"].get("replay_cache_miss"):
            notes.append("cache miss")
        if d.get("unstable"):
            notes.append(f"{len(d['unstable'])} unstable")
        route = d["log"].get("route", "").replace("[ROUTE]", "").strip()
        add(f"| {doc_id} | {d['document_type']} | {_pct(sc.get('accuracy'))} | "
            f"{cnt.get('hallucinated', 0)} | {sc.get('hallucinated_ungrounded', 0)} | "
            f"{route[:60]} | {'; '.join(notes)} |")
    add("")
    add("## Mismatches (everything not correct)")
    add("")
    add("| document | field | outcome | expected | actual |")
    add("|---|---|---|---|---|")

    def esc(v):
        return str(v).replace("|", "\\|").replace("\n", " ")[:60]

    for doc_id, d in report["documents"].items():
        sc = d.get("score") or {}
        for name, r in (sc.get("fields") or {}).items():
            if r["outcome"] in ("correct", "empty_ok"):
                continue
            oc = r["outcome"]
            if oc == "hallucinated":
                oc = "INVENTED" if not r.get("grounded") else "hallucinated (misplaced)"
            add(f"| {doc_id} | {esc(name)} | {oc} | "
                f"{esc(r['expected'])} | {esc(r['actual'])} |")
        for tname, t in (sc.get("tables") or {}).items():
            for c in t.get("cells", []):
                if c["outcome"] in ("correct", "empty_ok"):
                    continue
                row = c.get("row")
                loc = f"[row {row}]" if row is not None else f"[pred_row {c.get('pred_row')}]"
                oc = c["outcome"]
                if oc == "hallucinated":
                    oc = "INVENTED" if not c.get("grounded") else "hallucinated (misplaced)"
                add(f"| {doc_id} | {esc(tname + loc + '.' + c['column'])} | "
                    f"{oc} | {esc(c['expected'])} | {esc(c['actual'])} |")
    add("")
    if report.get("unstable_total"):
        add("## Unstable fields (varied across --repeat runs)")
        add("")
        for doc_id, d in report["documents"].items():
            for u in d.get("unstable", []):
                add(f"- {doc_id} :: {u['key']}: {u['values']}")
        add("")
    if report.get("diff"):
        add("## Changes vs previous run")
        add("")
        for ch in report["diff"]:
            flag = " **REGRESSION**" if ch["regression"] else ""
            add(f"- {ch['key']}: {ch['before']} -> {ch['after']}{flag}")
        add("")
    path.write_text("\n".join(lines), encoding="utf-8")


# ── main ─────────────────────────────────────────────────────────────────────


def run(mode: str = "replay", only=None, repeat: int = 1,
        report_dir: Path = None, do_diff: bool = True,
        no_template: bool = False) -> dict:
    bs.bootstrap()
    report_dir = report_dir or bs.REPORTS_DIR
    bs.chdir_backend()  # pipeline writes relative paths as production does
    labels = load_labels(only)
    if not labels:
        raise SystemExit("no gold labels matched")

    try:
        git_commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=bs.REPO_DIR,
            capture_output=True, text=True).stdout.strip()
    except OSError:
        git_commit = "unknown"

    cache = LLMCache(mode=mode)
    cache.install()
    doc_reports = {}
    doc_scores = []
    try:
        for label in labels:
            doc_id = label["document_id"]
            cache.context = doc_id
            print(f"[RUN] {doc_id} ({label['document_type']}) …", flush=True)

            if no_template:
                # Phase 3 — extract with NO template and score against the same
                # gold. The engine must infer the document's structure itself.
                td, grid, ttype = None, {"cells": {}}, NO_TEMPLATE
            else:
                td, grid, ttype = build_template_data(label, mode)
            adapted_runs = []
            log = ""
            results = []
            n_runs = repeat if mode != "replay" else 1
            if repeat > 1 and mode == "replay":
                print("[RUN]   --repeat has no effect in replay mode "
                      "(cache is deterministic); running once", flush=True)
            for i in range(n_runs):
                if i > 0:
                    cache.mode = "live"  # stability runs bypass recording
                results_i, log_i = run_pipeline(label, td)
                grid_i = grid
                if no_template and results_i:
                    ed0 = getattr(results_i[0], "extracted_data", None) or {}
                    grid_i = ed0.get("inferred_grid") or grid
                adapted_runs.append(adapt(results_i, label, grid_i))
                if i == 0:
                    results, log = results_i, log_i
            cache.mode = mode

            adapted = adapted_runs[0]
            score = score_document(label, adapted,
                                   doc_text=pdf_text(bs.PDF_DIR / label["pdf"]))
            doc_scores.append(score)
            unstable = find_unstable(adapted_runs)
            inferred = None
            if no_template and results:
                inferred = (getattr(results[0], "extracted_data", None) or {}).get(
                    "inferred_template")
            doc_reports[doc_id] = {
                "document_type": label["document_type"],
                "inferred_template": inferred,
                "template": label["template"],
                "template_type": ttype,
                "success": all(getattr(r, "success", False) for r in results) if results else False,
                "errors": [getattr(r, "error_message", "") or "" for r in results
                           if not getattr(r, "success", False)],
                "log": _log_findings(log),
                "adapter_notes": adapted.get("notes", []),
                "adapted": {"fields": adapted["fields"],
                            "tables": adapted["tables"]},
                "score": score,
                "unstable": unstable,
            }
            acc = score.get("accuracy")
            print(f"[RUN]   accuracy={_pct(acc)} counts={score['counts']}",
                  flush=True)
    finally:
        cache.uninstall()

    report = {
        "run_id": time.strftime("%Y-%m-%d %H:%M:%S"),
        "git_commit": git_commit,
        "config": {
            "mode": mode,
            "repeat": repeat,
            "no_template": no_template,
            "env": bs.PRODUCTION_PARITY_ENV,
        },
        "cache_stats": cache.stats,
        "documents": doc_reports,
        "summary": summarize(doc_scores),
        "unstable_total": sum(len(d["unstable"]) for d in doc_reports.values()),
    }

    stem = "latest-notemplate" if no_template else "latest"
    latest = report_dir / f"{stem}.json"
    if do_diff and latest.exists():
        try:
            prev = json.loads(latest.read_text(encoding="utf-8"))
            report["diff"] = diff_runs(prev, report)
            report["diff_against"] = prev.get("run_id")
        except (json.JSONDecodeError, OSError) as e:
            report["diff"] = []
            report["diff_error"] = str(e)
    else:
        report["diff"] = []

    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "history").mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    (report_dir / "history" / f"{stamp}-{stem}.json").write_text(
        json.dumps(report, indent=1, ensure_ascii=False, default=str),
        encoding="utf-8")
    latest.write_text(json.dumps(report, indent=1, ensure_ascii=False,
                                 default=str), encoding="utf-8")
    write_markdown(report, report_dir / f"{stem}.md")

    # console summary
    o = report["summary"]["overall"]
    print("\n=== SUMMARY ===")
    print(f"accuracy            : {_pct(o['accuracy'])}")
    print(f"hallucination rate  : {_pct(o['hallucination_rate'])} "
          f"({o['hallucinated']} values in slots gold leaves empty)")
    print(f"  of which INVENTED : {_pct(o['invention_rate'])} "
          f"({o['hallucinated_ungrounded']} values found nowhere in the PDF)")
    print(f"  of which misplaced: {o['hallucinated'] - o['hallucinated_ungrounded']} "
          f"(real document content, wrong slot)")
    print(f"outcome counts      : {o['counts']}")
    print(f"cache               : {report['cache_stats']}")
    if report["unstable_total"]:
        print(f"UNSTABLE fields     : {report['unstable_total']}")
    regressions = [c for c in report["diff"] if c["regression"]]
    if regressions:
        print(f"\n*** {len(regressions)} REGRESSION(S) vs previous run ***")
        for c in regressions:
            print(f"  {c['key']}: {c['before']} -> {c['after']}")
    elif report["diff"]:
        print(f"{len(report['diff'])} field state change(s) vs previous run "
              f"(no correct->x regressions)")
    print(f"\nreports: {report_dir / 'latest.md'}")
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", choices=["replay", "record", "live"],
                    default="replay")
    ap.add_argument("--docs", default=None,
                    help="comma-separated document ids (default: all labeled)")
    ap.add_argument("--repeat", type=int, default=1,
                    help="run each document N times (record/live only) and "
                         "flag fields whose value varies as unstable")
    ap.add_argument("--no-diff", action="store_true")
    ap.add_argument("--no-template", action="store_true",
                    help="extract with NO template — the engine infers the "
                         "shape (Phase 3) — and score against the same gold")
    args = ap.parse_args()
    only = set(args.docs.split(",")) if args.docs else None
    run(mode=args.mode, only=only, repeat=args.repeat,
        do_diff=not args.no_diff, no_template=args.no_template)


if __name__ == "__main__":
    main()
