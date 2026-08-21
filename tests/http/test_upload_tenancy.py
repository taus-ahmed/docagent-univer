"""
Upload must not trust the request body for who you are or what you may use.

Two holes, both at POST /api/extract/upload, both found by the pre-Phase-8
audit and neither caught by any of the 224 tests that existed:

  1. The template was loaded by id with NO ownership check at all —
     `db.query(ColumnTemplate).filter(id == template_id).first()`. Any
     authenticated user could extract with any other tenant's template,
     which discloses that template's structure: its field labels, its
     table columns, the shape of that customer's documents.

  2. `client_id` came from the multipart form, so a user could attribute a
     job — and its extracted contents — to any tenant they cared to name.

Both are now taken from the token's authority. These tests fail against the
pre-fix code.
"""
import io

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()


def _upload(client, headers, pdf, *, client_id="acme_001", template_id=None):
    data = {"client_id": client_id}
    if template_id is not None:
        data["template_id"] = str(template_id)
    return client.post(
        "/api/extract/upload", headers=headers, data=data,
        files=[("files", ("doc.pdf", io.BytesIO(pdf), "application/pdf"))],
    )


@pytest.fixture(autouse=True)
def _no_real_extraction(monkeypatch):
    """Stop the background thread. These tests are about the request, not the
    pipeline — and a real extraction would spend money and take minutes."""
    import threading

    class _Inert(threading.Thread):
        def start(self):
            return None

    monkeypatch.setattr("app.api.routes.extract.threading.Thread", _Inert)


class TestTemplateOwnership:
    def test_another_tenants_private_template_is_refused(
            self, client, auth, templates, pdf_bytes):
        """THE HOLE. acme asking to extract with other_002's private template."""
        r = _upload(client, auth["acme"], pdf_bytes,
                    template_id=templates["other_private"].id)
        assert r.status_code == 403, r.text

    def test_a_client_user_cannot_use_another_tenants_template_either(
            self, client, auth, templates, pdf_bytes):
        r = _upload(client, auth["other"], pdf_bytes, client_id="other_002",
                    template_id=templates["acme_private"].id)
        assert r.status_code == 403, r.text

    def test_your_own_template_is_accepted(self, client, auth, templates, pdf_bytes):
        r = _upload(client, auth["acme"], pdf_bytes,
                    template_id=templates["acme_private"].id)
        assert r.status_code == 202, r.text

    def test_a_template_shared_inside_your_own_client_is_accepted(
            self, client, auth, templates, pdf_bytes):
        r = _upload(client, auth["acme2"], pdf_bytes,
                    template_id=templates["acme_shared"].id)
        assert r.status_code == 202, r.text

    def test_a_system_default_is_accepted_by_anyone(
            self, client, auth, templates, pdf_bytes):
        r = _upload(client, auth["other"], pdf_bytes, client_id="other_002",
                    template_id=templates["system_default"].id)
        assert r.status_code == 202, r.text

    def test_a_super_admin_may_use_any_template(
            self, client, auth, templates, pdf_bytes):
        r = _upload(client, auth["super"], pdf_bytes, client_id="other_002",
                    template_id=templates["other_private"].id)
        assert r.status_code == 202, r.text

    def test_a_template_that_does_not_exist_is_a_404_not_a_silent_downgrade(
            self, client, auth, pdf_bytes):
        """Before: an unknown id left template_data None and the document was
        extracted with NO template — a completely different extraction mode,
        chosen silently, reported as success."""
        r = _upload(client, auth["acme"], pdf_bytes, template_id=987654)
        assert r.status_code == 404, r.text


class TestClientIdComesFromTheToken:
    def _job_client_id(self, db, resp):
        from app.models.models import ExtractionJob
        db.expire_all()
        job = db.query(ExtractionJob).filter(
            ExtractionJob.id == resp.json()["job_id"]).first()
        return job.client_id

    def test_a_forged_client_id_in_the_body_is_ignored(
            self, client, auth, db, pdf_bytes):
        """THE HOLE. acme_001's user naming other_002 in the form."""
        r = _upload(client, auth["acme"], pdf_bytes, client_id="other_002")
        assert r.status_code == 202, r.text
        assert self._job_client_id(db, r) == "acme_001"

    def test_a_client_role_user_is_pinned_to_their_own_tenant(
            self, client, auth, db, pdf_bytes):
        r = _upload(client, auth["other"], pdf_bytes, client_id="acme_001")
        assert r.status_code == 202, r.text
        assert self._job_client_id(db, r) == "other_002"

    def test_the_honest_case_still_works(self, client, auth, db, pdf_bytes):
        r = _upload(client, auth["acme2"], pdf_bytes, client_id="acme_001")
        assert r.status_code == 202
        assert self._job_client_id(db, r) == "acme_001"

    def test_the_frontends_mismatched_client_id_does_not_break_upload(
            self, client, auth, db, pdf_bytes):
        """The Extract page sends `schemas[0].client_id`, which is the first
        schema in a list and not necessarily the signed-in user's tenant. A
        403 on mismatch would lock out the tenanted users this protects, so
        the body value is ignored rather than rejected."""
        r = _upload(client, auth["acme2"], pdf_bytes, client_id="demo_001")
        assert r.status_code == 202, r.text
        assert self._job_client_id(db, r) == "acme_001"

    def test_a_super_admin_may_act_for_a_named_client(
            self, client, auth, db, pdf_bytes):
        """They have no tenant of their own, so the body is the only source."""
        r = _upload(client, auth["super"], pdf_bytes, client_id="other_002")
        assert r.status_code == 202, r.text
        assert self._job_client_id(db, r) == "other_002"

    def test_a_super_admin_with_no_client_id_is_asked_for_one(
            self, client, auth, pdf_bytes):
        r = _upload(client, auth["super"], pdf_bytes, client_id="")
        assert r.status_code == 400, r.text
        assert "client_id" in r.text


class TestUnauthenticatedCannotUploadAtAll:
    def test_no_token_is_401(self, client, pdf_bytes):
        r = _upload(client, {}, pdf_bytes)
        assert r.status_code in (401, 403), r.text

    def test_a_garbage_token_is_401(self, client, pdf_bytes):
        r = _upload(client, {"Authorization": "Bearer not.a.jwt"}, pdf_bytes)
        assert r.status_code == 401, r.text
