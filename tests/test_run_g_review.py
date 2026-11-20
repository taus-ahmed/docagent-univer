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


def _template_case(db, users, auth):
    """A job exported through the TEMPLATE (slot) writer: B2 low, B3 empty and
    flagged, one table row owing review."""
    import json
    from types import SimpleNamespace
    from app.models.models import ColumnTemplate, DocumentResult, ExtractionJob
    grid = {"cells": {"1,0": {"value": "Account name"}, "2,0": {"value": "Optional code"},
                      "4,0": {"value": "Date"}, "4,1": {"value": "Amount"}},
            "merges": {}, "colWidths": [], "repeatRows": []}
    tpl = ColumnTemplate(name="run-g", document_type="invoice", description=json.dumps(grid),
                         columns_json="[]", client_id="acme_001")
    db.add(tpl); db.commit(); db.refresh(tpl)
    job = ExtractionJob(user_id=users["acme2"].id, client_id="acme_001", status="completed",
                        total_docs=1, successful=1, input_source="upload", schema_id=str(tpl.id))
    db.add(job); db.commit(); db.refresh(job)
    ed = {"template_type": "slot", "document_type": "invoice",
          "extracted_fields": {"B2": "Machine value", "B3": ""},
          "extracted_data": {"Account name": {"value": "Machine value", "confidence": "low", "ref": "B2"},
                             "Optional code": {"value": "", "confidence": "low", "ref": "B3"}},
          "field_provenance": {r: {"source": v, "page": 1, "review_required": True,
                                   "review_reasons": ["grounding_failed"]}
                               for r, v in (("B2", "Machine value"), ("B3", ""))},
          "validation": {"confidence_map": {"B2": "low", "B3": "low"},
                         "flagged_fields": [{"ref": "B3", "reason": "expected"}]},
          "slot_map": {"fields": [{"ref": "B2", "row_label": "Account name"},
                                  {"ref": "B3", "row_label": "Optional code"}],
                       "tables": [{"name": "table", "header_row": 4, "start_row": 5, "end_row": 10,
                                   "columns": [{"col": 0, "header": "Date", "key": "Date"},
                                               {"col": 1, "header": "Amount", "key": "Amount"}]}]},
          "table_rows": [{"_row_id": "row-1", "Date": "03/04/2026", "Amount": "10.00",
                          "_confidence": "low", "_review_required": True,
                          "_review_reasons": ["grounding_failed"], "_source": "x", "_page": 1}]}
    doc = DocumentResult(job_id=job.id, filename="g.pdf", original_filename="g.pdf",
                         document_type="invoice", extraction_json=json.dumps(ed),
                         needs_review=True)
    db.add(doc); db.commit(); db.refresh(doc)
    return SimpleNamespace(job_id=job.id, doc_id=doc.id, headers=auth["acme2"])


def test_the_template_export_honours_dispositions_and_cell_marks(client, db, users, auth):
    import io
    from openpyxl import load_workbook
    from app.core.review import EXPORT_FILLS
    case = _template_case(db, users, auth)
    r = _review(client, case, {"values": [
        {"ref": "B2", "disposition": "corrected", "value": "Final name"},
        {"ref": "B3", "disposition": "confirmed_empty"},
        {"table": "table", "row_id": "row-1", "column": "Amount", "disposition": "accepted_as_is"}]})
    assert r.status_code == 200, r.text
    x = client.get(f"/api/jobs/{case.job_id}/export", headers=case.headers)
    assert x.status_code == 200 and "_DRAFT" in x.headers["content-disposition"]   # Date still open
    ws = load_workbook(io.BytesIO(x.content))["Results"]
    warn = {EXPORT_FILLS[k] for k in ("low", "unverified", "empty_flagged", "needs_review")}
    b2, b3 = ws["B2"], ws["B3"]
    assert b2.value == "Final name" and b2.fill.fgColor.rgb == EXPORT_FILLS["edited"]
    assert not (b2.comment and b2.comment.text.startswith(("NEEDS REVIEW", "EDITED BY HAND")))
    assert b3.value in (None, "") and b3.fill.fill_type is None and b3.comment is None
    amount, date_ = ws["B6"], ws["A6"]
    assert amount.fill.fgColor.rgb not in warn                  # this cell was accepted
    assert date_.fill.fgColor.rgb in warn                       # its neighbour was not


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
