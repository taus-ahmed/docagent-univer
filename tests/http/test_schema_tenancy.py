"""
A client's YAML schema is that client's business, and it was everybody's.

Three holes at `/api/schemas`, all three reachable by any authenticated user —
no admin role, no shared flag, no tenant check anywhere:

  1. GET /api/schemas listed EVERY tenant's schema: client_id, company name and
     document types for every other customer on the deployment.
  2. GET /api/schemas/{client_id} returned another tenant's RAW YAML — their
     field vocabulary, their document types, their naming.
  3. POST /api/schemas keyed on the client_id inside the uploaded file and
     overwrote the existing row for that client. A cross-tenant WRITE: any
     user could replace any customer's extraction vocabulary.

The list endpoint is load-bearing for ordinary use — the Extract page reads
`schemas[0].client_id` out of it — so the last two tests here are about the
honest path continuing to work, including for a user who has no schema at all.
"""
import io

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()


def _yaml_for(client_id: str) -> bytes:
    return (f"client_id: {client_id}\n"
            f"client_name: Hostile Takeover Ltd\n"
            # document_types is a MAPPING in this app's YAML (the route reads
            # .keys() off it), not a list.
            f"document_types:\n"
            f"  sales_invoice:\n"
            f"    required_fields: [invoice_number]\n").encode("utf-8")


@pytest.fixture(autouse=True)
def _schemas_in_db(db):
    """Two tenants with a schema each, in the database the app is using."""
    from app.models.models import ClientSchema
    for cid, name in (("acme_001", "Acme"), ("other_002", "Other Co")):
        row = db.query(ClientSchema).filter(
            ClientSchema.client_id == cid).first()
        if not row:
            db.add(ClientSchema(client_id=cid, client_name=name,
                                yaml_content=f"client_id: {cid}\n",
                                document_types='["sales_invoice"]',
                                is_active=True))
    db.commit()


class TestClientACannotReachClientBsSchema:
    """THE HOLE, from the only direction that matters: a different tenant."""

    def test_the_listing_shows_only_your_own_tenant(self, client, auth):
        r = client.get("/api/schemas", headers=auth["other"])
        assert r.status_code == 200, r.text
        ids = {row["client_id"] for row in r.json()}
        assert ids == {"other_002"}, ids

    def test_reading_another_tenants_yaml_is_refused(self, client, auth):
        r = client.get("/api/schemas/acme_001", headers=auth["other"])
        assert r.status_code == 404, r.text
        assert "acme_001" in r.json()["detail"]

    def test_the_refusal_is_indistinguishable_from_not_existing(
            self, client, auth):
        """A 403 would confirm which other companies are on the deployment,
        which is most of what the leak was worth."""
        forbidden = client.get("/api/schemas/acme_001", headers=auth["other"])
        absent = client.get("/api/schemas/no_such_client", headers=auth["other"])
        assert forbidden.status_code == absent.status_code == 404
        assert forbidden.json()["detail"].replace("acme_001", "X") == \
               absent.json()["detail"].replace("no_such_client", "X")

    def test_overwriting_another_tenants_schema_is_refused(self, client, auth):
        """Upload keys on the client_id INSIDE the file, so this was a write
        into another tenant's row, not merely a read."""
        r = client.post(
            "/api/schemas", headers=auth["other"],
            files=[("file", ("acme.yaml", io.BytesIO(_yaml_for("acme_001")),
                             "application/x-yaml"))],
        )
        assert r.status_code == 403, r.text

    def test_the_overwrite_really_did_not_happen(self, client, auth, db):
        from app.models.models import ClientSchema
        row = db.query(ClientSchema).filter(
            ClientSchema.client_id == "acme_001").first()
        assert "Hostile Takeover" not in (row.client_name or "")
        assert "Hostile Takeover" not in (row.yaml_content or "")

    def test_a_company_admin_is_scoped_to_their_own_tenant_too(
            self, client, auth):
        """role=admin WITH a client_id is a tenant, not a super-admin — the
        same reading `_get_job_or_404` and `_get_template_or_403` use."""
        r = client.get("/api/schemas", headers=auth["acme"])
        assert {row["client_id"] for row in r.json()} == {"acme_001"}
        assert client.get("/api/schemas/other_002",
                          headers=auth["acme"]).status_code == 404


class TestAdminStillSeesEverything:
    def test_a_super_admin_lists_every_tenant(self, client, auth):
        r = client.get("/api/schemas", headers=auth["super"])
        ids = {row["client_id"] for row in r.json()}
        assert {"acme_001", "other_002"} <= ids, ids

    def test_a_super_admin_may_read_any_yaml(self, client, auth):
        r = client.get("/api/schemas/acme_001", headers=auth["super"])
        assert r.status_code == 200, r.text
        assert "yaml_content" in r.json()

    def test_a_super_admin_may_still_upload(self, client, auth, db):
        r = client.post(
            "/api/schemas", headers=auth["super"],
            files=[("file", ("new.yaml", io.BytesIO(_yaml_for("fresh_009")),
                             "application/x-yaml"))],
        )
        assert r.status_code == 201, r.text
        assert r.json()["client_id"] == "fresh_009"


class TestTheExtractPageStillWorks:
    """`frontend/app/extract/page.tsx` reads `schemas[0].client_id` to fill the
    upload form. Scoping the list must not break that for a normal user, and
    must not break upload for a user whose tenant has no schema at all."""

    def test_a_normal_user_gets_their_own_tenant_first(self, client, auth):
        r = client.get("/api/schemas", headers=auth["acme2"])
        rows = r.json()
        assert rows, "the page would fall back to demo_001 with an empty list"
        assert rows[0]["client_id"] == "acme_001"

    def test_a_user_with_no_schema_gets_an_empty_list_not_an_error(
            self, client, demo_auth):
        """`pearx_demo` has no schema row. The page handles `[]` by falling
        back to "demo_001", and the upload endpoint ignores the form value
        anyway — the tenant comes from the token."""
        r = client.get("/api/schemas", headers=demo_auth)
        assert r.status_code == 200, r.text
        assert r.json() == []

    def test_upload_still_works_for_a_user_with_no_schema(
            self, client, demo_auth, pdf_bytes, monkeypatch):
        import threading

        class _Inert(threading.Thread):
            def start(self):
                return None

        monkeypatch.setattr("app.api.routes.extract.threading.Thread", _Inert)
        r = client.post(
            "/api/extract/upload", headers=demo_auth,
            data={"client_id": "demo_001"},
            files=[("files", ("doc.pdf", io.BytesIO(pdf_bytes),
                              "application/pdf"))],
        )
        assert r.status_code == 202, r.text
