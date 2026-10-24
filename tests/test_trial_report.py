"""scripts/trial_report.py on synthetic data (tests/fixtures/trial/)."""
import csv
import importlib.util
import json
from pathlib import Path

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

FIX = bs.TESTS_DIR / "fixtures" / "trial"
_spec = importlib.util.spec_from_file_location(
    "trial_report", bs.REPO_DIR / "scripts" / "trial_report.py")
tr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tr)


def _run(tmp_path, with_results):
    out = tmp_path / "r"
    argv = ["--truth", str(FIX / "outcomes.csv"), "--out", str(out)]
    if with_results:
        argv += ["--results", str(FIX / "results.json")]
    assert tr.main(argv) == 0
    md = (out.with_suffix(".md")).read_text(encoding="utf-8")
    rows = list(csv.reader(open(str(out) + ".csv", encoding="utf-8")))
    return md, {(r[0], r[1], r[2]): r for r in rows[1:]}


@pytest.mark.parametrize("with_results", [True, False])
def test_the_safety_numbers(tmp_path, with_results):
    md, rows = _run(tmp_path, with_results)
    assert rows[("safety", "", "")][3:6] == ["12", "6", "6"]
    assert rows[("silent_wrong", "", "high+grounded")][3:6] == ["6", "5", "1"]
    assert rows[("wrong_no_flag", "", "")][3] == "5"
    assert rows[("false_alarm", "", "")][3] == "1"
    assert "**1 of 6**" in md
    assert "cheques found / truth | 3 / 4 (missing 1, extra 0)" in md


def test_per_level_and_field(tmp_path):
    _, rows = _run(tmp_path, True)
    assert rows[("level", "", "verified")][3:7] == ["4", "3", "1", "75.0%"]
    assert rows[("level", "", "low")][3:6] == ["1", "0", "1"]
    assert rows[("level", "", "empty")][3:6] == ["4", "0", "4"]
    assert rows[("field", "Payee", "all")][3:6] == ["4", "2", "2"]
    assert rows[("field_level", "Amount in Figures", "unverified")][3:6] == ["1", "1", "0"]


def test_reason_precision(tmp_path):
    _, rows = _run(tmp_path, True)
    assert rows[("reason", "checksum_failed", "")][3:7] == ["1", "", "1", "100.0%"]
    assert rows[("reason", "ocr_origin", "")][3:7] == ["1", "", "0", "0.0%"]


def test_the_cheque_counts(tmp_path):
    _, rows = _run(tmp_path, True)
    assert rows[("cheques", "chq-b.pdf", "")][3:7] == ["2", "1", "", "dropped or merged"]
    assert rows[("cheques", "chq-a.pdf", "")][3:5] == ["2", "2"]


def test_the_report_explains_itself(tmp_path):
    md, _ = _run(tmp_path, True)
    for term in ("Silent-wrong rate", "Wrong with no flag", "False alarms",
                 "Cheques found vs truth", "Reason precision"):
        assert term in md


def test_notation_does_not_count_as_wrong():
    assert tr.same_value("$1,250.00", "1250")
    assert tr.same_value("(5.00)", "-5")
    assert tr.same_value("ACME LTD", "Acme Ltd")
    assert not tr.same_value("99.00", "990.00")


def test_the_results_json_overrides_the_csvs_copy(tmp_path):
    """The accountant's yes/no is about the value HE saw; when the results
    say something else, the value is re-judged against the truth."""
    data = json.loads((FIX / "results.json").read_text(encoding="utf-8"))
    data[0]["extracted_data"]["extracted_fields"]["B1"] = "1300.00"
    p = tmp_path / "res.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    out = tmp_path / "o"
    tr.main(["--truth", str(FIX / "outcomes.csv"), "--results", str(p), "--out", str(out)])
    rows = {(r[0], r[1], r[2]): r for r in csv.reader(open(str(out) + ".csv", encoding="utf-8"))}
    assert rows[("silent_wrong", "", "high+grounded")][5] == "2"

