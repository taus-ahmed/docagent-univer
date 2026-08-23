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
from tests.harness.adapter import adapt, set_widenings
from tests.harness.llm_cache import LLMCache
from tests.harness.scoring import (normalize_string, score_content,
                                   score_document, score_structure,
                                   summarize, summarize_content,
                                   summarize_structure)

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


def build_template_data(label: dict, mode: str, orchestrator=None,
                        template_override=None):
    """Template grid -> template_data, mirroring the production load flow.

    Shape is computed fresh from the grid on every run, exactly as production
    does — nothing is stored, so there is no stored/actual divergence to
    measure around.
    """
    import json as _json
    from app.api.routes.extract import _parse_template
    from app.models.models import ColumnTemplate

    # A template override runs a labeled document through a DIFFERENT template
    # shape, scored against the same gold. Gold labels are keyed by field label
    # and table name, not by cell address, so the same answers are expected
    # however the sheet is arranged — which is exactly what makes a transposed
    # template testable without inventing a second set of labels.
    name = template_override or label["template"]
    grid = _json.loads((bs.TEMPLATES_DIR / name).read_text(encoding="utf-8"))
    tpl = ColumnTemplate(name=Path(name).stem,
                         document_type=label["document_type"],
                         description=_json.dumps(grid), columns_json="[]")
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


def build_export(results, grid, no_template):
    """Build the workbook exactly as the download endpoint does, then read it
    back. Returns (worksheet_or_None, shape_used)."""
    import openpyxl
    from app.api.routes.extract import (_analyse_template_regions, _write_excel,
                                        _write_inferred_sheets, _write_flat_table)
    from app.models.models import DocumentResult

    docs, shape = [], None
    for r in results:
        ed = getattr(r, "extracted_data", None) or {}
        docs.append(DocumentResult(
            filename=getattr(r, "filename", "x.pdf"),
            document_type=getattr(r, "document_type", "") or "x",
            extraction_json=json.dumps(ed, default=str)))
    if not docs:
        return None, None

    wb = openpyxl.Workbook()
    ws = wb.active
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            if no_template:
                use_grid = (getattr(results[0], "extracted_data", None)
                            or {}).get("inferred_grid") or {}
                if not _write_inferred_sheets(wb, ws, docs, openpyxl):
                    _write_flat_table(ws, docs, openpyxl)
                ws = wb.worksheets[0]
            else:
                use_grid = grid
                _write_excel(ws, docs, grid, _analyse_template_regions(grid),
                             openpyxl)
        from app.api.routes.extract import _compute_shape_for_grid
        with contextlib.redirect_stdout(io.StringIO()):
            shape = _compute_shape_for_grid(use_grid) if use_grid else None
    except Exception as e:
        print(f"[EXPORT] could not build workbook: {e}", flush=True)
        return None, None
    return ws, shape


def calibrate(label, adapted, score, results):
    """Join each scored cell back to the confidence the engine gave it.

    Confidence is only worth surfacing if it predicts correctness, so this
    measures exactly that: of the cells the engine called high, what fraction
    are actually right.
    """
    from tests.harness.adapter import _match_name
    ed = (getattr(results[0], "extracted_data", None) or {}) if results else {}
    conf_map = (ed.get("validation") or {}).get("confidence_map") or {}
    slots = (ed.get("slot_map") or {}).get("fields") or []
    gold_names = list((label.get("fields") or {}).keys())

    by_gold = {}
    for slot in slots:
        c = conf_map.get(slot.get("ref"))
        if not c:
            continue
        g = _match_name(slot.get("row_label"), gold_names) or slot.get("row_label")
        by_gold[g] = c

    out = {}

    def add(level, outcome):
        b = out.setdefault(level, {"n": 0, "correct": 0, "wrong": 0,
                                   "missed": 0, "near": 0, "hallucinated": 0})
        b["n"] += 1
        if outcome in b:
            b[outcome] += 1

    for name, r in (score.get("fields") or {}).items():
        if r["outcome"] == "empty_ok":
            continue
        lvl = by_gold.get(name)
        if lvl:
            add(lvl, r["outcome"])

    for tname, t in (score.get("tables") or {}).items():
        rows = (adapted.get("tables") or {}).get(tname) or []
        for cell in t.get("cells", []):
            if cell["outcome"] == "empty_ok":
                continue
            pi = cell.get("pred_row")
            if pi is None or pi >= len(rows):
                continue
            lvl = rows[pi].get("_confidence")
            if lvl:
                add(lvl, cell["outcome"])
    return out


def merge_calibration(parts):
    out = {}
    for p in parts:
        for lvl, b in (p or {}).items():
            t = out.setdefault(lvl, {"n": 0, "correct": 0, "wrong": 0,
                                     "missed": 0, "near": 0, "hallucinated": 0})
            for k, v in b.items():
                t[k] = t.get(k, 0) + v
    return out


def _log_findings(log: str) -> dict:
    route = next((ln.strip() for ln in log.splitlines() if "[ROUTE]" in ln), "")
    return {
        "route": route,
        "engine_fallback_to_legacy": "falling back to legacy" in log,
        "fatal": "[EXTRACT] FATAL" in log,
        "replay_cache_miss": "cache miss in replay mode" in log,
    }


# ── stability (--repeat) ─────────────────────────────────────────────────────


def _stable_value(v):
    """A value as the user will actually receive it in the spreadsheet.

    Uses the WRITER's own coercion (`coerce_cell_value`), so "stable" means
    "two runs put the same thing in the cell" — which is the only sense of
    stability a user experiences. Money and numbers become numbers, so
    "$1,365,503" and "1,365,503" are the same value; genuine text differences
    ("1.5%" vs "1.5% monthly interest") still differ, because neither parses.

    Comparing the raw strings instead reported 9 BS-2024-Q1 totals as unstable
    when every run extracted the identical number and the exported workbook was
    byte-identical — measuring the model's formatting, not its extraction.
    """
    if v is None:
        return None
    from app.api.routes.extract import coerce_cell_value
    out = coerce_cell_value(v)
    return normalize_string(out) if isinstance(out, str) else out


def _flat_values(adapted: dict) -> dict:
    out = {}
    for name, v in adapted.get("fields", {}).items():
        out[f"field:{name}"] = _stable_value(v)
    for tname, rows in adapted.get("tables", {}).items():
        out[f"table:{tname}:row_count"] = len(rows)
        for i, row in enumerate(rows):
            for col, v in row.items():
                out[f"table:{tname}[{i}].{col}"] = _stable_value(v)
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
    s_raw = report.get("summary_raw", {}).get("overall", {"accuracy": None})
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
    add(f"| **accuracy RAW (all adapter widenings off)** | **{_pct(s_raw['accuracy'])}** |")
    _sc = report.get("summary_content") or {}
    _st = report.get("summary_structure") or {}
    if _sc.get("gold_valued"):
        add(f"| **accuracy CONTENT (container-blind)** | **{_pct(_sc['accuracy'])}** |")
    if _st.get("gold_tables"):
        add(f"| **structure FIDELITY (gold tables returned as tables)** | "
            f"**{_pct(_st['fidelity'])}** "
            f"({_st['tables_present']}/{_st['gold_tables']}; "
            f"{_st['tables_exact_rows']} with exact row count) |")
    add(f"| **hallucination rate (hallucinated / extracted)** | **{_pct(o['hallucination_rate'])}** |")
    add(f"| **├ INVENTED — value found NOWHERE in the PDF** | "
        f"**{o.get('invented', 0)}** ({_pct(o['invention_rate'])}) |")
    add(f"| ├ misfiled — real content in a slot gold says is EMPTY | "
        f"{o.get('misfiled', 0)} |")
    add(f"| └ out-of-schema — real content, name gold has no field for | "
        f"{o.get('out_of_schema', 0)} *(not a defect)* |")
    add(f"| **DEFECT RATE (invented + misfiled / extracted)** | "
        f"**{_pct(o.get('defect_rate'))}** |")
    add(f"| hallucinated values | {o['hallucinated']} |")
    add(f"| near misses | {o['counts'].get('near', 0)} |")
    add(f"| **renamed (right value, different field name)** | "
        f"**{o.get('renamed', 0)}** ({_pct(o.get('rename_rate'))}) |")
    add(f"| outcome counts | {json.dumps(o['counts'])} |")
    add("")
    add("## By document type")
    add("")
    add("| document type | accuracy | halluc. rate | invented | correct | near | renamed | wrong | missed | halluc. |")
    add("|---|---|---|---|---|---|---|---|---|---|")
    for k, v in s["by_document_type"].items():
        c = v["counts"]
        add(f"| {k} | {_pct(v['accuracy'])} | {_pct(v['hallucination_rate'])} | "
            f"{v['hallucinated_ungrounded']} | "
            f"{c.get('correct', 0)} | {c.get('near', 0)} | {c.get('renamed', 0)} | "
            f"{c.get('wrong', 0)} | "
            f"{c.get('missed', 0)} | {c.get('hallucinated', 0)} |")
    add("")
    add("## By field type")
    add("")
    add("| field type | accuracy | halluc. rate | invented | correct | near | renamed | wrong | missed | halluc. |")
    add("|---|---|---|---|---|---|---|---|---|---|")
    for k, v in s["by_field_type"].items():
        c = v["counts"]
        add(f"| {k} | {_pct(v['accuracy'])} | {_pct(v['hallucination_rate'])} | "
            f"{v['hallucinated_ungrounded']} | "
            f"{c.get('correct', 0)} | {c.get('near', 0)} | {c.get('renamed', 0)} | "
            f"{c.get('wrong', 0)} | "
            f"{c.get('missed', 0)} | {c.get('hallucinated', 0)} |")
    add("")
    add("## Per document")
    add("")
    add("| document | type | accuracy | raw | halluc. | invented | route | notes |")
    add("|---|---|---|---|---|---|---|---|")
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
            f"{_pct((d.get('score_raw') or {}).get('accuracy'))} | "
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
        no_template: bool = False, template: str = None) -> dict:
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

    # W2 (identify a table by its rows) is a no-template-only rule: see the
    # note on WIDENINGS. Templated extraction runs without it.
    set_widenings(W2_table_by_content=bool(no_template))

    cache = LLMCache(mode=mode)
    cache.install()
    doc_reports = {}
    doc_scores = []
    doc_scores_raw = []
    doc_scores_export = []
    doc_scores_content = []
    doc_scores_structure = []
    calib = []
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
                td, grid, ttype = build_template_data(label, mode,
                                                      template_override=template)
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

            text = pdf_text(bs.PDF_DIR / label["pdf"])
            adapted = adapted_runs[0]
            score = score_document(label, adapted, doc_text=text)

            # EXPORT — score the .xlsx that a user actually receives, read
            # back from the file. Extraction accuracy and export accuracy
            # diverging means the WRITER is wrong; the export bug of
            # 2026-08-18 produced 34 correct values and 34 empty cells and
            # nothing caught it, because only the in-memory result was scored.
            export_score = None
            try:
                from tests.harness.sheet_reader import sheet_as_result
                ws_out, out_shape = build_export(results, grid_i if no_template
                                                 else grid, no_template)
                if ws_out is not None and out_shape:
                    exported = adapt([sheet_as_result(ws_out, out_shape)],
                                     label, grid_i if no_template else grid)
                    export_score = score_document(label, exported, doc_text=text)
            except Exception as e:
                print(f"[EXPORT] scoring failed: {e}", flush=True)

            # RAW — the same extraction scored with every adapter widening off.
            # Reported alongside the adapted number in every run, so a number
            # that depends on mapping leniency is visible as such.
            from tests.harness.adapter import WIDENINGS
            prev = set_widenings(**{k: False for k in WIDENINGS})
            try:
                raw_adapted = adapt(results, label, grid_i if no_template else grid)
                raw_score = score_document(label, raw_adapted, doc_text=text)
            finally:
                set_widenings(**prev)
            # CONTENT and STRUCTURE, asked separately. See the block comment in
            # scoring.py: the headline compares like-for-like containers, which
            # is right with a template and conflates two questions without one.
            content = score_content(label, adapted)
            structure = score_structure(label, adapted)
            doc_scores.append(score)
            doc_scores_raw.append(raw_score)
            doc_scores_content.append(content)
            doc_scores_structure.append(structure)
            calib.append(calibrate(label, adapted, score, results))
            if export_score:
                doc_scores_export.append(export_score)
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
                "score_raw": raw_score,
                "score_export": export_score,
                "score_content": content,
                "score_structure": structure,
                "unstable": unstable,
            }
            ex = _pct((export_score or {}).get("accuracy"))
            flag = ""
            if export_score and score.get("accuracy") is not None:
                if abs((export_score.get("accuracy") or 0)
                       - (score.get("accuracy") or 0)) > 0.001:
                    flag = "   <-- WRITER: export != extraction"
            print(f"[RUN]   extraction={_pct(score.get('accuracy'))}  "
                  f"export={ex}  raw={_pct(raw_score.get('accuracy'))}{flag}",
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
        "summary_raw": summarize(doc_scores_raw),
        "summary_export": summarize(doc_scores_export) if doc_scores_export else None,
        "summary_content": summarize_content(doc_scores_content),
        "summary_structure": summarize_structure(doc_scores_structure),
        "calibration": merge_calibration(calib),
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
    ro = report.get("summary_raw", {}).get("overall", {}) or {}
    print("\n=== SUMMARY ===")
    eo = (report.get("summary_export") or {}).get("overall") or {}
    print(f"accuracy  EXTRACTION: {_pct(o['accuracy'])}")
    if eo:
        div = ("   <-- WRITER BUG: the file does not match the extraction"
               if abs((eo.get('accuracy') or 0) - (o.get('accuracy') or 0)) > 0.001
               else "   (matches extraction)")
        print(f"accuracy  EXPORT    : {_pct(eo.get('accuracy'))}{div}")
    print(f"accuracy  RAW       : {_pct(ro.get('accuracy'))}"
          f"   (all adapter widenings off)")
    # CONTENT and STRUCTURE are asked separately — see the block comment in
    # scoring.py. Reported alongside the headline, never instead of it.
    sc_ = report.get("summary_content") or {}
    st_ = report.get("summary_structure") or {}
    if sc_.get("gold_valued"):
        print(f"accuracy  CONTENT   : {_pct(sc_['accuracy'])}"
              f"   (container-blind: did we get the fact, wherever it landed)")
    if st_.get("gold_tables"):
        print(f"structure FIDELITY  : {_pct(st_['fidelity'])}"
              f"   ({st_['tables_present']}/{st_['gold_tables']} gold tables came "
              f"back as tables, {st_['tables_exact_rows']} with the right row count)")
    print(f"hallucination rate  : {_pct(o['hallucination_rate'])} "
          f"({o['hallucinated']} values in slots gold leaves empty)")
    # ASCII only: this goes to a Windows cp1252 console.
    print(f"  |- INVENTED       : {_pct(o['invention_rate'])} "
          f"({o.get('invented', 0)} values found nowhere in the PDF)")
    print(f"  |- misfiled       : {o.get('misfiled', 0)} "
          f"(real content in a slot gold says is EMPTY - a real defect)")
    print(f"  \- out-of-schema  : {o.get('out_of_schema', 0)} "
          f"(real content under a name gold has no field for - NOT a defect)")
    print(f"DEFECT RATE         : {_pct(o.get('defect_rate'))} "
          f"(invented + misfiled / extracted)")
    if o.get("renamed"):
        print(f"renamed             : {o['renamed']} ({_pct(o['rename_rate'])}) "
              f"(right value, different field name — ONE defect, not a "
              f"miss plus a hallucination)")
    print(f"outcome counts      : {o['counts']}")
    cal = report.get("calibration") or {}
    if cal:
        print("\nCONFIDENCE CALIBRATION  (of cells at each level, % correct)")
        print(f"  {'level':<11}{'cells':>7}{'judged':>8}{'correct':>9}"
              f"{'precision':>11}   wrong/near/missed   halluc")
        # Every level the engine can emit, in descending strength. Listing them
        # explicitly (rather than iterating cal.keys()) keeps the order stable;
        # an unknown level is appended rather than dropped, because a level we
        # forgot to list is exactly the thing worth seeing.
        known = ("high", "grounded", "medium", "unverified", "low")
        for lvl in known + tuple(k for k in cal if k not in known):
            b = cal.get(lvl)
            if not b:
                continue
            # Precision is measured over cells gold has an OPINION on. A
            # hallucinated cell is one gold has no slot for — in no-template
            # mode that is usually a field inference proposed and the labels
            # never asked about, which says nothing about the confidence level.
            judged = b["correct"] + b["near"] + b["wrong"] + b["missed"]
            prec = (b["correct"] / judged) if judged else 0
            print(f"  {lvl:<11}{b['n']:>7}{judged:>8}{b['correct']:>9}"
                  f"{prec*100:>10.1f}%   {b['wrong']}/{b['near']}/{b['missed']}"
                  f"        {b['hallucinated']}")
        # "Survival" is the share of cells at a level we stand behind. HIGH and
        # GROUNDED both qualify; they are counted together here and reported
        # separately above, because the DISTINCTION is per-cell and the RATE is
        # per-run. Counting only "high" would have read 0% the moment the
        # no-template path stopped claiming it.
        tot = sum(b["n"] for b in cal.values())
        conf = sum((cal.get(l) or {}).get("n", 0) for l in ("high", "grounded"))
        parts = [f"{l}={(cal.get(l) or {}).get('n', 0)}"
                 for l in ("high", "grounded") if cal.get(l)]
        print(f"  survival: {conf}/{tot} cells ({(conf/tot*100 if tot else 0):.1f}%) "
              f"are at a confident level ({', '.join(parts) or 'none'})")
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
    ap.add_argument("--template", default=None,
                    help="run every selected document through THIS template "
                         "file from tests/gold/templates/ instead of the one "
                         "its labels name, scored against the same gold")
    ap.add_argument("--no-template", action="store_true",
                    help="extract with NO template — the engine infers the "
                         "shape (Phase 3) — and score against the same gold")
    args = ap.parse_args()
    only = set(args.docs.split(",")) if args.docs else None
    run(mode=args.mode, only=only, repeat=args.repeat,
        do_diff=not args.no_diff, no_template=args.no_template,
        template=args.template)


if __name__ == "__main__":
    main()
