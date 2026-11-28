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
never printed, logged or written, and no dotenv file is read
(DOCAGENT_TEST_NO_DOTENV is set before settings load).

    python -m tools.model_matrix --dry-run

DRY RUN: no key, no network. Builds EVERY (document, model) job exactly as
the live run would -- golden file, template grid and its route, the source
PDF, an Orchestrator on the firm schema (the resolution the app makes in
`job_worker`: the firm's stored schema, else engine/demo_accounting.yaml), the
model pinned on its Gemini provider -- then prints "would make N calls,
estimated cost $X" and exits 0. Any job that cannot be constructed is listed
and the exit code is 2. The HTTP layer is replaced by a function that raises,
so a dry run that reached the network would fail rather than spend.
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


#: Rough sizing for the cost ESTIMATE (the HTTP cap is what actually bounds
#: spend): the slot prompt's fixed text, and a typical answer (thinking billed
#: as output). The worst case uses the model's whole output allowance.
PROMPT_OVERHEAD_CHARS = 8000
TYPICAL_OUTPUT_TOKENS = 3000
CALLS_PER_JOB = 1     # templated slot extraction: one model call per document


class JobError(Exception):
    """A (document, model) job that cannot even be constructed."""


def _no_dotenv() -> None:
    """Never read the backend's dotenv file: the key comes from this shell only."""
    os.environ["DOCAGENT_TEST_NO_DOTENV"] = "1"
    try:
        from pydantic_settings.sources import DotEnvSettingsSource
        DotEnvSettingsSource.__call__ = lambda self: {}
    except ImportError:
        pass


def _paths() -> None:
    for p in (str(ROOT), str(ROOT / "backend" / "engine"), str(ROOT / "backend")):
        if p not in sys.path:
            sys.path.insert(0, p)
    # The harness bootstrap is reached through tests.contract.run_a_driver.
    # Run it HERE first with production parity OFF: parity force-sets
    # GEMINI_MODEL=gemini-2.5-flash-lite, so settings (built on first import)
    # named a different model from the one pinned on the client. bootstrap()
    # is idempotent, so the driver's own later call is then a no-op.
    from tests.harness import bootstrap as bs
    bs.bootstrap(production_parity=False)


def _schema_path(client_id: str = "demo_001") -> str:
    """The firm schema the Orchestrator is built on: the resolution the app
    makes (`job_worker`, storage.get_schema_path), with the harness's
    fallback to the shipped demo schema."""
    from app.core.storage import get_storage
    p = get_storage().get_schema_path(client_id)
    if p is None or not Path(p).is_file():
        p = ROOT / "backend" / "engine" / "demo_accounting.yaml"
    if not Path(p).is_file():
        raise JobError(f"no schema for {client_id} and no {p}")
    return str(p)


def _source(rel: str) -> Path:
    from tests.local_corpus import ROOTS
    for root in ROOTS:
        if (root / rel).is_file():
            return root / rel
    raise JobError(f"source PDF not found under local_docs: {rel}")


def _spec(rel: str, sheet: str, gold: str) -> dict:
    """The model-independent half of a job: truth, template, source."""
    from tests.contract.run_a_driver import template_grid
    import template_shape as TS
    try:
        truth = json.loads((ROOT / "tests" / "golden" / gold).read_text(encoding="utf-8"))
        grid = template_grid(sheet)
    except Exception as e:
        raise JobError(f"{type(e).__name__}: {e}") from e
    route = TS.choose_path(TS.compute_shape(grid), truth.get("document_type", ""), None)
    if route.get("error"):
        raise JobError(f"template {sheet}: {route['error']}")
    return {"truth": truth, "source": _source(rel),
            "template": {"layout": grid, "doc_type": truth.get("document_type", "other")}}


def _orchestrator(model: str, schema_path: str):
    """An Orchestrator built the way the app builds it, with `model` pinned on
    its Gemini provider (the client read GEMINI_MODEL at construction)."""
    from orchestrator import Orchestrator
    import connectors.gemini_client as G
    os.environ["GEMINI_MODEL"] = model
    os.environ["GEMINI_MODEL_FALLBACKS"] = ""        # never a silent switch
    with contextlib.redirect_stdout(io.StringIO()):
        orch = Orchestrator(client_schema_path=schema_path)
    from app.config import settings
    settings.GEMINI_MODEL = model        # call sizing and pricing read settings
    pinned = 0
    for _name, p in getattr(orch.llm, "providers", []) or []:
        if isinstance(p, G.GeminiClient):
            p._preferred = model
            pinned += 1
    if not pinned:
        raise JobError("no Gemini provider to pin the model on")
    why = model_mismatch(model, orch.llm)
    if why:
        raise JobError(why)
    return orch


def model_mismatch(model: str, router):
    """None when settings, the environment and every Gemini client in `router`
    all name `model`; otherwise what disagrees."""
    from app.config import settings
    import connectors.gemini_client as G
    import llm_contract as LC
    seen = {"settings.GEMINI_MODEL": getattr(settings, "GEMINI_MODEL", None),
            "env GEMINI_MODEL": os.environ.get("GEMINI_MODEL"),
            "llm_contract.setting": LC.setting("GEMINI_MODEL", "")}
    seen.update({f"client {n}": p._preferred for n, p in getattr(router, "providers", []) or []
                 if isinstance(p, G.GeminiClient)})
    bad = {k: v for k, v in seen.items() if v != model}
    if bad:
        return "model is not " + repr(model) + ": " + ", ".join(f"{k}={v!r}" for k, v in bad.items())
    return None


def _estimate(source: Path, model: str) -> tuple:
    """(estimated USD, worst-case USD) for one job on `source` with `model`."""
    import pdfplumber
    import call_sizing as CS
    import llm_contract as LC
    price = LC.price_for(model)
    if price is None:
        raise JobError(f"model {model} is not in the price table; the cap cannot price it")
    with pdfplumber.open(str(source)) as pdf:
        chars = sum(len(pg.extract_text() or "") for pg in pdf.pages)
    inp = (chars + PROMPT_OVERHEAD_CHARS) / 4
    est = (inp * price["input"] + TYPICAL_OUTPUT_TOKENS * price["output"]) / 1e6
    worst = (inp * price["input"] + CS.output_limit(model) * price["output"]) / 1e6
    return est * CALLS_PER_JOB, worst * CALLS_PER_JOB


def dry_run(docs, models) -> int:
    """Build every job offline and print the plan; 2 if any job cannot be built."""
    from app.config import settings
    import connectors.gemini_client as G
    attempted = 0

    def _offline_post(self, model, body, timeout):
        nonlocal attempted
        attempted += 1
        raise RuntimeError("model_matrix --dry-run: a network call was attempted")

    saved_env = {k: os.environ.get(k) for k in ("GEMINI_MODEL", "GEMINI_MODEL_FALLBACKS")}
    saved_key, saved_post = settings.GEMINI_API_KEY, G.GeminiClient._post
    saved_model = settings.GEMINI_MODEL
    settings.GEMINI_API_KEY = "model-matrix-dry-run-placeholder"   # never a real key
    G.GeminiClient._post = _offline_post
    failures, jobs, est, worst = [], 0, 0.0, 0.0
    try:
        from app.api.routes.extract import _extract_with_template   # noqa: F401 (importable)
        schema = _schema_path()
        for rel, sheet, gold in docs:
            try:
                spec = _spec(rel, sheet, gold)
            except JobError as e:
                failures += [f"{Path(gold).stem} / {m}: {e}" for m in models]
                continue
            for model in models:
                try:
                    _orchestrator(model, schema)
                    e1, w1 = _estimate(spec["source"], model)
                except Exception as e:
                    failures.append(f"{Path(gold).stem} / {model}: {type(e).__name__}: {e}")
                    continue
                jobs += 1
                est += e1
                worst += w1
    finally:
        settings.GEMINI_API_KEY, G.GeminiClient._post = saved_key, saved_post
        settings.GEMINI_MODEL = saved_model
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    n = jobs * CALLS_PER_JOB
    print(f"model_matrix dry run: {jobs} of {len(docs) * len(models)} jobs built "
          f"({len(docs)} documents x {len(models)} models)")
    print(f"would make {n} calls, estimated cost ${est:.4f} "
          f"(worst case ${worst:.4f}; caps {MAX_CALLS} calls / ${MAX_USD:.2f})")
    if attempted:
        failures.append(f"{attempted} network call(s) attempted during the dry run")
    if n > MAX_CALLS:
        failures.append(f"{n} calls exceeds the {MAX_CALLS}-call cap; the run would be cut short")
    if failures:
        print(f"FAILED: {len(failures)} job(s) cannot be constructed:")
        for f in failures:
            print(f"  - {f}")
        return 2
    return 0


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
    ap.add_argument("--dry-run", action="store_true",
                    help="build every job offline (no key, no network) and report the plan")
    args = ap.parse_args(argv)

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    wanted = {d.strip() for d in args.docs.split(",") if d.strip()}
    docs = [d for d in DOCUMENTS if not wanted or Path(d[2]).stem in wanted]
    unknown = wanted - {Path(d[2]).stem for d in docs}
    if unknown:
        _refuse(f"unknown --docs: {', '.join(sorted(unknown))}")

    _no_dotenv()
    if args.dry_run:
        _paths()
        return dry_run(docs, models)

    if not os.environ.get("GEMINI_API_KEY"):
        _refuse("GEMINI_API_KEY is not set in the environment — this tool makes live "
                "calls and will not run without it (it never reads .env files)")
    _caps()

    _paths()
    os.environ.setdefault("EXTRACTION_TEMPERATURE", "0")     # production temperature
    from tests.tools import live_cap
    from tests.tools.score_runs import score_record

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    live_cap.install(out / "live_cap_state.json", label="model_matrix")

    from app.api.routes.extract import _extract_with_template
    schema = _schema_path()

    summary = []
    stopped = None
    for rel, sheet, gold in docs:
        try:
            spec = _spec(rel, sheet, gold)
        except JobError as e:
            summary += [{"doc": Path(gold).stem, "model": m, "error": f"JobError: {e}"}
                        for m in models]
            continue
        truth = spec["truth"]
        for model in models:
            live_cap.set_label(f"{model} {Path(rel).name}")
            t0 = time.monotonic()
            try:
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    orch = _orchestrator(model, schema)
                    results = _extract_with_template(orch, spec["source"], spec["template"])
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
