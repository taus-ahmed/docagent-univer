"""Offline replay scoreboard for every committed Run B answer.

    python -m tests.tools.replay_scoreboard [--json out.json]

Replays both the four committed owner jobs (15, 19, 21, 25) and all three
recorded Run B live answers through the CURRENT engine, then scores each
against tests/golden with `tests/tools/score_runs.score_record`.  The live
answers here are recordings: this tool never creates a provider client and
never makes a model or network call.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path

os.environ.setdefault("DOCAGENT_TEST_NO_DOTENV", "1")

from tests.contract.run_a_driver import replay_job  # noqa: E402
from tests.tools.score_runs import JOB_TRUTH, DEFAULT_GOLDEN, score_record  # noqa: E402

KEYS = ("expected", "correct", "wrong", "missing", "silent_defects", "false_flags")

LIVE_CASES = (
    ("live-bank", "bank_live_b0.raw.json", "flowparse_bank_us.json",
     "bank_statement/flowparse_bank_us.pdf", "Bank_Recon", "bank_statement"),
    ("live-card", "card_live_b0.raw.json", "flowparse_card_us.json",
     "credit_card/flowparse_card_us.pdf", "Card_Stmt", "credit_card_statement"),
    ("live-w2", "w2_mod11_live_b0.raw.json", "irs_w2_mod11.json",
     "w2/irs_w2_mod11.pdf", "W2_Full", "w2"),
)


def _replay_live(raw_name: str, rel: str, sheet: str, doc_type: str) -> dict:
    """Replay one recorded answer without constructing a live LLM client."""
    from types import SimpleNamespace

    import llm_contract as contract
    from connectors.base import LLMResponse
    from core.preprocessor import preprocess_file
    from slot_extractor import run_slot_extraction
    from tests.contract.run_a_driver import DOCS, FIXTURES, template_grid

    raw_path = FIXTURES.parent / "run_b" / raw_name
    raw = json.loads(raw_path.read_text(encoding="utf-8"))[0]
    answer = json.loads(raw)
    path = DOCS / rel
    document = preprocess_file(path)

    def extract(**_kwargs):
        return LLMResponse(raw_text=raw, parsed_json=copy.deepcopy(answer),
                           success=True, model_used="offline-recorded-answer")

    count = len(document.page_texts)
    with contract.collect_attempts(fresh=True):
        data = run_slot_extraction(
            SimpleNamespace(llm=SimpleNamespace(extract=extract)), path,
            {"layout": template_grid(sheet)}, None, page_images=[],
            doc_text=document.extracted_text,
            doc_text_pages=document.page_texts,
            file_type="digital_pdf", default_doc_type=doc_type, start=0.0,
            page_lines=document.page_lines,
            page_origins={i + 1: origin
                          for i, origin in enumerate(document.page_origins)},
            page_numbers=list(range(1, count + 1)),
            widget_values=document.widget_values,
            form_fields=document.form_fields,
            unreadable={"ocr_failed": document.ocr_failed_pages,
                        "ocr_zero": document.ocr_zero_word_pages},
        )[0].extracted_data
    return {"extracted_data": data,
            "document_state": data.get("document_state"),
            "needs_review": data.get("document_state") != "READY"}


def scoreboard(dump: Path | None = None) -> dict:
    runs = []
    for job, truth_name in JOB_TRUTH.items():
        truth = json.loads((DEFAULT_GOLDEN / truth_name).read_text(encoding="utf-8"))
        rep = replay_job(job)
        record = copy.deepcopy(rep["record"])
        record["extracted_data"] = rep["extracted_data"]
        record["document_state"] = rep["extracted_data"].get("document_state")
        record["needs_review"] = record["document_state"] != "READY"
        run = score_record(truth, record, job=job)
        run["source"] = f"frozen-job-{job}"
        if dump is not None:
            dump.mkdir(parents=True, exist_ok=True)
            (dump / f"job{job}.json").write_text(
                json.dumps([record], default=str, ensure_ascii=False), encoding="utf-8")
        run["flags"] = [f for f in (rep["extracted_data"].get("validation") or {})
                        .get("flagged_fields") or []]
        runs.append(run)
    for source, raw_name, truth_name, rel, sheet, doc_type in LIVE_CASES:
        truth = json.loads((DEFAULT_GOLDEN / truth_name).read_text(encoding="utf-8"))
        record = _replay_live(raw_name, rel, sheet, doc_type)
        run = score_record(truth, record)
        run["source"] = source
        run["flags"] = [f for f in (record["extracted_data"].get("validation") or {})
                        .get("flagged_fields") or []]
        if dump is not None:
            dump.mkdir(parents=True, exist_ok=True)
            (dump / f"{source}.json").write_text(
                json.dumps([record], default=str, ensure_ascii=False), encoding="utf-8")
        runs.append(run)
    totals = {k: sum(r[k] for r in runs) for k in KEYS}
    totals["approve_only"] = sum(bool(r["approve_only"]) for r in runs)
    return {"runs": runs, "totals": totals}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=Path)
    ap.add_argument("--dump", type=Path, help="write each replayed record here "
                    "(input for tools/score_runs.py)")
    a = ap.parse_args(argv)
    sb = scoreboard(a.dump)
    for r in sb["runs"]:
        print(f"{r['source']} {r['run_id']}: state={r['state']} "
              + " ".join(f"{k}={r[k]}" for k in KEYS)
              + f" approve_only={r['approve_only']}")
        for d in r["details"]:
            print(f"    {d['outcome']}: {d['key']} expected={d['expected']!r} "
                  f"actual={d['actual']!r} flagged={d['flagged']}")
        for f in r["flags"]:
            print(f"    FLAG {f.get('ref')}: {str(f.get('reason'))[:90]}")
    print("TOTAL " + " ".join(f"{k}={v}" for k, v in sb["totals"].items()))
    if a.json:
        a.json.write_text(json.dumps(sb, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
