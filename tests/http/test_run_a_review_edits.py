"""Run A through the real routes:

  A4  the jobs API states each document's state and the page ledger
  A5  "mark document reviewed" and "approve" are refused while a completeness
      reason is open; a disposition per reason settles it; the export of an
      unsettled document is a DRAFT (file name + first Legend line)
  A6  a header edit and a table-cell edit both survive a reload and reach the
      downloaded file; a stale whole-document save no longer undoes a review
      mark; every edit is an append-only event keeping the machine's value
"""
from __future__ import annotations

import io
import json

import pytest
from openpyxl import load_workbook


def _ed(attention=True):
    ed = {
        "document_type": "bank_statement", "template_type": "slot",
        "extraction_method": "slot_directed",
        "extracted_fields": {"B1": "Lakeshore Bank", "B2": "$20,376.00"},
        "extracted_data": {"Bank Name": {"value": "Lakeshore Bank", "confidence": "high", "ref": "B1"},
                           "Closing Balance": {"value": "$20,376.00", "confidence": "high", "ref": "B2"}},
        "field_provenance": {r: {"source": v, "page": 1, "grounded": True,
                                 "review_required": False, "review_reasons": []}
                             for r, v in (("B1", "Lakeshore Bank"), ("B2", "$20,376.00"))},
        "slot_map": {"fields": [{"slot_id": "F1", "ref": "B1", "row_label": "Bank Name", "section": ""},
                                {"slot_id": "F2", "ref": "B2", "row_label": "Closing Balance", "section": ""},
                                {"slot_id": "F3", "ref": "B3", "row_label": "Total Deposits", "section": ""}],
                     "tables": [{"name": "table", "header_row": 4, "start_row": 5, "end_row": 20,
                                 "columns": [{"col": 0, "header": "Date", "key": "Date"},
                                             {"col": 1, "header": "Amount", "key": "Amount"}]}]},
        "table_rows": [{"Date": "09/02/2026", "Amount": "1,254.00", "_confidence": "high",
                        "_source": "09/02/2026 ACH 1,254.00", "_page": 1},
                       {"Date": "09/03/2026", "Amount": "4,980.00", "_confidence": "high",
                        "_source": "09/03/2026 ACH 4,980.00", "_page": 1}],
        "validation": {"confidence_map": {"B1": "high", "B2": "high"},
                       "flagged_fields": [{"ref": "Total Deposits", "value": "",
                                           "reason": "empty_flagged: amount $12,445.50 printed near this label"}]},
        "needs_review": True,
        "diagnostics": {"pages": {"1": "processed", "2": "failed"}},
        "attention": ([{"id": "att-1", "disposition": None,
                        "text": "Amount $12,445.50 appears on page 1 next to \"Total Deposits\" but is not in any cell."},
                       {"id": "att-2", "disposition": None,
                        "text": "Page 2 could not be read (OCR found no words), so nothing on it was extracted."}]
                      if attention else []),
    }
    return ed


@pytest.fixture
def doc(db, users):
    from app.models.models import ColumnTemplate, DocumentResult, ExtractionJob
    grid = {"cells": {"0,0": {"value": "Bank Name"}, "1,0": {"value": "Closing Balance"},
                      "2,0": {"value": "Total Deposits"},
                      "4,0": {"value": "Date"}, "4,1": {"value": "Amount"}},
            "merges": {}, "colWidths": [], "repeatRows": []}
    tpl = ColumnTemplate(name="run-a-bank", document_type="bank_statement",
                         description=json.dumps(grid), columns_json="[]",
                         client_id="acme_001")
    db.add(tpl); db.commit(); db.refresh(tpl)
    j = ExtractionJob(user_id=users["acme"].id, client_id="acme_001", status="completed",
                      total_docs=1, successful=1, input_source="upload",
                      schema_id=str(tpl.id))
    db.add(j); db.commit(); db.refresh(j)
    d = DocumentResult(job_id=j.id, filename="stmt.pdf", original_filename="stmt.pdf",
                       document_type="bank_statement", overall_confidence="high",
                       needs_review=True, extraction_json=json.dumps(_ed()))
    db.add(d); db.commit(); db.refresh(d)
    return j, d


def _stored(client, auth, job_id):
    r = client.get(f"/api/jobs/{job_id}/results", headers=auth["acme"])
    assert r.status_code == 200, r.text
    return r.json()[0]["extracted_data"]


class TestJobStates:
    def test_the_job_says_it_needs_attention_and_names_the_failed_page(self, client, auth, doc):
        j, _d = doc
        r = client.get(f"/api/jobs/{j.id}", headers=auth["acme"]).json()
        assert r["status"] == "completed"
        assert r["needs_attention"] == 1
        assert r["document_states"]["NEEDS_ATTENTION"] == 1
        assert (r["pages_processed"], r["pages_total"]) == (1, 2)
        assert r["pages_failed"] == ["stmt.pdf p.2"]
        listed = client.get("/api/jobs", headers=auth["acme"]).json()
        assert next(x for x in listed if x["id"] == j.id)["needs_attention"] == 1

    def test_the_review_listing_carries_the_reasons(self, client, auth, doc):
        j, _d = doc
        r = client.get(f"/api/jobs/{j.id}/review", headers=auth["acme"]).json()
        d = r["documents"][0]
        assert d["document_state"] == "NEEDS_ATTENTION"
        assert [a["id"] for a in d["attention"]] == ["att-1", "att-2"]
        assert r["summary"]["documents_needing_attention"] == 1
        assert r["summary"]["attention_open"] == 2
        assert any(v["status"] == "empty_flagged" for v in d["values"])


class TestReviewCannotEraseAMissingSection:
    def test_mark_document_reviewed_is_refused_while_reasons_are_open(self, client, auth, doc):
        j, d = doc
        r = client.post(f"/api/jobs/{j.id}/docs/{d.id}/review", headers=auth["acme"],
                        json={"scope": "document"})
        assert r.status_code == 409
        assert len(r.json()["detail"]["open"]) == 2
        assert _stored(client, auth, j.id).get("review") is None

    def test_approve_is_refused_too(self, client, auth, doc):
        j, d = doc
        r = client.post(f"/api/jobs/{j.id}/docs/{d.id}/approve", headers=auth["acme"])
        assert r.status_code == 409

    def test_a_partial_disposition_still_blocks(self, client, auth, doc):
        j, d = doc
        r = client.post(f"/api/jobs/{j.id}/docs/{d.id}/review", headers=auth["acme"],
                        json={"scope": "document", "dispositions": [
                            {"id": "att-1", "choice": "entered_manually"}]})
        assert r.status_code == 409
        # the disposition given is NOT stored by a refused request
        att = _stored(client, auth, j.id)["attention"]
        assert att[0]["disposition"] is None

    def test_each_reason_dispositioned_then_reviewed(self, client, auth, doc, db):
        from app.models.models import DocumentResult
        j, d = doc
        r = client.post(f"/api/jobs/{j.id}/docs/{d.id}/review", headers=auth["acme"],
                        json={"scope": "document", "dispositions": [
                            {"id": "att-1", "choice": "entered_manually", "note": "typed it"},
                            {"id": "att-2", "choice": "confirmed_absent"}]})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["document_reviewed"] is True
        assert body["document_state"] in ("READY", "NEEDS_REVIEW")
        att = _stored(client, auth, j.id)["attention"]
        assert att[0]["disposition"]["choice"] == "entered_manually"
        assert att[0]["disposition"]["by"] == "acme_admin"
        assert att[1]["disposition"]["choice"] == "confirmed_absent"

    def test_an_unknown_choice_is_refused(self, client, auth, doc):
        j, d = doc
        r = client.post(f"/api/jobs/{j.id}/docs/{d.id}/review", headers=auth["acme"],
                        json={"dispositions": [{"id": "att-1", "choice": "whatever"}]})
        assert r.status_code == 404


class TestDraftExport:
    def _book(self, client, auth, job_id):
        r = client.get(f"/api/jobs/{job_id}/export", headers=auth["acme"])
        assert r.status_code == 200, r.text
        return r, load_workbook(io.BytesIO(r.content))

    def test_an_unsettled_document_exports_as_a_draft(self, client, auth, doc):
        j, _d = doc
        r, wb = self._book(client, auth, j.id)
        assert f"job_{j.id}_results_DRAFT.xlsx" in r.headers["content-disposition"]
        lg = wb["Legend"]
        assert str(lg["A1"].value).startswith("DRAFT")
        assert "2 completeness reasons open" in str(lg["A1"].value)
        assert "Nothing needs review" not in " ".join(
            str(c.value) for row in lg.iter_rows() for c in row if c.value)
        heads = [c.value for c in next(lg.iter_rows(min_row=1)) if c.value]
        all_text = " ".join(str(c.value) for row in lg.iter_rows() for c in row if c.value)
        assert "Needs attention" in all_text and heads

    def test_c2_default_and_audit_route_keep_review_artifacts(self, client, auth, doc):
        """Exercise C2 through the HTTP route, not just the workbook writer."""
        j, _d = doc
        default = client.get(f"/api/jobs/{j.id}/export", headers=auth["acme"])
        audit = client.get(f"/api/jobs/{j.id}/export?include_audit=true",
                           headers=auth["acme"])
        assert default.status_code == audit.status_code == 200
        assert "_DRAFT.xlsx" in default.headers["content-disposition"]
        assert "_DRAFT.xlsx" in audit.headers["content-disposition"]

        clean_book = load_workbook(io.BytesIO(default.content))
        audit_book = load_workbook(io.BytesIO(audit.content))
        for book in (clean_book, audit_book):
            assert "Legend" in book.sheetnames
            assert str(book["Legend"]["A1"].value).startswith("DRAFT")
            cells = [c for row in book["Results"].iter_rows() for c in row]
            assert any(c.comment is not None for c in cells)
            assert any(c.fill.fill_type == "solid" for c in cells)

        clean_text = [str(c.value) for row in clean_book["Results"].iter_rows()
                      for c in row if c.value is not None]
        audit_text = [str(c.value) for row in audit_book["Results"].iter_rows()
                      for c in row if c.value is not None]
        assert not any(v == "Source" or v.startswith("Review status")
                       or " · p." in v for v in clean_text)
        assert any(v.startswith("Review status") for v in audit_text)
        assert any(" · p." in v for v in audit_text)

    def test_once_settled_the_name_has_no_draft(self, client, auth, doc):
        j, d = doc
        client.post(f"/api/jobs/{j.id}/docs/{d.id}/review", headers=auth["acme"],
                    json={"dispositions": [{"id": "att-1", "choice": "confirmed_absent"},
                                           {"id": "att-2", "choice": "confirmed_absent"}]})
        r, wb = self._book(client, auth, j.id)
        assert "_DRAFT" not in r.headers["content-disposition"]
        assert not str(wb["Legend"]["A1"].value).startswith("DRAFT")


class TestEditsStickAndReachTheExport:
    def test_header_and_cell_edits_survive_reload_and_export(self, client, auth, doc):
        j, d = doc
        r = client.patch(f"/api/jobs/{j.id}/docs/{d.id}/fields/B2", headers=auth["acme"],
                         json={"value": "$99,999.99"})
        assert r.status_code == 200, r.text
        r = client.patch(f"/api/jobs/{j.id}/docs/{d.id}/rows/table/1", headers=auth["acme"],
                         json={"column": "Amount", "value": "4,981.00"})
        assert r.status_code == 200, r.text
        ed = _stored(client, auth, j.id)
        assert ed["extracted_fields"]["B2"] == "$99,999.99"
        assert ed["validation"]["confidence_map"]["B2"] == "edited"
        assert ed["table_rows"][1]["Amount"] == "4,981.00"
        assert ed["table_rows"][1]["_edited"] == ["Amount"]
        log = ed["edit_log"]
        assert [(e["kind"], e["old"], e["new"]) for e in log] == [
            ("field", "$20,376.00", "$99,999.99"), ("cell", "4,980.00", "4,981.00")]
        assert all(e["by"] == "acme_admin" and e["at"] for e in log)
        # an edit does not settle an open completeness reason
        assert any(a["disposition"] is None for a in ed["attention"])
        x = client.get(f"/api/jobs/{j.id}/export", headers=auth["acme"])
        text = " ".join(str(c.value) for ws in load_workbook(io.BytesIO(x.content))
                        for row in ws.iter_rows() for c in row if c.value is not None)
        assert "99999.99" in text.replace(",", "") and "4981" in text.replace(",", "")
        assert "20376" not in text.replace(",", "").replace(".00", "")

    def test_a_stale_whole_document_save_keeps_a_review_mark(self, client, auth, doc):
        j, d = doc
        stale = _stored(client, auth, j.id)            # the browser's copy
        r = client.post(f"/api/jobs/{j.id}/docs/{d.id}/review", headers=auth["acme"],
                        json={"values": [{"ref": "B1"}, {"table": "table", "row": 0}]})
        assert r.status_code == 200, r.text
        stale["table_rows"][1]["Amount"] = "5,000.00"
        r = client.put(f"/api/jobs/{j.id}/docs/{d.id}", headers=auth["acme"],
                       json={"extracted_data": stale})
        assert r.status_code == 200, r.text
        ed = _stored(client, auth, j.id)
        assert ed["field_provenance"]["B1"].get("reviewed")       # was lost before
        assert ed["table_rows"][0].get("_reviewed")
        assert ed["table_rows"][1]["Amount"] == "5,000.00"
        assert [a["id"] for a in ed["attention"]] == ["att-1", "att-2"]

    def test_an_unknown_cell_is_404(self, client, auth, doc):
        j, d = doc
        r = client.patch(f"/api/jobs/{j.id}/docs/{d.id}/rows/table/9", headers=auth["acme"],
                         json={"column": "Amount", "value": "x"})
        assert r.status_code == 404
        r = client.patch(f"/api/jobs/{j.id}/docs/{d.id}/rows/table/0", headers=auth["acme"],
                         json={"column": "_page", "value": "x"})
        assert r.status_code == 404
