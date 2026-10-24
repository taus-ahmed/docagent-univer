"""The review screen's routes: reasons, the job summary, page images with
value boxes, and review marks — and that another tenant gets 404 from every
one of them."""
from __future__ import annotations

import contextlib
import io
import json

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

PDF = bs.PDF_DIR / "INV-2024-0031.pdf"


def _line_with(text):
    from core.preprocessor import preprocess_file
    with contextlib.redirect_stdout(io.StringIO()):
        pd = preprocess_file(PDF)
    for ln in pd.page_lines[0]:
        s = " ".join(str(w["text"]) for w in ln)
        if text in s:
            return s
    raise AssertionError(f"{text!r} not on page 1")


@pytest.fixture(scope="module")
def job(db, users):
    from app.core.storage import get_storage
    from app.models.models import DocumentResult, ExtractionJob
    j = ExtractionJob(user_id=users["acme2"].id, client_id="acme_001",
                      status="completed", total_docs=1, input_source="upload")
    db.add(j); db.commit(); db.refresh(j)
    key, _ = get_storage().save_upload(PDF.read_bytes(), PDF.name, j.id,
                                       client_id="acme_001")
    quote = _line_with("INV-2024-0031")
    ed = {
        "extracted_fields": {"B2": "INV-2024-0031", "B3": "$9.99", "B4": ""},
        "slot_map": {"fields": [{"ref": "B2", "row_label": "Invoice Number"},
                                {"ref": "B3", "row_label": "Total"},
                                {"ref": "B4", "row_label": "PO"}], "tables": []},
        "field_provenance": {
            "B2": {"source": quote, "page": 1, "grounded": True,
                   "review_required": False, "review_reasons": []},
            "B3": {"source": "Total $9.99", "page": 1, "grounded": False,
                   "review_required": True, "review_reasons": ["grounding_failed"]},
            "B4": {"source": "", "page": None, "review_required": False,
                   "review_reasons": []}},
        "validation": {"confidence_map": {"B2": "high", "B3": "low", "B4": "low"},
                       "flagged_fields": [{"ref": "PO", "value": "", "reason": "x"}]},
    }
    d = DocumentResult(job_id=j.id, filename=PDF.name, original_filename=PDF.name,
                       document_type="invoice", extraction_json=json.dumps(ed),
                       needs_review=True, s3_key=key)
    db.add(d); db.commit(); db.refresh(d)
    return j.id, d.id


def test_reasons_are_served(client, auth):
    r = client.get("/api/review/reasons", headers=auth["acme2"])
    assert r.status_code == 200
    body = r.json()
    assert body["reasons"]["amount_mismatch"]["label"]
    assert set(body["statuses"]) >= {"verified", "grounded", "unverified", "low",
                                      "edited", "empty_flagged"}


def test_job_review_counts(client, auth, job):
    jid, did = job
    r = client.get(f"/api/jobs/{jid}/review", headers=auth["acme2"])
    assert r.status_code == 200, r.text
    s = r.json()["summary"]
    assert (s["documents"], s["values"], s["needs_review"], s["low"]) == (1, 3, 2, 1)
    doc = r.json()["documents"][0]
    assert doc["doc_id"] == did and doc["pages"] == [1]


def test_page_meta_boxes_the_value_and_says_why_not(client, auth, job):
    jid, did = job
    r = client.get(f"/api/jobs/{jid}/docs/{did}/pages/1", headers=auth["acme2"])
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["origin"] == "native" and m["width_pt"] > 500
    by = {b["ref"]: b for b in m["boxes"]}
    x0, top, x1, bottom = by["B2"]["box_pt"]
    assert 0 <= x0 < x1 <= m["width_pt"] and 0 <= top < bottom <= m["height_pt"]
    assert by["B2"]["match"] == "value"
    assert by["B3"]["box_pt"] is None and "not found" in by["B3"]["no_box_reason"]
    assert "B4" not in by                     # it has no page


def test_page_image_is_a_png(client, auth, job):
    jid, did = job
    r = client.get(f"/api/jobs/{jid}/docs/{did}/pages/1/image", headers=auth["acme2"])
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    from PIL import Image
    im = Image.open(io.BytesIO(r.content))
    assert max(im.size) <= 2000 and im.size[0] > 500


@pytest.mark.parametrize("page", [0, 2, 99])
def test_a_page_that_does_not_exist_is_404(client, auth, job, page):
    jid, did = job
    for suffix in ("", "/image"):
        r = client.get(f"/api/jobs/{jid}/docs/{did}/pages/{page}{suffix}",
                       headers=auth["acme2"])
        assert r.status_code == 404


def test_another_tenant_gets_404_everywhere(client, auth, job):
    jid, did = job
    for method, url, body in [
            ("GET", f"/api/jobs/{jid}/review", None),
            ("GET", f"/api/jobs/{jid}/docs/{did}/pages/1", None),
            ("GET", f"/api/jobs/{jid}/docs/{did}/pages/1/image", None),
            ("POST", f"/api/jobs/{jid}/docs/{did}/review", {"scope": "document"})]:
        r = client.request(method, url, headers=auth["other"], json=body)
        assert r.status_code == 404, (method, url, r.status_code)


def test_a_document_of_another_job_is_404(client, auth, job, db, users):
    from app.models.models import ExtractionJob
    jid, did = job
    j2 = ExtractionJob(user_id=users["acme2"].id, client_id="acme_001",
                       status="completed", total_docs=0, input_source="upload")
    db.add(j2); db.commit(); db.refresh(j2)
    r = client.get(f"/api/jobs/{j2.id}/docs/{did}/pages/1", headers=auth["acme2"])
    assert r.status_code == 404


def test_marking_values_and_the_document_reviewed(client, auth, job, db):
    from app.models.models import DocumentResult
    jid, did = job
    url = f"/api/jobs/{jid}/docs/{did}/review"
    r = client.post(url, headers=auth["acme2"], json={"values": [{"ref": "B3"}]})
    assert r.status_code == 200, r.text
    assert r.json()["summary"]["needs_review"] == 1
    b3 = next(v for v in r.json()["values"] if v["ref"] == "B3")
    assert b3["resolved"] and b3["status"] == "low"          # the level is kept
    assert client.post(url, headers=auth["acme2"],
                       json={"values": [{"ref": "Z9"}]}).status_code == 404
    r = client.post(url, headers=auth["acme2"], json={"scope": "document"})
    assert r.json()["summary"]["needs_review"] == 0 and r.json()["document_reviewed"]
    db.expire_all()
    d = db.get(DocumentResult, did)
    stored = json.loads(d.extraction_json)
    assert stored["field_provenance"]["B3"]["reviewed"]["by"] == "acme_user"
    assert d.reviewed and not d.needs_review
    # undo leaves the per-value mark in place
    r = client.post(url, headers=auth["acme2"],
                    json={"scope": "document", "reviewed": False})
    assert r.json()["summary"]["needs_review"] == 1


def test_no_retained_source_is_a_clear_404(client, auth, db, users):
    from app.models.models import DocumentResult, ExtractionJob
    j = ExtractionJob(user_id=users["acme2"].id, client_id="acme_001",
                      status="completed", total_docs=1, input_source="upload")
    db.add(j); db.commit(); db.refresh(j)
    d = DocumentResult(job_id=j.id, filename="gone.pdf", original_filename="gone.pdf",
                       extraction_json="{}")
    db.add(d); db.commit(); db.refresh(d)
    r = client.get(f"/api/jobs/{j.id}/docs/{d.id}/pages/1", headers=auth["acme2"])
    assert r.status_code == 404 and "not retained" in r.json()["detail"]


def test_an_ocr_page_serves_the_straightened_image(client, auth, db, users,
                                                   scanned_pdf_bytes):
    from app.core.storage import get_storage
    from app.models.models import DocumentResult, ExtractionJob
    j = ExtractionJob(user_id=users["acme2"].id, client_id="acme_001",
                      status="completed", total_docs=1, input_source="upload")
    db.add(j); db.commit(); db.refresh(j)
    key, _ = get_storage().save_upload(scanned_pdf_bytes, "scan.pdf", j.id,
                                       client_id="acme_001")
    d = DocumentResult(job_id=j.id, filename="scan.pdf", original_filename="scan.pdf",
                       extraction_json="{}", s3_key=key)
    db.add(d); db.commit(); db.refresh(d)
    m = client.get(f"/api/jobs/{j.id}/docs/{d.id}/pages/1", headers=auth["acme2"])
    assert m.status_code == 200, m.text
    assert m.json()["origin"] == "ocr"
    assert m.json()["frame"].startswith("straightened")
    r = client.get(f"/api/jobs/{j.id}/docs/{d.id}/pages/1/image", headers=auth["acme2"])
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"


def test_every_export_carries_a_legend_with_the_count(client, auth, db, users):
    import openpyxl
    from app.models.models import DocumentResult, ExtractionJob
    j = ExtractionJob(user_id=users["acme2"].id, client_id="acme_001",
                      status="completed", total_docs=1, input_source="upload")
    db.add(j); db.commit(); db.refresh(j)
    ed = {"extracted_fields": {"B2": "1.00", "B3": "2.00"},
          "slot_map": {"fields": [{"ref": "B2", "row_label": "A"},
                                  {"ref": "B3", "row_label": "B"}], "tables": []},
          "field_provenance": {"B2": {"review_required": True,
                                      "review_reasons": ["ocr_origin"]},
                               "B3": {"review_required": False, "review_reasons": []}},
          "validation": {"confidence_map": {"B2": "unverified", "B3": "high"}}}
    db.add(DocumentResult(job_id=j.id, filename="x.pdf", original_filename="x.pdf",
                          extraction_json=json.dumps(ed)))
    db.commit()
    for url in (f"/api/jobs/{j.id}/export", f"/api/jobs/{j.id}/export/zip"):
        r = client.get(url, headers=auth["acme2"])
        assert r.status_code == 200, (url, r.text[:200])
        if url.endswith("zip"):
            import zipfile
            z = zipfile.ZipFile(io.BytesIO(r.content))
            data = z.read(z.namelist()[0])
        else:
            data = r.content
        wb = openpyxl.load_workbook(io.BytesIO(data))
        assert "Legend" in wb.sheetnames
        lg = wb["Legend"]
        assert lg["A1"].value == "1 value needs review"
        assert "1 unverified" in lg["A2"].value
