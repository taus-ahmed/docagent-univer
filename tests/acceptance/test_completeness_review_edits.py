from __future__ import annotations

import copy

import pytest

from tests.contract import names
from tests.contract.adapter import (
    assert_non_ready_with_reason,
    coverage_of,
    evaluate_answer,
    resolve_callable,
    state_of,
)


RUN_A3 = pytest.mark.xfail(
    strict=True,
    reason="Run A3: source inventory and unplaced AcroForm evidence are not implemented",
)
RUN_A4 = pytest.mark.xfail(
    strict=True,
    reason="Run A4: completeness gate and evidence-aware empty flags are not implemented",
)
RUN_A5 = pytest.mark.xfail(
    strict=True,
    reason="Run A5: dispositions, review gating, and end-to-end edit persistence are not implemented",
)


@RUN_A4
def test_bank_inventory_survives_an_empty_model_answer():
    result = evaluate_answer(
        model_result={"raw_text": "{}", "finish_reason": "STOP", "candidates": [{}]},
        expected_slots=["Opening Balance", "Closing Balance"],
        expected_tables=["Transactions"],
        section="full_document",
        source_inventory={
            "candidate_rows": 12,
            "unplaced_amounts": [10309.62, 12445.50],
        },
    )
    coverage = coverage_of(result)
    assert coverage[names.CANDIDATE_ROWS_FIELD] in range(11, 14)
    assert coverage[names.EXTRACTED_ROWS_FIELD] == 0
    assert coverage[names.UNPLACED_AMOUNTS_FIELD] == [10309.62, 12445.50]
    assert_non_ready_with_reason(result)


@RUN_A3
def test_fillable_widget_values_survive_an_empty_model_answer():
    result = evaluate_answer(
        model_result={"raw_text": "{}", "finish_reason": "STOP", "candidates": [{}]},
        expected_slots=["Box 1", "Employee Name"],
        expected_tables=[],
        section="full_document",
        source_inventory={"unplaced_widget_values": ["10,535", "SETH W. WIGGINS"]},
    )
    coverage = coverage_of(result)
    assert coverage[names.UNPLACED_WIDGET_VALUES_FIELD] == ["10,535", "SETH W. WIGGINS"]
    assert_non_ready_with_reason(result)


@pytest.mark.parametrize(
    "slot,source_inventory",
    [
        ("Payer Name", {"label_only_slots": ["Payer Name"]}),
        ("Total Withdrawals", {"unplaced_amounts_by_slot": {"Total Withdrawals": [10309.62]}}),
    ],
)
@RUN_A4
def test_evidence_behind_an_empty_slot_is_flagged(slot, source_inventory):
    result = evaluate_answer(
        model_result={
            "raw_text": '{"fields":{"F1":{"value":"","source":"%s"}},"tables":{}}' % slot,
            "finish_reason": "STOP",
            "candidates": [{}],
        },
        expected_slots=[slot],
        expected_tables=[],
        absent_slots=[],
        section="full_document",
        source_inventory=source_inventory,
    )
    flags = result.get("flags") or []
    assert any(flag.get("slot") == slot for flag in flags)
    assert state_of(result) == names.DOCUMENT_STATE_NEEDS_ATTENTION


@pytest.mark.parametrize("slot", ["GL Account", "PO Number"])
@RUN_A4
def test_a_truly_absent_slot_is_not_false_flagged(slot):
    result = evaluate_answer(
        model_result={
            "raw_text": '{"fields":{"F1":{"value":"","source":""}},"tables":{}}',
            "finish_reason": "STOP",
            "candidates": [{}],
        },
        expected_slots=[slot],
        expected_tables=[],
        absent_slots=[slot],
        section="full_document",
        source_inventory={},
    )
    assert not any(flag.get("slot") == slot for flag in result.get("flags") or [])


@RUN_A5
def test_mark_reviewed_rejects_open_attention_reasons():
    evaluator = resolve_callable(names.REVIEW_DISPOSITION_EVALUATOR)
    result = evaluator(
        document={
            names.DOCUMENT_STATE_FIELD: names.DOCUMENT_STATE_NEEDS_ATTENTION,
            names.DIAGNOSTICS_FIELD: {names.REASONS_FIELD: [{"code": "coverage_gap", "open": True}]},
        },
        action="mark_reviewed",
        dispositions=[],
    )
    assert result["accepted"] is False


@RUN_A5
def test_each_open_reason_must_be_dispositioned_explicitly():
    evaluator = resolve_callable(names.REVIEW_DISPOSITION_EVALUATOR)
    result = evaluator(
        document={
            names.DOCUMENT_STATE_FIELD: names.DOCUMENT_STATE_NEEDS_ATTENTION,
            names.DIAGNOSTICS_FIELD: {
                names.REASONS_FIELD: [
                    {"id": "r1", "code": "coverage_gap", "open": True},
                    {"id": "r2", "code": "unplaced_value", "open": True},
                ]
            },
        },
        action="mark_reviewed",
        dispositions=[{"reason_id": "r1", "disposition": "accepted_absent"}],
    )
    assert result["accepted"] is False
    assert result["open_reason_count"] == 1


@RUN_A5
def test_reviewing_never_deletes_coverage_reasons_or_banner_counts():
    evaluator = resolve_callable(names.REVIEW_DISPOSITION_EVALUATOR)
    result = evaluator(
        document={
            names.DOCUMENT_STATE_FIELD: names.DOCUMENT_STATE_NEEDS_ATTENTION,
            names.DIAGNOSTICS_FIELD: {
                names.REASONS_FIELD: [{"id": "r1", "code": "coverage_gap", "open": True}]
            },
        },
        action="mark_reviewed",
        dispositions=[{"reason_id": "r1", "disposition": "source_unreadable"}],
    )
    reasons = result[names.DIAGNOSTICS_FIELD][names.REASONS_FIELD]
    assert reasons and reasons[0][names.REASON_CODE_FIELD] == names.REASON_COVERAGE_GAP
    assert result["legend_count"] == 1
    assert result["banner_count"] == 1


def test_current_edit_reconciliation_keeps_machine_history_for_fields_and_tables():
    from app.services.edits import _reconcile_edits

    stored = {
        "extracted_fields": {"B1": "machine"},
        "extracted_data": {"Header": {"value": "machine", "confidence": "high", "ref": "B1"}},
        "field_provenance": {"B1": {"source": "machine", "page": 1}},
        "validation": {"confidence_map": {"B1": "high"}},
        "slot_map": {"fields": [{"ref": "B1", "row_label": "Header"}], "tables": []},
        "Items_rows": [{"Item": "A", "Amount": "10.00"}],
    }
    incoming = copy.deepcopy(stored)
    incoming["extracted_fields"]["B1"] = "human"
    incoming["Items_rows"][0]["Amount"] = "12.00"
    edited = _reconcile_edits(stored, incoming)
    assert edited["extracted_fields"]["B1"] == "human"
    assert edited["field_provenance"]["B1"]["original_value"] == "machine"
    assert edited["Items_rows"][0]["_original"]["Amount"] == "10.00"
    assert "Amount" in edited["Items_rows"][0]["_edited"]


@RUN_A5
def test_edits_survive_accept_reload_and_download():
    # The fixture is intentionally supplied by the Run A integration branch;
    # keeping the route names in names.py makes this test a one-file adapter update.
    http_client = resolve_callable(names.HTTP_ACCEPTANCE_DRIVER)()
    created = http_client.create_recorded_job(19)
    assert http_client.edit(created, "B1", "PO-HUMAN").ok
    assert http_client.edit_table(created, "table", 0, "Quantity", 13).ok
    assert http_client.accept(created).ok
    reloaded = http_client.reload(created)
    assert reloaded.field("B1") == "PO-HUMAN"
    assert reloaded.table_cell("table", 0, "Quantity") == 13
    assert reloaded.original("B1") == "PO-2026-1147"
    downloaded = http_client.download(created)
    assert downloaded.cell("B1") == "PO-HUMAN"
    assert downloaded.table_cell("table", 0, "Quantity") == 13


@RUN_A5
def test_failed_save_is_visible_to_the_reviewer():
    http_client = resolve_callable(names.HTTP_ACCEPTANCE_DRIVER)()
    created = http_client.create_recorded_job(19)
    http_client.fail_next_save()
    response = http_client.edit(created, "B1", "PO-HUMAN")
    assert not response.ok
    assert response.visible_error
