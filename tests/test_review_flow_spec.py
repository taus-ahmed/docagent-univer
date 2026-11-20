"""Target review/edit behavior, pinned at the HTTP and exported-XLSX level.

The API contract chosen here extends the existing document review endpoint:

* ``values[]`` entries carry ``disposition`` and a field ``ref`` or a table
  ``row``/``row_id`` plus ``column``; ``corrected`` also carries ``value``.
* ``POST .../rows/{table}`` adds a row and returns its stable ``row_id``.
* ``GET .../history`` returns the append-only value/row history.

Every rule is a strict xfail while today's application lacks the behavior.  An
implementation that satisfies a rule XPASSes and therefore forces removal of
both the marker and its row in tests/KNOWN_FAILING.md.
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


RULE_1 = pytest.mark.xfail(
    strict=True,
    reason="REVIEW RULE 1 -- explicit accepted_as_is/corrected/confirmed_empty states and log events",
)
RULE_2 = pytest.mark.xfail(
    strict=True,
    reason="REVIEW RULE 2 -- correct-and-accept must be one atomic operation",
)
RULE_3 = pytest.mark.xfail(
    strict=True,
    reason="REVIEW RULE 3 -- accepting a table cell must not accept its row",
)
RULE_4 = pytest.mark.xfail(
    strict=True,
    reason="REVIEW RULE 4 -- confirmed_empty permanently clears one flagged slot and its export mark",
)
RULE_5 = pytest.mark.xfail(
    strict=True,
    reason="REVIEW RULE 5 -- add-row needs a stable id, history, export placement, and total handling",
)
RULE_6 = pytest.mark.xfail(
    strict=True,
    reason="REVIEW RULE 6 -- relational review, JSON review, legacy approve, and DRAFT must share one state",
)
RULE_7 = pytest.mark.xfail(
    strict=True,
    reason="REVIEW RULE 7 -- a document history read endpoint must expose the edit log",
)
RULE_8 = pytest.mark.xfail(
    strict=True,
    reason="REVIEW RULE 8 -- re-downloaded Excel must contain final values without stale review warnings",
)


@pytest.fixture
def review_case_factory(db, users, auth):
    """Create a fresh, local-only completed job with addressable fields/rows."""
    from app.models.models import DocumentResult, ExtractionJob

    made: list[tuple[int, int]] = []

    def make(
        *,
        open_refs=("B2", "B3", "B4"),
        flag_empty=True,
        table_open=True,
        attention=None,
    ):
        open_refs_set = set(open_refs)
        attention = list(attention or [])
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

        fields = {"B2": "Machine value", "B3": "", "B4": "10.00"}
        labels = {"B2": "Account name", "B3": "Optional code", "B4": "Total"}
        provenance = {
            ref: {
                "source": value,
                "page": 1,
                "review_required": ref in open_refs_set or (ref == "B3" and flag_empty),
                "review_reasons": ["low_confidence"]
                if ref in open_refs_set or (ref == "B3" and flag_empty)
                else [],
            }
            for ref, value in fields.items()
        }
        confidence = {
            ref: "low"
            if ref in open_refs_set or (ref == "B3" and flag_empty)
            else "high"
            for ref in fields
        }
        row = {
            "_row_id": "row-1",
            "Description": "Existing item",
            "Amount": "10.00",
            "_confidence": "low" if table_open else "high",
            "_review_required": bool(table_open),
            "_review_reasons": ["low_confidence"] if table_open else [],
        }
        ed = {
            "template_type": "slot",
            "document_type": "invoice",
            "extracted_fields": fields,
            "extracted_data": {
                labels[ref]: {"value": value, "confidence": confidence[ref], "ref": ref}
                for ref, value in fields.items()
            },
            "field_provenance": provenance,
            "validation": {
                "confidence_map": confidence,
                "flagged_fields": ([{"ref": "B3", "reason": "expected value"}]
                                   if flag_empty else []),
            },
            "slot_map": {
                "fields": [{"ref": ref, "row_label": label} for ref, label in labels.items()],
                "tables": [{
                    "name": "items",
                    "columns": [
                        {"header": "Description", "key": "Description"},
                        {"header": "Amount", "key": "Amount"},
                    ],
                }],
            },
            "items_rows": [row],
            "attention": attention,
        }
        unresolved = bool(open_refs_set or flag_empty or table_open or attention)
        doc = DocumentResult(
            job_id=job.id,
            filename=f"review-spec-{job.id}.pdf",
            original_filename=f"review-spec-{job.id}.pdf",
            document_type="invoice",
            extraction_json=json.dumps(ed),
            overall_confidence="low" if unresolved else "high",
            needs_review=unresolved,
            reviewed=not unresolved,
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        made.append((job.id, doc.id))
        return SimpleNamespace(
            job_id=job.id,
            doc_id=doc.id,
            headers=auth["acme2"],
            actor=users["acme2"].username,
        )

    return make


def _stored(db, case):
    from app.models.models import DocumentResult

    db.expire_all()
    return db.get(DocumentResult, case.doc_id).get_extracted_data()


def _review(client, case, payload):
    return client.post(
        f"/api/jobs/{case.job_id}/docs/{case.doc_id}/review",
        headers=case.headers,
        json=payload,
    )


def _export(client, case):
    return client.get(f"/api/jobs/{case.job_id}/export", headers=case.headers)


def _workbook_text(workbook) -> str:
    return "\n".join(
        str(cell.value)
        for sheet in workbook.worksheets
        for row in sheet.iter_rows()
        for cell in row
        if cell.value is not None
    )


def _value_cell_below_header(workbook, header: str):
    """Return the exported result cell directly below a scalar-field header."""
    for sheet in workbook.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                if cell.value == header:
                    return sheet.cell(row=cell.row + 1, column=cell.column)
    raise AssertionError(f"No exported header {header!r}")


def test_explicit_dispositions_are_stored_per_value_and_logged(
    client, db, review_case_factory
):
    case = review_case_factory(table_open=False)
    response = _review(client, case, {"values": [
        {"ref": "B2", "disposition": "accepted_as_is"},
        {"ref": "B3", "disposition": "confirmed_empty"},
        {"ref": "B4", "disposition": "corrected", "value": "15.00"},
    ]})
    assert response.status_code == 200, response.text

    stored = _stored(db, case)
    expected = {
        "B2": "accepted_as_is",
        "B3": "confirmed_empty",
        "B4": "corrected",
    }
    for ref, disposition in expected.items():
        mark = stored["field_provenance"][ref]["reviewed"]
        assert mark["disposition"] == disposition
        assert mark["by"] == case.actor and mark["at"]

    for ref, disposition in expected.items():
        event = next(
            event for event in stored["edit_log"]
            if event.get("ref") == ref and event.get("disposition") == disposition
        )
        assert event["by"] == case.actor and event["at"]


def test_correct_and_accept_is_one_atomic_operation(client, db, review_case_factory):
    case = review_case_factory(open_refs=("B2",), flag_empty=False, table_open=False)
    response = _review(client, case, {"values": [
        {"ref": "B2", "disposition": "corrected", "value": "Human correction"},
    ]})
    assert response.status_code == 200, response.text

    stored = _stored(db, case)
    assert stored["extracted_fields"]["B2"] == "Human correction"
    assert stored["field_provenance"]["B2"]["reviewed"]["disposition"] == "corrected"
    event = next(event for event in stored["edit_log"] if event.get("ref") == "B2")
    assert event["old"] == "Machine value"
    assert event["new"] == "Human correction"
    assert event["disposition"] == "corrected"
    assert event["by"] == case.actor and event["at"]


def test_accepting_one_table_cell_marks_only_that_cell(client, db, review_case_factory):
    case = review_case_factory(open_refs=(), flag_empty=False, table_open=True)
    response = _review(client, case, {"values": [{
        "table": "items",
        "row": 0,
        "row_id": "row-1",
        "column": "Amount",
        "disposition": "accepted_as_is",
    }]})
    assert response.status_code == 200, response.text

    row = _stored(db, case)["items_rows"][0]
    assert set(row["_reviewed_cells"]) == {"Amount"}
    assert row["_reviewed_cells"]["Amount"]["disposition"] == "accepted_as_is"
    assert "_reviewed" not in row

    listing = client.get(f"/api/jobs/{case.job_id}/review", headers=case.headers).json()
    cells = {
        value["column"]: value
        for value in listing["documents"][0]["values"]
        if value.get("kind") == "cell" and value.get("row") == 0
    }
    assert cells["Amount"]["resolved"] is True
    assert cells["Description"]["resolved"] is False


def test_confirmed_empty_clears_the_flag_and_exports_a_clean_empty_slot(
    client, db, review_case_factory
):
    case = review_case_factory(open_refs=(), flag_empty=True, table_open=False)
    response = _review(client, case, {"values": [
        {"ref": "B3", "disposition": "confirmed_empty"},
    ]})
    assert response.status_code == 200, response.text

    stored = _stored(db, case)
    assert stored["extracted_fields"]["B3"] == ""
    assert stored["field_provenance"]["B3"]["reviewed"]["disposition"] == "confirmed_empty"
    assert not any(flag.get("ref") == "B3" for flag in stored["validation"]["flagged_fields"])

    downloaded = _export(client, case)
    assert downloaded.status_code == 200, downloaded.text
    assert "_DRAFT" not in downloaded.headers["content-disposition"]
    workbook = load_workbook(io.BytesIO(downloaded.content))
    value_cell = _value_cell_below_header(workbook, "Optional code")
    assert value_cell.value in (None, "")
    assert value_cell.fill.fill_type is None
    assert value_cell.comment is None
    comments = [
        cell.comment.text
        for sheet in workbook.worksheets
        for row in sheet.iter_rows()
        for cell in row
        if cell.comment
    ]
    assert not any("Optional code" in comment or "NEEDS REVIEW" in comment for comment in comments)


@RULE_5
def test_add_row_has_stable_identity_history_export_and_total_handling(
    client, db, review_case_factory
):
    case = review_case_factory(
        open_refs=(),
        flag_empty=False,
        table_open=False,
        attention=[{"id": "att-1", "text": "A printed row is missing", "disposition": None}],
    )
    response = client.post(
        f"/api/jobs/{case.job_id}/docs/{case.doc_id}/rows/items",
        headers=case.headers,
        json={
            "values": {"Description": "Added item", "Amount": "5.00"},
            "attention_id": "att-1",
        },
    )
    assert response.status_code == 201, response.text
    row_id = response.json()["row_id"]
    assert isinstance(row_id, str) and row_id

    stored = _stored(db, case)
    added = next(row for row in stored["items_rows"] if row.get("_row_id") == row_id)
    assert added["Description"] == "Added item" and added["Amount"] == "5.00"
    event = next(event for event in stored["edit_log"] if event.get("kind") == "add_row")
    assert event["row_id"] == row_id and event["by"] == case.actor and event["at"]

    total_recomputed = str(stored["extracted_fields"]["B4"]) in {"15", "15.0", "15.00"}
    total_reflagged = "total" in json.dumps({
        "attention": stored.get("attention"),
        "validation": stored.get("validation"),
    }).casefold()
    assert total_recomputed or total_reflagged

    downloaded = _export(client, case)
    workbook = load_workbook(io.BytesIO(downloaded.content))
    text = _workbook_text(workbook)
    assert "Added item" in text and "5.00" in text
    assert row_id == next(row["_row_id"] for row in _stored(db, case)["items_rows"]
                          if row["Description"] == "Added item")


@RULE_6
def test_one_review_state_controls_legacy_approve_and_draft(
    client, db, review_case_factory
):
    dirty = review_case_factory(open_refs=("B2",), flag_empty=False, table_open=False)
    incomplete = review_case_factory(
        open_refs=(),
        flag_empty=False,
        table_open=False,
        attention=[{"id": "att-open", "text": "Printed section is incomplete", "disposition": None}],
    )
    clean = review_case_factory(open_refs=(), flag_empty=False, table_open=False)

    dirty_export = _export(client, dirty)
    incomplete_export = _export(client, incomplete)
    clean_export = _export(client, clean)
    assert "_DRAFT" in dirty_export.headers["content-disposition"]
    assert "_DRAFT" in incomplete_export.headers["content-disposition"]
    assert "_DRAFT" not in clean_export.headers["content-disposition"]

    legacy = client.post(
        f"/api/jobs/{dirty.job_id}/docs/{dirty.doc_id}/approve",
        headers=dirty.headers,
    )
    assert legacy.status_code == 409

    accepted = _review(client, dirty, {"values": [
        {"ref": "B2", "disposition": "accepted_as_is"},
    ]})
    assert accepted.status_code == 200, accepted.text
    marked = _review(client, dirty, {"scope": "document"})
    assert marked.status_code == 200, marked.text
    legacy = client.post(
        f"/api/jobs/{dirty.job_id}/docs/{dirty.doc_id}/approve",
        headers=dirty.headers,
    )
    assert legacy.status_code == 200, legacy.text

    from app.models.models import DocumentResult

    db.expire_all()
    row = db.get(DocumentResult, dirty.doc_id)
    stored = row.get_extracted_data()
    listing = client.get(f"/api/jobs/{dirty.job_id}/review", headers=dirty.headers).json()
    assert row.reviewed and not row.needs_review
    assert stored["review"]["document_reviewed"] is True
    assert listing["documents"][0]["document_state"] == "READY"
    assert listing["documents"][0]["document_reviewed"] is True
    assert "_DRAFT" not in _export(client, dirty).headers["content-disposition"]


def test_document_history_endpoint_returns_who_when_old_new_and_target(
    client, review_case_factory
):
    case = review_case_factory(open_refs=("B2",), flag_empty=False, table_open=False)
    edited = client.patch(
        f"/api/jobs/{case.job_id}/docs/{case.doc_id}/fields/B2",
        headers=case.headers,
        json={"value": "History value"},
    )
    assert edited.status_code == 200, edited.text
    edited_cell = client.patch(
        f"/api/jobs/{case.job_id}/docs/{case.doc_id}/rows/items/0",
        headers=case.headers,
        json={"column": "Amount", "value": "12.00"},
    )
    assert edited_cell.status_code == 200, edited_cell.text

    response = client.get(
        f"/api/jobs/{case.job_id}/docs/{case.doc_id}/history",
        headers=case.headers,
    )
    assert response.status_code == 200, response.text
    event = next(item for item in response.json()["events"] if item.get("ref") == "B2")
    assert event["by"] == case.actor and event["at"]
    assert event["old"] == "Machine value" and event["new"] == "History value"
    assert event["kind"] == "field"
    cell_event = next(
        item for item in response.json()["events"]
        if item.get("table") == "items" and item.get("column") == "Amount"
    )
    assert cell_event["by"] == case.actor and cell_event["at"]
    assert cell_event["old"] == "10.00" and cell_event["new"] == "12.00"
    assert cell_event["kind"] == "cell"


def test_export_after_correction_and_empty_confirmation_has_no_stale_warning(
    client, review_case_factory
):
    case = review_case_factory(open_refs=("B2",), flag_empty=True, table_open=False)
    response = _review(client, case, {"values": [
        {"ref": "B2", "disposition": "corrected", "value": "Final account name"},
        {"ref": "B3", "disposition": "confirmed_empty"},
    ]})
    assert response.status_code == 200, response.text

    downloaded = _export(client, case)
    assert downloaded.status_code == 200, downloaded.text
    assert "_DRAFT" not in downloaded.headers["content-disposition"]
    workbook = load_workbook(io.BytesIO(downloaded.content))
    text = _workbook_text(workbook)
    assert "Final account name" in text
    assert "Machine value" not in text
    assert str(workbook["Legend"]["A1"].value) == "Nothing needs review"
    corrected_cell = _value_cell_below_header(workbook, "Account name")
    empty_cell = _value_cell_below_header(workbook, "Optional code")
    assert corrected_cell.comment is None
    assert empty_cell.value in (None, "") and empty_cell.comment is None
    assert empty_cell.fill.fill_type is None
    from app.core.review import EXPORT_FILLS

    warning_fills = {
        EXPORT_FILLS[name]
        for name in ("low", "unverified", "empty_flagged", "needs_review")
    }
    assert corrected_cell.fill.fgColor.rgb not in warning_fills
    comments = [
        cell.comment.text
        for sheet in workbook.worksheets
        for row in sheet.iter_rows()
        for cell in row
        if cell.comment
    ]
    assert not any(comment.startswith("NEEDS REVIEW") for comment in comments)
