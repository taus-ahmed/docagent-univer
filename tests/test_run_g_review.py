"""Run G (G4): pins beside tests/test_review_flow_spec.py — the stricter
choices the spec leaves open. Local database, no provider."""
from __future__ import annotations

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
    _review,
    _stored,
    review_case_factory,
)


def _add(client, case, body):
    return client.post(f"/api/jobs/{case.job_id}/docs/{case.doc_id}/rows/items",
                       headers=case.headers, json=body)


def test_a_table_disposition_must_name_its_column(client, review_case_factory):
    case = review_case_factory(open_refs=(), flag_empty=False, table_open=True)
    r = _review(client, case, {"values": [
        {"table": "items", "row": 0, "disposition": "accepted_as_is"}]})
    assert r.status_code == 422


def test_a_row_id_that_disagrees_with_the_row_number_is_a_conflict(client, db,
                                                                   review_case_factory):
    case = review_case_factory(open_refs=(), flag_empty=False, table_open=True)
    r = _review(client, case, {"values": [
        {"table": "items", "row": 3, "row_id": "row-1", "column": "Amount",
         "disposition": "accepted_as_is"}]})
    assert r.status_code == 409
    assert "_reviewed_cells" not in _stored(db, case)["items_rows"][0]


def test_unknown_disposition_and_correction_without_value_are_refused(client,
                                                                      review_case_factory):
    case = review_case_factory()
    assert _review(client, case, {"values": [
        {"ref": "B2", "disposition": "looks_fine"}]}).status_code == 422
    assert _review(client, case, {"values": [
        {"ref": "B2", "disposition": "corrected"}]}).status_code == 422


def test_a_corrected_table_cell_is_edited_accepted_and_logged(client, db,
                                                              review_case_factory):
    case = review_case_factory(open_refs=(), flag_empty=False, table_open=True)
    r = _review(client, case, {"values": [
        {"table": "items", "row_id": "row-1", "column": "Amount",
         "disposition": "corrected", "value": "11.00"}]})
    assert r.status_code == 200, r.text
    row = _stored(db, case)["items_rows"][0]
    assert row["Amount"] == "11.00" and "Amount" in row["_edited"]
    assert row["_reviewed_cells"]["Amount"]["disposition"] == "corrected"
    ev = [e for e in _stored(db, case)["edit_log"] if e.get("column") == "Amount"]
    assert ev and ev[-1]["old"] == "10.00" and ev[-1]["new"] == "11.00"


def test_add_row_refuses_an_unknown_column_and_an_unknown_reason(client, db,
                                                                 review_case_factory):
    case = review_case_factory(open_refs=(), flag_empty=False, table_open=False)
    assert _add(client, case, {"values": {"Colour": "red"}}).status_code == 422
    assert _add(client, case, {"values": {"Description": ""}}).status_code == 422
    assert _add(client, case, {"values": {"Description": "x"},
                               "attention_id": "nope"}).status_code == 404
    assert len(_stored(db, case)["items_rows"]) == 1


def test_a_total_that_still_matches_is_not_reflagged_and_is_never_rewritten(
        client, db, review_case_factory):
    case = review_case_factory(open_refs=(), flag_empty=False, table_open=False)
    r = _add(client, case, {"values": {"Description": "Free item", "Amount": "0.00"}})
    assert r.status_code == 201, r.text
    assert r.json()["reflagged_totals"] == []
    r = _add(client, case, {"values": {"Description": "Paid item", "Amount": "2.50"}})
    assert r.json()["reflagged_totals"] == ["B4"]
    stored = _stored(db, case)
    assert stored["extracted_fields"]["B4"] == "10.00"          # not recomputed
    assert stored["field_provenance"]["B4"]["review_required"] is True
    assert len({row["_row_id"] for row in stored["items_rows"]}) == 3


def test_one_edit_does_not_settle_a_document_with_other_open_values(client, db,
                                                                     review_case_factory):
    from app.models.models import DocumentResult
    case = review_case_factory(open_refs=("B2", "B4"), flag_empty=False, table_open=False)
    r = client.patch(f"/api/jobs/{case.job_id}/docs/{case.doc_id}/fields/B2",
                     headers=case.headers, json={"value": "Typed"})
    assert r.status_code == 200
    db.expire_all()
    doc = db.get(DocumentResult, case.doc_id)
    assert doc.needs_review and not doc.reviewed           # B4 is still owed a look
    assert client.post(f"/api/jobs/{case.job_id}/docs/{case.doc_id}/approve",
                       headers=case.headers).status_code == 409
    assert _review(client, case, {"values": [
        {"ref": "B4", "disposition": "accepted_as_is"}]}).status_code == 200
    assert client.post(f"/api/jobs/{case.job_id}/docs/{case.doc_id}/approve",
                       headers=case.headers).status_code == 200
    db.expire_all()
    doc = db.get(DocumentResult, case.doc_id)
    assert doc.reviewed and not doc.needs_review
    assert doc.get_extracted_data()["review"]["document_reviewed"] is True


def test_add_row_settles_the_named_reason_and_shows_in_history(client, db,
                                                               review_case_factory):
    case = review_case_factory(
        open_refs=(), flag_empty=False, table_open=False,
        attention=[{"id": "att-1", "text": "A printed row is missing", "disposition": None}])
    r = _add(client, case, {"values": {"Description": "Added", "Amount": "0.00"},
                            "attention_id": "att-1"})
    assert r.status_code == 201, r.text
    att = _stored(db, case)["attention"][0]["disposition"]
    assert att["choice"] == "entered_manually" and att["by"] == case.actor
    h = client.get(f"/api/jobs/{case.job_id}/docs/{case.doc_id}/history",
                   headers=case.headers).json()["events"]
    assert [e["kind"] for e in h] == ["add_row", "attention"]
