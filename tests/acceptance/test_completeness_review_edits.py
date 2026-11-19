from __future__ import annotations

import copy
import io

import pytest
from openpyxl import load_workbook

from tests.contract import names
from tests.contract.adapter import coverage_of, state_of
from tests.contract.run_a_driver import words


def _stored(client, auth, job_id):
    response = client.get(f"/api/jobs/{job_id}/results", headers=auth["acme"])
    assert response.status_code == 200, response.text
    return response.json()[0]["extracted_data"]


def test_bank_inventory_survives_the_recorded_missing_table(replayed_jobs):
    data = replayed_jobs[15]["extracted_data"]
    coverage = coverage_of(data)
    rows = coverage[names.ROWS_FIELD]["table"]
    assert rows[names.CANDIDATE_ROWS_FIELD] == 12
    assert rows[names.EXTRACTED_ROWS_FIELD] == 0
    unplaced = {entry["value"] for entry in coverage[names.UNPLACED_AMOUNTS_FIELD]}
    assert {"$10,309.62", "$12,445.50"} <= unplaced
    assert state_of(data) == names.DOCUMENT_STATE_NEEDS_ATTENTION


def test_fillable_widget_values_survive_the_recorded_empty_answer(monkeypatch):
    """The Run A safety net, with the Run B form-field lane switched off (no
    widget matches any slot): the widget values are still reported."""
    import form_fields
    from tests.contract.run_a_driver import replay_job

    monkeypatch.setattr(form_fields, "match", lambda *a, **k: (None, False))
    data = replay_job(21)["extracted_data"]
    coverage = coverage_of(data)
    values = {entry["value"] for entry in coverage[names.UNPLACED_WIDGET_VALUES_FIELD]}
    assert "10535" in values
    assert any("SETH W. WIGGINS" in value for value in values)
    assert state_of(data) == names.DOCUMENT_STATE_NEEDS_ATTENTION


def test_fillable_widget_values_reach_their_cells_through_the_form_lane(replayed_jobs):
    """Run B, B1: with the lane on, the same empty answer has every filled
    widget value placed, so none is left unplaced."""
    data = replayed_jobs[21]["extracted_data"]
    coverage = coverage_of(data)
    assert coverage[names.UNPLACED_WIDGET_VALUES_FIELD] == []
    assert data["extracted_fields"]
    assert "10535" in data["extracted_fields"].values()
    assert "SETH W. WIGGINS" in data["extracted_fields"].values()


@pytest.mark.parametrize(
    "slot,page_text,raw_field,expected_fragment",
    [
        ("Payer Name", ["Payer Name"], {"value": "", "source": "Payer Name"},
         "quoted this label"),
        ("Total Withdrawals", ["Total Withdrawals $10,309.62"],
         {"value": "", "source": ""}, "10,309.62"),
    ],
)
def test_evidence_behind_an_empty_slot_is_flagged(
    slot, page_text, raw_field, expected_fragment
):
    import source_inventory as inventory

    lines = [words(1, page_text)]
    slots = {"fields": [{"slot_id": "F1", "ref": "B1", "row_label": slot}],
             "tables": []}
    coverage = inventory.coverage(
        inventory.build(lines, [1]), slots, {}, {}, {"F1": raw_field}, lines, [1]
    )
    assert expected_fragment in coverage[names.FLAG_SLOTS_FIELD]["B1"]
    assert coverage[names.REASONS_FIELD] or "quoted this label" in expected_fragment


@pytest.mark.parametrize("slot", ["GL Account", "PO Number"])
def test_a_truly_absent_slot_is_not_false_flagged(slot):
    import source_inventory as inventory

    lines = [words(1, ["A document that does not print the requested label"])]
    slots = {"fields": [{"slot_id": "F1", "ref": "B1", "row_label": slot}],
             "tables": []}
    coverage = inventory.coverage(
        inventory.build(lines, [1]), slots, {}, {},
        {"F1": {"value": "", "source": ""}}, lines, [1]
    )
    assert coverage[names.FLAG_SLOTS_FIELD] == {}
    assert slot in coverage[names.ABSENT_FIELD]


def test_mark_reviewed_returns_409_while_attention_reasons_are_open(
    client, auth, run_a_http_doc
):
    job, document = run_a_http_doc
    route = names.REVIEW_ROUTE.format(job_id=job.id, doc_id=document.id)
    response = client.post(route, headers=auth["acme"], json={"scope": "document"})
    assert response.status_code == 409
    assert {item["id"] for item in response.json()["detail"]["open"]} == {"att-1", "att-2"}
    assert _stored(client, auth, job.id).get("review") is None


def test_each_open_reason_must_be_dispositioned_explicitly(
    client, auth, run_a_http_doc
):
    job, document = run_a_http_doc
    route = names.REVIEW_ROUTE.format(job_id=job.id, doc_id=document.id)
    response = client.post(route, headers=auth["acme"], json={
        "scope": "document",
        "dispositions": [{"id": "att-1", "choice": names.DISPOSITION_ENTERED_MANUALLY}],
    })
    assert response.status_code == 409
    # A refused request is atomic: even its one supplied disposition is not stored.
    assert all(item["disposition"] is None for item in _stored(client, auth, job.id)["attention"])


def test_dispositions_are_stored_without_deleting_the_original_reasons(
    client, auth, run_a_http_doc
):
    job, document = run_a_http_doc
    route = names.REVIEW_ROUTE.format(job_id=job.id, doc_id=document.id)
    response = client.post(route, headers=auth["acme"], json={
        "dispositions": [
            {"id": "att-1", "choice": names.DISPOSITION_ENTERED_MANUALLY},
            {"id": "att-2", "choice": names.DISPOSITION_CONFIRMED_ABSENT},
        ],
    })
    assert response.status_code == 200, response.text
    attention = _stored(client, auth, job.id)["attention"]
    assert [item["id"] for item in attention] == ["att-1", "att-2"]
    assert [item["disposition"]["choice"] for item in attention] == [
        names.DISPOSITION_ENTERED_MANUALLY,
        names.DISPOSITION_CONFIRMED_ABSENT,
    ]
    listing = client.get(f"/api/jobs/{job.id}/review", headers=auth["acme"]).json()
    assert listing["summary"]["attention_open"] == 0
    assert len(listing["documents"][0]["attention"]) == 2


def test_unsettled_export_name_and_first_legend_line_say_draft(
    client, auth, run_a_http_doc
):
    job, _document = run_a_http_doc
    response = client.get(names.DOWNLOAD_ROUTE.format(job_id=job.id), headers=auth["acme"])
    assert response.status_code == 200, response.text
    assert f"job_{job.id}_results_DRAFT.xlsx" in response.headers["content-disposition"]
    workbook = load_workbook(io.BytesIO(response.content))
    first_line = str(workbook["Legend"]["A1"].value)
    print(f"draft export={response.headers['content-disposition']} legend={first_line}")
    assert first_line.startswith("DRAFT")
    assert "2 completeness reasons open" in first_line


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


def test_edits_survive_reload_review_and_export(client, auth, run_a_http_doc):
    job, document = run_a_http_doc
    field_route = names.FIELD_EDIT_ROUTE.format(job_id=job.id, doc_id=document.id, ref="B1")
    cell_route = names.CELL_EDIT_ROUTE.format(
        job_id=job.id, doc_id=document.id, table="table", row=0
    )
    assert client.patch(field_route, headers=auth["acme"], json={"value": "HUMAN BANK"}).status_code == 200
    assert client.patch(
        cell_route, headers=auth["acme"], json={"column": "Amount", "value": "1,300.00"}
    ).status_code == 200

    review_route = names.REVIEW_ROUTE.format(job_id=job.id, doc_id=document.id)
    accepted = client.post(review_route, headers=auth["acme"], json={
        "scope": "document",
        "dispositions": [
            {"id": "att-1", "choice": names.DISPOSITION_ENTERED_MANUALLY},
            {"id": "att-2", "choice": names.DISPOSITION_CONFIRMED_ABSENT},
        ],
    })
    assert accepted.status_code == 200, accepted.text

    reloaded = _stored(client, auth, job.id)
    assert reloaded["extracted_fields"]["B1"] == "HUMAN BANK"
    assert reloaded["field_provenance"]["B1"]["original_value"] == "Lakeshore Bank"
    assert reloaded["table_rows"][0]["Amount"] == "1,300.00"
    assert reloaded["table_rows"][0]["_original"]["Amount"] == "1,254.00"
    assert [(event["kind"], event["old"], event["new"]) for event in reloaded["edit_log"]] == [
        ("field", "Lakeshore Bank", "HUMAN BANK"),
        ("cell", "1,254.00", "1,300.00"),
    ]

    downloaded = client.get(names.DOWNLOAD_ROUTE.format(job_id=job.id), headers=auth["acme"])
    assert downloaded.status_code == 200, downloaded.text
    workbook = load_workbook(io.BytesIO(downloaded.content))
    text = " ".join(
        str(cell.value)
        for sheet in workbook
        for row in sheet.iter_rows()
        for cell in row
        if cell.value is not None
    ).replace(",", "")
    assert "HUMAN BANK" in text
    assert "1300" in text
    assert workbook["Results"]["B1"].value == "HUMAN BANK"
    assert float(workbook["Results"]["B6"].value) == 1300.0


def test_failed_save_is_visible_to_the_reviewer(repo_dir):
    panel = (repo_dir / "frontend" / "components" / "extract" / "ReviewPanel.tsx").read_text(
        encoding="utf-8"
    )
    assert 'toast.error(`Not saved: ${detailText(e, "Save failed")}`)' in panel
