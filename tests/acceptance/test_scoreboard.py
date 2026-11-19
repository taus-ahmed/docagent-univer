from __future__ import annotations

import json
import copy

from tests.tools.score_runs import (
    JOB_TRUTH,
    build_scoreboard,
    gate_failures,
    score_record,
    values_equal,
)


def test_scorer_compares_money_identifiers_and_text_by_type():
    assert values_equal(1234.50, "$1,234.50", "money")
    assert values_equal("0042", "0042", "identifier")
    assert not values_equal("0042", "42", "identifier")
    assert values_equal("Harwood Design Studio Ltd", "  harwood  design studio LTD ", "text")


def test_zero_is_scored_as_a_value_not_as_empty():
    truth = {
        "run_id": "zero", "file": "zero.pdf", "absent_slots": [], "tables": [], "totals": {},
        "headers": {"Interest": {"value": 0.0, "type": "money"}},
    }
    record = {
        "needs_review": False,
        "extracted_data": {
            "extracted_data": {"Interest": {"value": "0.00", "ref": "B1"}},
            "validation": {"flagged_fields": []},
        },
    }
    scored = score_record(truth, record)
    assert scored["correct"] == 1 and scored["missing"] == 0


def test_first_recorded_scoreboard_is_reproducible(golden_dir, acceptance_job_records):
    actual = build_scoreboard(golden_dir, acceptance_job_records)
    committed = json.loads(
        (golden_dir.parent / "reports" / "acceptance" / "scoreboard.json").read_text(
            encoding="utf-8"
        )
    )
    assert actual == committed


def test_replayed_results_pass_the_silent_defect_gate(golden_dir, replayed_jobs):
    before = build_scoreboard(golden_dir)
    runs = []
    for job, truth_name in JOB_TRUTH.items():
        truth = json.loads((golden_dir / truth_name).read_text(encoding="utf-8"))
        replay = replayed_jobs[job]
        record = copy.deepcopy(replay["record"])
        record["extracted_data"] = replay["extracted_data"]
        record["document_state"] = replay["extracted_data"]["document_state"]
        record["needs_review"] = record["document_state"] != "READY"
        runs.append(score_record(truth, record, job=job))

    keys = ("expected", "correct", "wrong", "missing", "silent_defects", "false_flags")
    after = {
        "schema_version": 1,
        "runs": runs,
        "totals": {key: sum(run[key] for run in runs) for key in keys},
    }
    after["totals"]["approve_only"] = sum(bool(run["approve_only"]) for run in runs)
    print(
        f"silent defects before={before['totals']['silent_defects']} "
        f"after={after['totals']['silent_defects']}"
    )
    for run in runs:
        print(
            f"job{run['job']} {run['run_id']}: state={run['state']} "
            f"missing={run['missing']} wrong={run['wrong']} "
            f"silent={run['silent_defects']} false_flags={run['false_flags']}"
        )

    assert before["totals"]["silent_defects"] == 35
    assert after["totals"]["silent_defects"] == 0
    assert not gate_failures(after), "\n".join(gate_failures(after))
    job19 = next(run for run in runs if run["job"] == 19)
    assert job19["state"] == "READY"
    # Run B, B8: the "template columns" false flag on this healthy PO is gone.
    assert job19["false_flags"] == 0
    assert job19["approve_only"] is True
