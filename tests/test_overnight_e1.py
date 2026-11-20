"""E1 — an edit made in the review dialog persists: in the stored result, in
GET /results (what the screen re-reads after every action), and in the Excel.

Job 52 (irs_1099int_mod3): the owner edited "Form Type", which carried an
ambiguity note ("printed in 2 places on this page; showing the one nearest
its label") and an open completeness reason; the screen and the download
showed the original. The API persisted the edit (Codex, RUN_G_REVIEW); the
revert was stale frontend state — fixed in frontend/lib/reviewRefresh.ts and
pinned by frontend/lib/reviewRefresh.test.ts. These tests pin the server
half of the contract for both paths: a plain edit, and correct-and-accept.
"""

from __future__ import annotations

import io
import json

import openpyxl
import pytest

from tests.http.conftest import (  # noqa: F401  (fixtures)
    _db_url, _scratch_storage, app, auth, client, db, users,
)
from tests.test_review_flow_spec import (  # noqa: F401  (fixtures)
    _export, _review, _stored, review_case_factory,
)

AMBIGUITY = "printed in 2 places on this page; showing the one nearest its label"


@pytest.fixture
def form_type_case(db, review_case_factory):
    """Job 52's shape: Form Type (B2) with an ambiguity note in its
    provenance and an open completeness reason on the document."""
    from app.models.models import DocumentResult

    case = review_case_factory(open_refs=("B2",), flag_empty=False, table_open=False,
                               attention=[{"id": "a1", "text": "11 of 18 field slots "
                                           "are empty while the labels of 7 of them "
                                           "are printed on the page.",
                                           "disposition": None}])
    doc = db.get(DocumentResult, case.doc_id)
    ed = doc.get_extracted_data()
    ed["extracted_fields"]["B2"] = "1099-INT copy B"
    ed["slot_map"]["fields"][0]["row_label"] = "Form Type"
    ed["extracted_data"] = {"Form Type": {"value": "1099-INT copy B",
                                          "confidence": "low", "ref": "B2"}}
    ed["field_provenance"]["B2"].update(source="Form 1099-INT", note=AMBIGUITY)
    doc.set_extracted_data(ed)
    db.commit()
    return case


def _results_value(client, case):
    r = client.get(f"/api/jobs/{case.job_id}/results", headers=case.headers)
    assert r.status_code == 200, r.text
    doc = next(d for d in r.json() if d["id"] == case.doc_id)
    data = doc["extracted_data"]
    return data["extracted_fields"]["B2"], data["extracted_data"]["Form Type"]["value"]


def _exported(client, case):
    r = _export(client, case)
    assert r.status_code == 200, r.text[:300]
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    return [c.value for ws in wb.worksheets if ws.title != "Legend"
            for row in ws.iter_rows() for c in row]


def test_a_plain_edit_persists_in_results_and_in_the_excel(client, db, form_type_case):
    case = form_type_case
    r = client.patch(f"/api/jobs/{case.job_id}/docs/{case.doc_id}/fields/B2",
                     headers=case.headers, json={"value": "1099-INT"})
    assert r.status_code == 200, r.text
    assert _stored(db, case)["extracted_fields"]["B2"] == "1099-INT"
    assert _results_value(client, case) == ("1099-INT", "1099-INT")
    cells = _exported(client, case)
    assert "1099-INT" in cells and "1099-INT copy B" not in cells


def test_correct_and_accept_persists_in_results_and_in_the_excel(client, db, form_type_case):
    case = form_type_case
    r = _review(client, case, {"values": [
        {"ref": "B2", "disposition": "corrected", "value": "1099-INT"}]})
    assert r.status_code == 200, r.text
    stored = _stored(db, case)
    assert stored["extracted_fields"]["B2"] == "1099-INT"
    assert stored["field_provenance"]["B2"]["reviewed"]["disposition"] == "corrected"
    assert _results_value(client, case) == ("1099-INT", "1099-INT")
    cells = _exported(client, case)
    assert "1099-INT" in cells and "1099-INT copy B" not in cells


def test_a_second_read_after_the_edit_does_not_revert_it(client, db, form_type_case):
    """Reading the results twice (what a refetch does) must not re-ground or
    re-normalise the value back to the machine's."""
    case = form_type_case
    client.patch(f"/api/jobs/{case.job_id}/docs/{case.doc_id}/fields/B2",
                 headers=case.headers, json={"value": "1099-INT"})
    assert _results_value(client, case) == ("1099-INT", "1099-INT")
    assert _results_value(client, case) == ("1099-INT", "1099-INT")
    assert json.dumps(_stored(db, case)).count("1099-INT copy B") <= 2   # history only
