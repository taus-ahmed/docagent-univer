"""Frozen-replay scoreboard (Run B acceptance item 2).

    python -m tests.tools.replay_scoreboard [--json out.json]

Replays the four committed owner jobs (15, 19, 21, 25) through the CURRENT
engine with their frozen model answers (`tests/contract/run_a_driver.py`) and
scores each against tests/golden with `tests/tools/score_runs.score_record`.
No model calls.
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
        if dump is not None:
            dump.mkdir(parents=True, exist_ok=True)
            (dump / f"job{job}.json").write_text(
                json.dumps([record], default=str, ensure_ascii=False), encoding="utf-8")
        run["flags"] = [f for f in (rep["extracted_data"].get("validation") or {})
                        .get("flagged_fields") or []]
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
        print(f"job{r['job']} {r['run_id']}: state={r['state']} "
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
