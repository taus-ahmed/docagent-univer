"""Run T1, 3h: ?layout=organized is the structure layout, read from the
words stored with each record (the upload is not needed); the owner's
NO_TEMPLATE_USES_STRUCTURE switch is off by default; plan calls are costed."""
import io
import json

from openpyxl import load_workbook

from tests.harness import bootstrap as bs
from tests.run_q_support import make_pdf

bs.bootstrap()


def _job(db, users, tmp_path, store_file=True, store_words=True):
    import perception as P
    from app.core.storage import get_storage
    from app.models.models import DocumentResult, ExtractionJob
    j = ExtractionJob(user_id=users["acme"].id, client_id="acme_001", status="completed",
                      total_docs=1, successful=1, input_source="upload")
    db.add(j)
    db.commit()
    db.refresh(j)
    pdf = make_pdf(tmp_path / "stub.pdf", [[(72, 740, "Employer Name: ACME Corp"),
                                            (72, 700, "Net Pay"), (330, 700, "$5,731.00")]])
    key = f"clients/acme_001/jobs/{j.id}/source/stub.pdf"
    if store_file:
        get_storage().put(key, pdf.read_bytes())
    d = DocumentResult(job_id=j.id, filename="stub.pdf", original_filename="stub.pdf",
                       s3_key=key, extraction_json=json.dumps({"extracted_fields": {}}),
                       perception_json=P.pack(P.read_document(pdf)) if store_words else None,
                       needs_review=False, reviewed=False)
    db.add(d)
    db.commit()
    return j


def _vals(r, sheet="stub"):
    assert r.status_code == 200, r.text
    wb = load_workbook(io.BytesIO(r.content))
    return wb, [c.value for row in wb[sheet].iter_rows() for c in row if c.value is not None]


def test_laid_out_from_stored_words_when_the_upload_is_gone(client, db, users, auth, tmp_path):
    j = _job(db, users, tmp_path, store_file=False)
    r = client.get(f"/api/jobs/{j.id}/export?layout=organized", headers=auth["acme"])
    wb, vals = _vals(r)
    assert "Employer Name:" in vals and "ACME Corp" in vals and 5731.0 in vals
    assert "Layout check" in wb.sheetnames
    notes = [c.value for row in wb["Layout check"].iter_rows() for c in row]
    assert any("geometry" in str(v) for v in notes)


def test_neither_words_nor_file_is_named(client, db, users, auth, tmp_path):
    j = _job(db, users, tmp_path, store_file=False, store_words=False)
    r = client.get(f"/api/jobs/{j.id}/export?layout=organized", headers=auth["acme"])
    assert r.status_code == 422 and r.json()["detail"]["code"] == "source_missing"


def test_default_export_unchanged_while_the_switch_is_off(client, db, users, auth, tmp_path):
    from app.config import settings
    assert settings.NO_TEMPLATE_USES_STRUCTURE is False
    j = _job(db, users, tmp_path)
    r = client.get(f"/api/jobs/{j.id}/export", headers=auth["acme"])
    assert r.status_code == 200 and "organized" not in r.headers["content-disposition"]


def test_switch_on_makes_the_structure_layout_the_default(client, db, users, auth, tmp_path,
                                                           monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "NO_TEMPLATE_USES_STRUCTURE", True)
    j = _job(db, users, tmp_path)
    r = client.get(f"/api/jobs/{j.id}/export", headers=auth["acme"])
    assert "organized" in r.headers["content-disposition"]
    _wb, vals = _vals(r)
    assert "Employer Name:" in vals


def test_switch_on_but_nothing_to_lay_out_falls_back_to_the_ordinary_sheet(
        client, db, users, auth, tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "NO_TEMPLATE_USES_STRUCTURE", True)
    j = _job(db, users, tmp_path, store_file=False, store_words=False)
    r = client.get(f"/api/jobs/{j.id}/export", headers=auth["acme"])
    assert r.status_code == 200 and "organized" not in r.headers["content-disposition"]


def test_plan_calls_at_extraction_are_stored_and_costed(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app.config import settings
    from app.services import perception_store as PS
    from app.services.job_worker import doc_cost_of
    import perception as P
    import structure_engine as S
    import structure_geometry as G
    monkeypatch.setattr(settings, "STRUCTURE_PLANS_AT_EXTRACTION", True)
    monkeypatch.setattr(PS, "_page_images", lambda p: {})
    pdf = make_pdf(tmp_path / "s.pdf", [[(72, 740, "Employer Name: ACME Corp")]])
    good = G.fallback_plan(P.read_document(pdf)["pages"][0])

    def extract(prompt="", system_instruction="", **kw):
        import llm_contract as C
        C.finish_attempt({**C.new_attempt("gemini-2.5-flash"), "prompt_tokens": 1000,
                          "output_tokens": 100, "thinking_tokens": 0,
                          "model_version": "gemini-2.5-flash"}, log=False)
        return SimpleNamespace(success=True, error_kind=None, tokens_used=1100, attempts=[],
                               parsed_json={k: good[k] for k in ("regions", "ignored",
                                                                 "contradictions")})
    ed = {}
    packed = PS.packed_for(pdf, ed, {}, SimpleNamespace(llm=SimpleNamespace(extract=extract)))
    perc = P.unpack(packed)
    assert S.stored_plans(perc)[1]["regions"]
    assert ed["diagnostics"]["structure_attempts"]
    assert doc_cost_of(ed, None, 0)["usd"] > 0
