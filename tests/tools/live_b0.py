"""Run B, B0: capped live measurement through the real engine path.

    python -m tests.tools.live_b0 --state <scratch>/live_state.json \
        --out <scratch>/b0 --case bank [--case w2 ...]

Every HTTP request goes through ``tests.tools.live_cap`` (12 calls, 1.00 USD,
shared across processes by the state file). The key is read only by the
client from the environment; nothing here prints or stores it. Results and
raw responses go to --out (keep that outside the repo unless a raw response
is deliberately committed as a replay fixture).
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

os.environ["DOCAGENT_TEST_NO_DOTENV"] = "1"

from tests.harness import bootstrap as _bootstrap  # noqa: E402

_bootstrap.bootstrap()

from tests.tools import live_cap  # noqa: E402
from tests.tools.score_runs import score_record  # noqa: E402
from tests.contract.run_a_driver import template_grid  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "local_docs" / "DocAgent_testdocs"
GOLDEN = ROOT / "tests" / "golden"

CASES = {
    "bank": ("bank_statement/flowparse_bank_us.pdf", "Bank_Recon", "bank_statement",
             "flowparse_bank_us.json"),
    "w2": ("w2/irs_w2_mod11.pdf", "W2_Full", "w2", "irs_w2_mod11.json"),
    "nec": ("1099/irs_1099nec_ellis.pdf", "F1099_NEC_MISC", "form_1099",
            "irs_1099nec_ellis.json"),
    "card": ("credit_card/flowparse_card_us.pdf", "Card_Stmt", "credit_card_statement",
             "flowparse_card_us.json"),
}


def run_case(name: str, out: Path, tag: str, grid=None) -> dict:
    import llm_contract as C
    from connectors.llm_router import LLMRouter
    from extractor import run_extraction

    rel, sheet, doc_type, truth_name = CASES[name]
    live_cap.set_label(f"{name}{tag}")
    grid = grid or template_grid(sheet)
    orch = SimpleNamespace(llm=LLMRouter())
    t0 = time.monotonic()
    err = None
    results = []
    with C.collect_attempts(fresh=True) as attempts:
        try:
            results = run_extraction(orch, DOCS / rel,
                                     {"layout": grid, "doc_type": doc_type})
        except live_cap.CapReached as e:
            err = f"cap reached: {e}"
        except Exception as e:  # a failure is a measurement, never a retry
            err = f"{type(e).__name__}: {e}"
    wall = round(time.monotonic() - t0, 1)
    report = {"case": name, "tag": tag, "wall_s": wall, "error": err,
              "attempts": list(attempts) if attempts else []}
    if results:
        ed = results[0].extracted_data
        truth = json.loads((GOLDEN / truth_name).read_text(encoding="utf-8"))
        rec = {"extracted_data": ed, "document_state": ed.get("document_state"),
               "needs_review": ed.get("needs_review")}
        sc = score_record(truth, rec)
        rows = {k: len(v) for k, v in ed.items()
                if (k.endswith("_rows") or k == "table_rows") and isinstance(v, list)}
        report.update(score={k: sc[k] for k in ("expected", "correct", "wrong",
                                                "missing", "silent_defects",
                                                "false_flags", "approve_only",
                                                "state")},
                      details=sc["details"], rows=rows,
                      flags=(ed.get("validation") or {}).get("flagged_fields"))
        raws = ed.get("raw_llm_responses") or []
        report["tables_key_in_answer"] = []
        for raw in raws:
            try:
                j = json.loads(raw)
                report["tables_key_in_answer"].append(
                    {"has_tables": "tables" in j,
                     "table_rows": {k: len(v) for k, v in (j.get("tables") or {}).items()
                                    if isinstance(v, list)}
                     if isinstance(j.get("tables"), dict) else None})
            except Exception:
                report["tables_key_in_answer"].append({"unparsed": len(raw or "")})
        (out / f"{name}{tag}.raw.json").write_text(json.dumps(raws, indent=1),
                                                   encoding="utf-8")
        (out / f"{name}{tag}.result.json").write_text(
            json.dumps(ed, indent=1, default=str), encoding="utf-8")
    (out / f"{name}{tag}.report.json").write_text(
        json.dumps(report, indent=1, default=str), encoding="utf-8")
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--case", action="append", required=True)
    ap.add_argument("--tag", default="")
    a = ap.parse_args(argv)
    if not os.environ.get("GEMINI_API_KEY"):
        print("GEMINI_API_KEY not set: not measured")
        return 0
    a.out.mkdir(parents=True, exist_ok=True)
    live_cap.install(a.state)
    for i, case in enumerate(a.case):
        rep = run_case(case, a.out, a.tag or (f"_{i + 1}" if a.case.count(case) > 1 else ""))
        print(json.dumps({k: rep.get(k) for k in ("case", "tag", "wall_s", "error",
                                                    "score", "rows",
                                                    "tables_key_in_answer")},
                         default=str), flush=True)
        if rep.get("error", "") and "cap reached" in rep["error"]:
            break
    live_cap.summary()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
