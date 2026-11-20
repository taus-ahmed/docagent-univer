"""Model matrix: 8 documents x 5 models, scored against tests/golden.

    GEMINI_API_KEY=... python -m tools.model_matrix [--out local_docs/job_records/matrix]
                                                    [--models a,b] [--docs pitt_sample_w2,...]

LIVE CALLS, REAL MONEY. Written in the overnight run (M3) and deliberately
NOT run there; the owner runs it. Hard caps at HTTP level: at most 50
requests and USD 1.00 for the whole run, counted by tests/tools/live_cap.py
on `GeminiClient._post` (every request, retry included; a failed request is
charged pessimistically). The caps can be lowered with LIVE_CAP_MAX_CALLS /
LIVE_CAP_MAX_USD; this tool refuses values above its own 50 / 1.00.

Each (document, model) result is written as a GET /results-shaped record to
<out>/<model>/<document>.json and scored with tests/tools/score_runs.py
against tests/golden/<document>.json. The summary is <out>/summary.json and
<out>/summary.md. Order is document-major (every model reads document 1
before any reads document 2), so a cap that stops the run cuts the same
documents from every model.

It refuses to start without GEMINI_API_KEY in the environment. The key is
never printed, logged or written.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_CALLS = 50
MAX_USD = 1.00

#: (PDF under local_docs/DocAgent_testdocs, template sheet in
#: tests/fixtures/acceptance/templates/DocAgent_templates_v2.xlsx, golden file)
DOCUMENTS = [
    ("w2/pitt_sample_w2.pdf", "W2_Full", "pitt_sample_w2.json"),
    ("w2/irs_w2_mod11.pdf", "W2_Full", "irs_w2_mod11.json"),
    ("1099/irs_1099int_mod3.pdf", "F1099_INT_DIV", "irs_1099int_mod3.json"),
    ("1099/irs_1099nec_ellis.pdf", "F1099_NEC_MISC", "irs_1099nec_ellis.json"),
    ("bank_statement/flowparse_bank_us.pdf", "Bank_Recon", "flowparse_bank_us.json"),
    ("bank_statement/mammoth_2pg.pdf", "Bank_Recon", "mammoth_2pg.json"),
    ("invoice/flowparse_invoice_tax.pdf", "AP_Inv_Full", "flowparse_invoice_tax.json"),
    ("purchase_order/flowparse_po.pdf", "PO_Full", "flowparse_po.json"),
]

#: Today's production model first, then the candidates (docs/MODEL_MIGRATION.md).
MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-3.5-flash-lite",
    "gemini-3.6-flash",
    "gemini-3.8-flash",
]


def _refuse(msg: str):
    raise SystemExit(f"model_matrix: {msg}")


def _caps() -> None:
    """Install the HTTP-level cap at no more than 50 calls / USD 1.00."""
    calls = os.environ.get("LIVE_CAP_MAX_CALLS")
    usd = os.environ.get("LIVE_CAP_MAX_USD")
    try:
        if calls is not None and int(float(calls)) > MAX_CALLS:
            _refuse(f"LIVE_CAP_MAX_CALLS may not exceed {MAX_CALLS}")
        if usd is not None and float(usd) > MAX_USD:
            _refuse(f"LIVE_CAP_MAX_USD may not exceed {MAX_USD:.2f}")
    except ValueError:
        _refuse("LIVE_CAP_MAX_CALLS / LIVE_CAP_MAX_USD must be numbers")
    os.environ.setdefault("LIVE_CAP_MAX_CALLS", str(MAX_CALLS))
    os.environ.setdefault("LIVE_CAP_MAX_USD", f"{MAX_USD:.2f}")


def _record(result, filename: str) -> dict:
    ed = getattr(result, "extracted_data", None) or {}
    resp = getattr(result, "extraction_response", None)
    return {"id": 1, "filename": filename, "original_filename": filename,
            "extracted_data": ed,
            "model_used": getattr(resp, "model_version", None) or getattr(resp, "model_used", None),
            "tokens_used": getattr(resp, "tokens_used", 0) if resp else 0,
            "needs_review": bool(ed.get("needs_review"))}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=str(ROOT / "local_docs" / "job_records" / "matrix"))
    ap.add_argument("--models", default=",".join(MODELS))
    ap.add_argument("--docs", default="")
    args = ap.parse_args(argv)

    if not os.environ.get("GEMINI_API_KEY"):
        _refuse("GEMINI_API_KEY is not set in the environment — this tool makes live "
                "calls and will not run without it (it never reads .env files)")
    _caps()

    sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "backend" / "engine"), str(ROOT)]
    os.environ.setdefault("EXTRACTION_TEMPERATURE", "0")     # production temperature
    from tests.tools import live_cap
    from tests.tools.score_runs import score_record
    from tests.contract.run_a_driver import template_grid
    from tests.local_corpus import local_file

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    live_cap.install(out / "live_cap_state.json", label="model_matrix")
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    wanted = {d.strip() for d in args.docs.split(",") if d.strip()}
    docs = [d for d in DOCUMENTS if not wanted or Path(d[2]).stem in wanted]

    from app.api.routes.extract import _extract_with_template
    from orchestrator import Orchestrator
    import connectors.gemini_client as G

    summary = []
    stopped = None
    for rel, sheet, gold in docs:
        truth = json.loads((ROOT / "tests" / "golden" / gold).read_text(encoding="utf-8"))
        template = {"layout": template_grid(sheet), "doc_type": truth.get("document_type", "other")}
        for model in models:
            os.environ["GEMINI_MODEL"] = model
            os.environ["GEMINI_MODEL_FALLBACKS"] = ""        # never a silent switch
            live_cap.set_label(f"{model} {Path(rel).name}")
            t0 = time.monotonic()
            try:
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    orch = Orchestrator()
                    # the client read GEMINI_MODEL from settings at import;
                    # pin this cell's model on the router's Gemini provider
                    pinned = 0
                    for _name, p in getattr(orch.llm, "providers", []) or []:
                        if isinstance(p, G.GeminiClient):
                            p._preferred = model
                            pinned += 1
                    if not pinned:
                        _refuse("no Gemini provider to pin the model on")
                    results = _extract_with_template(orch, local_file(rel), template)
            except live_cap.CapReached as e:
                stopped = f"cap reached ({e}) before {model} / {Path(rel).name}"
                break
            except Exception as e:                      # one cell of the matrix
                summary.append({"doc": Path(gold).stem, "model": model,
                                "error": f"{type(e).__name__}: {str(e)[:200]}"})
                continue
            rec = _record(results[0], Path(rel).name) if results else {"extracted_data": {}}
            dest = out / model / f"{Path(gold).stem}.json"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(json.dumps([rec], indent=1, default=str), encoding="utf-8")
            score = score_record(truth, rec)
            summary.append({"doc": Path(gold).stem, "model": model,
                            "model_version": rec.get("model_used"),
                            "seconds": round(time.monotonic() - t0, 1),
                            **{k: score.get(k) for k in ("expected", "correct", "wrong",
                                                         "missing", "silent_defects",
                                                         "false_flags", "approve_only",
                                                         "state")}})
        if stopped:
            break

    state = live_cap.summary()
    report = {"stopped": stopped, "calls": state.get("calls"), "usd": state.get("usd"),
              "rows": summary}
    (out / "summary.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    lines = ["| Document | Model | Version | Correct/Expected | Wrong | Missing | Silent | False flags | State |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in summary:
        if "error" in r:
            lines.append(f"| {r['doc']} | {r['model']} | | ERROR: {r['error']} | | | | | |")
            continue
        lines.append(f"| {r['doc']} | {r['model']} | {r.get('model_version') or ''} | "
                     f"{r.get('correct')}/{r.get('expected')} | {r.get('wrong')} | "
                     f"{r.get('missing')} | {r.get('silent_defects')} | "
                     f"{r.get('false_flags')} | {r.get('state')} |")
    lines.append(f"\n{state.get('calls')} HTTP calls, ${state.get('usd', 0):.4f}"
                 + (f" — STOPPED: {stopped}" if stopped else ""))
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
