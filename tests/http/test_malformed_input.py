"""
Bad input must produce a bad-request answer, not a stack trace.

Malformed uploads were probed by hand during the pre-Phase-8 audit and held up.
This pins that behaviour so it stays true, and extends the same question to the
JSON endpoints, which had never been asked it at all.

The rule being checked throughout: 4xx for anything the caller got wrong, and
never a 500 — a 500 is a bug reaching the client.
"""
import io

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()


@pytest.fixture(autouse=True)
def _no_real_extraction(monkeypatch):
    import threading

    class _Inert(threading.Thread):
        def start(self):
            return None

    monkeypatch.setattr("app.api.routes.extract.threading.Thread", _Inert)


def _upload(client, auth, name, content, client_id="acme_001"):
    return client.post(
        "/api/extract/upload", headers=auth, data={"client_id": client_id},
        files=[("files", (name, io.BytesIO(content), "application/pdf"))])


class TestUploadedFilesThatAreNotDocuments:
    CASES = {
        "zero_bytes.pdf": b"",
        "plain_text.pdf": b"this is not a pdf at all\n" * 5,
        "truncated.pdf": b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog",
        "html.pdf": b"<html><body><h1>hi</h1></body></html>",
    }

    def test_they_are_accepted_for_processing_not_crashed_on(self, client, auth):
        """Validation happens in the pipeline, not at the door: the upload is
        accepted and the document fails inside the job. What must not happen
        is a 500 at request time."""
        for name, content in self.CASES.items():
            r = _upload(client, auth["acme"], name, content)
            assert r.status_code == 202, f"{name} -> {r.status_code} {r.text[:100]}"

    def test_a_disallowed_extension_is_refused(self, client, auth):
        r = _upload(client, auth["acme"], "payload.exe", b"MZ\x90\x00")
        assert r.status_code == 400
        assert "not supported" in r.text

    def test_a_double_extension_does_not_sneak_through(self, client, auth):
        r = _upload(client, auth["acme"], "invoice.pdf.exe", b"MZ\x90\x00")
        assert r.status_code == 400, r.text

    def test_a_file_with_no_extension_is_refused(self, client, auth):
        assert _upload(client, auth["acme"], "noextension",
                       b"data").status_code == 400

    def test_an_oversized_file_is_refused(self, client, auth):
        from app.config import settings
        big = b"%PDF-1.4\n" + b"\0" * (settings.max_upload_bytes + 1024)
        r = _upload(client, auth["acme"], "huge.pdf", big)
        assert r.status_code == 400
        assert "too large" in r.text.casefold()

    def test_a_traversal_filename_cannot_escape_the_upload_directory(
            self, client, auth, _scratch_storage):
        """The name is sanitised to its last component. Verified end to end:
        nothing lands outside the job's own directory."""
        r = _upload(client, auth["acme"], "../../../escaped.pdf",
                    b"%PDF-1.4\n%%EOF\n")
        assert r.status_code == 202, r.text
        assert not (_scratch_storage.parent / "escaped.pdf").exists()
        assert not (_scratch_storage / "escaped.pdf").exists()

    def test_uploading_no_files_at_all_is_a_422(self, client, auth):
        r = client.post("/api/extract/upload", headers=auth["acme"],
                        data={"client_id": "acme_001"})
        assert r.status_code == 422, r.text

    def test_too_many_files_is_refused(self, client, auth):
        from app.config import settings
        n = settings.MAX_FILES_PER_BATCH + 1
        files = [("files", (f"f{i}.pdf", io.BytesIO(b"%PDF-1.4\n%%EOF\n"),
                            "application/pdf")) for i in range(n)]
        r = client.post("/api/extract/upload", headers=auth["acme"],
                        data={"client_id": "acme_001"}, files=files)
        assert r.status_code == 400
        assert "max" in r.text.casefold()


class TestMalformedJsonBodies:
    def test_a_missing_required_field_is_422(self, client, auth):
        r = client.post("/api/templates", headers=auth["acme"],
                        json={"document_type": "sales_invoice"})
        assert r.status_code == 422, r.text

    def test_a_wrong_type_is_422(self, client, auth):
        r = client.post("/api/export/combined", headers=auth["acme"],
                        json={"job_id": "not-a-number"})
        assert r.status_code == 422, r.text

    def test_unparseable_json_is_422_not_500(self, client, auth):
        r = client.post("/api/templates",
                        headers={**auth["acme"],
                                 "Content-Type": "application/json"},
                        content=b"{not json at all")
        assert r.status_code == 422, r.text

    def test_an_empty_body_where_one_is_required_is_422(self, client, auth):
        r = client.post("/api/export/combined", headers=auth["acme"], json={})
        assert r.status_code == 422, r.text

    def test_a_null_body_is_422(self, client, auth):
        r = client.post("/api/export/combined", headers=auth["acme"], json=None)
        assert r.status_code == 422, r.text

    def test_an_invalid_role_is_refused(self, client, auth):
        """UserCreate constrains role to admin|client."""
        r = client.post("/api/admin/users", headers=auth["super"], json={
            "username": "roletest", "password": "pw123456",
            "display_name": "Role Test", "role": "superuser"})
        assert r.status_code == 422, r.text


class TestTemplateGridsThatAreNotGrids:
    def test_a_non_json_description_is_accepted_as_plain_text(
            self, client, auth):
        """description is dual-use: a grid OR a human description. Free text
        must not fail the save."""
        r = client.post("/api/templates", headers=auth["acme"], json={
            "name": "plain_text_desc", "document_type": "other",
            "description": "just a note about this template", "columns": []})
        assert r.status_code == 201, r.text

    def test_the_shape_endpoint_refuses_nonsense_without_crashing(
            self, client, auth):
        for bad in [{}, {"grid": None}, {"grid": "nonsense"},
                    {"grid": {"no": "cells"}}, {"grid": []}, {"grid": 42}]:
            r = client.post("/api/templates/shape", headers=auth["acme"],
                            json=bad)
            assert r.status_code == 200, f"{bad} -> {r.status_code}"
            assert r.json()["field_count"] == 0

    def test_a_grid_with_absurd_coordinates_does_not_crash(self, client, auth):
        r = client.post("/api/templates/shape", headers=auth["acme"], json={
            "grid": {"cells": {"999999,999999": {"value": "x", "style": {}},
                               "-1,-1": {"value": "y", "style": {}},
                               "bad,key": {"value": "z", "style": {}}},
                     "colWidths": [], "merges": {}, "repeatRows": []}})
        assert r.status_code == 200, r.text


class TestLoginInput:
    def test_a_wrong_password_is_401_not_500(self, client, users):
        r = client.post("/api/auth/login",
                        json={"username": "acme_admin", "password": "wrong"})
        assert r.status_code == 401, r.text

    def test_an_unknown_user_is_401(self, client):
        r = client.post("/api/auth/login",
                        json={"username": "nobody-here", "password": "x"})
        assert r.status_code == 401, r.text

    def test_the_error_does_not_say_which_half_was_wrong(self, client, users):
        """Distinguishing 'no such user' from 'wrong password' enumerates
        accounts."""
        a = client.post("/api/auth/login",
                        json={"username": "acme_admin", "password": "wrong"})
        b = client.post("/api/auth/login",
                        json={"username": "nobody-here", "password": "wrong"})
        assert a.json().get("detail") == b.json().get("detail")

    def test_missing_credentials_are_422(self, client):
        assert client.post("/api/auth/login", json={}).status_code == 422
