"""Adversarial API checks for Run G review dispositions.

These tests use the local SQLite HTTP fixture and generated workbooks only.
They make no model or remote-service calls.
"""
from __future__ import annotations

import io
import json
from types import SimpleNamespace

import pytest
from openpyxl import load_workbook

from tests.http.conftest import (  # noqa: F401
    _db_url,
    _scratch_storage,
    app,
    auth,
    client,
    db,
    users,
)
from tests.test_review_flow_spec import (  # noqa: F401
    _export,
    _review,
    _stored,
    _workbook_text,
    review_case_factory,
)


def _download(client, case):
    response = _export(client, case)
    assert response.status_code == 200, response.text
    return response, load_workbook(io.BytesIO(response.content))


def _assert_export_has(client, case, *needles, absent=()):
    response, workbook = _download(client, case)
    text = _workbook_text(workbook)
    for needle in needles:
        assert str(needle) in text
    for needle in absent:
        assert str(needle) not in text
    return response, workbook


def test_dispositions_in_odd_orders_survive_every_intermediate_export(
    client, db, review_case_factory
):
    case = review_case_factory(table_open=False)

    first = _review(client, case, {"values": [
        {"ref": "B4", "disposition": "corrected", "value": "15.00"},
    ]})
    assert first.status_code == 200, first.text
    response, _ = _assert_export_has(client, case, "15", absent=("10.00",))
    assert "_DRAFT" in response.headers["content-disposition"]

    second = _review(client, case, {"values": [
        {"ref": "B2", "disposition": "accepted_as_is"},
    ]})
    assert second.status_code == 200, second.text
    response, _ = _assert_export_has(client, case, "Machine value", "15")
    assert "_DRAFT" in response.headers["content-disposition"]

    third = _review(client, case, {"values": [
        {"ref": "B3", "disposition": "confirmed_empty"},
    ]})
    assert third.status_code == 200, third.text
    response, workbook = _assert_export_has(client, case, "Machine value", "15")
    assert "_DRAFT" not in response.headers["content-disposition"]
    assert workbook["Legend"]["A1"].value == "Nothing needs review"

    stored = _stored(db, case)
    assert [stored["field_provenance"][ref]["reviewed"]["disposition"]
            for ref in ("B4", "B2", "B3")] == [
                "corrected", "accepted_as_is", "confirmed_empty"]


def test_correct_then_confirm_empty_replaces_value_in_results_and_export(
    client, db, review_case_factory
):
    case = review_case_factory(open_refs=("B2",), flag_empty=False, table_open=False)
    corrected = _review(client, case, {"values": [
        {"ref": "B2", "disposition": "corrected", "value": "Transient correction"},
    ]})
    assert corrected.status_code == 200, corrected.text
    _assert_export_has(client, case, "Transient correction", absent=("Machine value",))

    emptied = _review(client, case, {"values": [
        {"ref": "B2", "disposition": "confirmed_empty"},
    ]})
    assert emptied.status_code == 200, emptied.text
    response, workbook = _assert_export_has(
        client, case, absent=("Transient correction", "Machine value")
    )
    assert "_DRAFT" not in response.headers["content-disposition"]
    assert workbook["Legend"]["A1"].value == "Nothing needs review"

    stored = _stored(db, case)
    assert stored["extracted_fields"]["B2"] == ""
    assert stored["extracted_data"]["Account name"]["value"] == ""
    assert stored["field_provenance"]["B2"]["reviewed"]["disposition"] == "confirmed_empty"


def test_table_cell_disposition_cannot_silently_accept_the_row(
    client, review_case_factory
):
    case = review_case_factory(open_refs=(), flag_empty=False, table_open=True)
    row_level = _review(client, case, {"values": [{
        "table": "items", "row": 0, "row_id": "row-1",
        "disposition": "accepted_as_is",
    }]})
    assert row_level.status_code == 422
    response, _ = _download(client, case)
    assert "_DRAFT" in response.headers["content-disposition"]

    amount = _review(client, case, {"values": [{
        "table": "items", "row": 0, "row_id": "row-1", "column": "Amount",
        "disposition": "accepted_as_is",
    }]})
    assert amount.status_code == 200, amount.text
    listing = client.get(f"/api/jobs/{case.job_id}/review", headers=case.headers).json()
    cells = {value["column"]: value for value in listing["documents"][0]["values"]
             if value.get("kind") == "cell" and value.get("row_id") == "row-1"}
    assert cells["Amount"]["resolved"] is True
    assert cells["Description"]["resolved"] is False
    response, _ = _assert_export_has(client, case, "Existing item", "10")
    assert "_DRAFT" in response.headers["content-disposition"]


def test_add_row_keeps_declared_total_then_reflags_until_a_human_corrects_it(
    client, db, review_case_factory
):
    case = review_case_factory(open_refs=(), flag_empty=False, table_open=False)
    added = client.post(
        f"/api/jobs/{case.job_id}/docs/{case.doc_id}/rows/items",
        headers=case.headers,
        json={"values": {"Description": "Second item", "Amount": "5.00"}},
    )
    assert added.status_code == 201, added.text
    assert added.json()["reflagged_totals"] == ["B4"]
    response, _ = _assert_export_has(client, case, "Second item", "5", "10")
    assert "_DRAFT" in response.headers["content-disposition"]
    assert _stored(db, case)["extracted_fields"]["B4"] == "10.00"

    corrected = _review(client, case, {"values": [
        {"ref": "B4", "disposition": "corrected", "value": "15.00"},
    ]})
    assert corrected.status_code == 200, corrected.text
    response, workbook = _assert_export_has(
        client, case, "Second item", "5", "15", absent=("10.00",)
    )
    assert "_DRAFT" not in response.headers["content-disposition"]
    assert workbook["Legend"]["A1"].value == "Nothing needs review"


def test_approve_refuses_both_unresolved_values_and_open_completeness(
    client, review_case_factory
):
    value_case = review_case_factory(
        open_refs=("B2",), flag_empty=False, table_open=False
    )
    attention_case = review_case_factory(
        open_refs=(), flag_empty=False, table_open=False,
        attention=[{"id": "missing-row", "text": "One printed row is missing",
                    "disposition": None}],
    )
    for case in (value_case, attention_case):
        approved = client.post(
            f"/api/jobs/{case.job_id}/docs/{case.doc_id}/approve",
            headers=case.headers,
        )
        assert approved.status_code == 409, approved.text
        response, _ = _download(client, case)
        assert "_DRAFT" in response.headers["content-disposition"]


def test_history_is_oldest_first_and_complete_for_every_action(
    client, review_case_factory
):
    case = review_case_factory(
        open_refs=("B2",), flag_empty=False, table_open=False,
        attention=[{"id": "missed-row", "text": "A printed row was missed",
                    "disposition": None}],
    )
    assert _review(client, case, {"values": [
        {"ref": "B2", "disposition": "corrected", "value": "History correction"},
    ]}).status_code == 200
    added = client.post(
        f"/api/jobs/{case.job_id}/docs/{case.doc_id}/rows/items",
        headers=case.headers,
        json={"values": {"Description": "History row", "Amount": "5.00"},
              "attention_id": "missed-row"},
    )
    assert added.status_code == 201, added.text
    assert _review(client, case, {"values": [
        {"ref": "B4", "disposition": "corrected", "value": "15.00"},
    ]}).status_code == 200
    assert _review(client, case, {"scope": "document"}).status_code == 200

    history = client.get(
        f"/api/jobs/{case.job_id}/docs/{case.doc_id}/history",
        headers=case.headers,
    )
    assert history.status_code == 200, history.text
    events = history.json()["events"]
    assert [event.get("at") for event in events] == sorted(event.get("at") for event in events)
    assert {(event.get("kind"), event.get("ref")) for event in events} >= {
        ("field", "B2"), ("field", "B4")}
    assert any(event.get("kind") == "add_row" and event.get("row_id") == added.json()["row_id"]
               for event in events)
    assert any(event.get("kind") == "attention" and event.get("attention_id") == "missed-row"
               for event in events)
    assert events[-1]["kind"] == "document"
    assert all(event.get("by") == case.actor and event.get("at") for event in events)
    response, _ = _assert_export_has(client, case, "History correction", "History row", "15")
    assert "_DRAFT" not in response.headers["content-disposition"]


def test_other_tenant_cannot_read_or_mutate_any_review_route(
    client, auth, review_case_factory
):
    case = review_case_factory(open_refs=("B2",), flag_empty=False, table_open=False)
    owner_listing = client.get(f"/api/jobs/{case.job_id}/review", headers=case.headers)
    assert owner_listing.status_code == 200

    routes = [
        ("get", f"/api/jobs/{case.job_id}/review", None),
        ("post", f"/api/jobs/{case.job_id}/docs/{case.doc_id}/review",
         {"values": [{"ref": "B2", "disposition": "accepted_as_is"}]}),
        ("post", f"/api/jobs/{case.job_id}/docs/{case.doc_id}/rows/items",
         {"values": {"Description": "Intruder", "Amount": "1.00"}}),
        ("get", f"/api/jobs/{case.job_id}/docs/{case.doc_id}/history", None),
        ("post", f"/api/jobs/{case.job_id}/docs/{case.doc_id}/approve", None),
        ("get", f"/api/jobs/{case.job_id}/export", None),
    ]
    for method, url, payload in routes:
        kwargs = {"headers": auth["other"]}
        if payload is not None:
            kwargs["json"] = payload
        response = getattr(client, method)(url, **kwargs)
        assert response.status_code == 404, (method, url, response.text)

    owner_export, _ = _download(client, case)
    assert "_DRAFT" in owner_export.headers["content-disposition"]


@pytest.fixture
def owner_1099_case(db, users, auth):
    """The owner's fillable 1099-INT state, reduced to the affected slot."""
    from app.models.models import DocumentResult, ExtractionJob

    job = ExtractionJob(
        user_id=users["acme2"].id,
        client_id="acme_001",
        status="completed",
        total_docs=1,
        successful=1,
        needs_review=1,
        input_source="upload",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    ed = {
        "template_type": "slot",
        "document_type": "irs_1099int",
        "extracted_fields": {"B1": "1099-INT"},
        "extracted_data": {
            "Form Type": {"value": "1099-INT", "confidence": "low", "ref": "B1"}
        },
        "field_provenance": {
            "B1": {
                "source": "Form 1099-INT",
                "page": 1,
                "review_required": True,
                "review_reasons": ["grounding_failed"],
                "location_note": (
                    "ambiguous: printed in 2 places on this page; showing the one "
                    "nearest its label"
                ),
            }
        },
        "validation": {
            "confidence_map": {"B1": "low"},
            "flagged_fields": [{"ref": "B1", "reason": "ambiguous source"}],
        },
        "slot_map": {
            "fields": [{"ref": "B1", "row_label": "Form Type"}],
            "tables": [],
        },
        "attention": [{
            "id": "missing-form-slots",
            "text": "11 of 18 field slots are empty while labels are printed",
            "disposition": None,
        }],
    }
    doc = DocumentResult(
        job_id=job.id,
        filename="irs_1099int_mod3.pdf",
        original_filename="irs_1099int_mod3.pdf",
        document_type="irs_1099int",
        extraction_json=json.dumps(ed),
        overall_confidence="low",
        needs_review=True,
        reviewed=False,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return SimpleNamespace(
        job_id=job.id,
        doc_id=doc.id,
        headers=auth["acme2"],
        actor=users["acme2"].username,
    )


def test_owner_1099_form_type_edit_persists_in_results_and_download(
    client, owner_1099_case
):
    """OWNER REVERT: the edited ambiguous slot must not fall back to model text."""
    case = owner_1099_case
    edited_value = "1099-INT (human corrected)"
    # This is the exact request made by Review -> Correct -> Save and accept
    # for an unresolved field, not the ordinary edit route for a clean value.
    edited = client.post(
        f"/api/jobs/{case.job_id}/docs/{case.doc_id}/review",
        headers=case.headers,
        json={"values": [{
            "ref": "B1", "disposition": "corrected", "value": edited_value,
        }]},
    )
    assert edited.status_code == 200, edited.text

    results = client.get(f"/api/jobs/{case.job_id}/results", headers=case.headers)
    assert results.status_code == 200, results.text
    result = next(item for item in results.json() if item["id"] == case.doc_id)
    stored = result["extracted_data"]
    assert stored["extracted_fields"]["B1"] == edited_value
    assert stored["extracted_data"]["Form Type"]["value"] == edited_value

    response, workbook = _download(client, case)
    text = _workbook_text(workbook)
    assert edited_value in text
    assert "1099-INT\n" not in text
    assert "_DRAFT" in response.headers["content-disposition"]
