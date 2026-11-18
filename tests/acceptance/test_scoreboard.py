from __future__ import annotations

import json

import pytest

from tests.tools.score_runs import build_scoreboard, gate_failures, score_record, values_equal


RUN_A4 = pytest.mark.xfail(
    strict=True,
    reason="Run A4: recorded empty/partial jobs still report READY and create silent defects",
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


@RUN_A4
def test_recorded_results_pass_the_silent_defect_gate(golden_dir, acceptance_job_records):
    failures = gate_failures(build_scoreboard(golden_dir, acceptance_job_records))
    assert not failures, "\n".join(failures)
