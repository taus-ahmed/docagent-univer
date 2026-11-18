from __future__ import annotations

import json
from pathlib import Path

import pytest


OWNER_RUNS = {
    "flowparse_bank_us",
    "mammoth_2pg",
    "flowparse_card_us",
    "flowparse_invoice_tax",
    "flowparse_po",
    "flowparse_cafe",
    "irs_w2_mod11",
    "irs_w2_2012",
    "irs6744_w2_mcguire",
    "pitt_sample_w2",
    "irs_1099nec_ellis",
    "irs_1099int_mod3",
    "irs6744_brokerage_1099DIV_MISC_INT_B",
    "irs_1098_joe_angela",
}


def _truths(golden_dir: Path):
    for path in sorted(golden_dir.glob("*.json")):
        yield path, json.loads(path.read_text(encoding="utf-8"))


def test_all_fourteen_owner_runs_have_truth_files(golden_dir):
    found = {data["run_id"] for _, data in _truths(golden_dir)}
    assert OWNER_RUNS <= found


def test_answers_sheet_contributes_additional_truth_files(golden_dir):
    found = {data["run_id"] for _, data in _truths(golden_dir)}
    assert len(found - OWNER_RUNS) >= 7


@pytest.mark.parametrize("required", [
    "schema_version", "run_id", "file", "template_name", "document_type",
    "headers", "tables", "totals", "absent_slots",
])
def test_every_truth_has_the_contract_key(golden_dir, required):
    missing = [path.name for path, data in _truths(golden_dir) if required not in data]
    assert not missing, f"{required} missing in {missing}"


def test_absent_slots_are_explicit_and_unique(golden_dir):
    for path, truth in _truths(golden_dir):
        absent = truth["absent_slots"]
        assert isinstance(absent, list) and absent, path.name
        assert len(absent) == len(set(absent)), path.name


def test_zero_is_a_value_in_the_brokerage_truth(golden_dir):
    truth = json.loads(
        (golden_dir / "irs6744_brokerage_1099DIV_MISC_INT_B.json").read_text(
            encoding="utf-8"
        )
    )
    zeros = [entry["value"] for entry in truth["headers"].values() if entry["value"] == 0]
    assert len(zeros) >= 6


def test_receipt_uses_the_printed_accent(golden_dir):
    truth = json.loads((golden_dir / "flowparse_cafe.json").read_text(encoding="utf-8"))
    assert truth["headers"]["Merchant"]["value"] == "FERN & COPPER CAFÉ"
