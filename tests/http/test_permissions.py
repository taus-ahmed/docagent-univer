"""
Who may see and change what, over HTTP.

The RBAC rules exist in the route code and were, until this suite, checked by
nothing. Four principals cover every branch:

    super   admin, no client_id   — sees and acts across all tenants
    acme    admin, client_id set  — company admin for acme_001
    acme2   client in acme_001
    other   client in other_002   — the one who must be kept out
"""
import json

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

GRID = json.dumps({
    "cells": {"0,0": {"value": "Invoice Number", "style": {}},
              "0,1": {"value": "", "style": {}}},
    "colWidths": [160, 160], "merges": {}, "repeatRows": [],
})


class TestTemplateVisibility:
    def test_a_tenant_does_not_see_another_tenants_templates(
            self, client, auth, templates):
        names = {t["name"] for t in client.get(
            "/api/templates", headers=auth["other"]).json()}
        assert "acme_private" not in names
        assert "acme_shared" not in names

    def test_a_tenant_sees_its_own_and_shared_and_defaults(
            self, client, auth, templates):
        names = {t["name"] for t in client.get(
            "/api/templates", headers=auth["acme2"]).json()}
        assert "acme_shared" in names
        assert "system_default" in names

    def test_a_super_admin_sees_everything(self, client, auth, templates):
        names = {t["name"] for t in client.get(
            "/api/templates", headers=auth["super"]).json()}
        assert {"acme_private", "other_private", "system_default"} <= names

    def test_fetching_another_tenants_template_by_id_is_403(
            self, client, auth, templates):
        r = client.get(f"/api/templates/{templates['other_private'].id}",
                       headers=auth["acme"])
        assert r.status_code == 403, r.text

    def test_a_template_that_does_not_exist_is_404(self, client, auth):
        assert client.get("/api/templates/987654",
                          headers=auth["acme"]).status_code == 404


class TestTemplateMutation:
    def test_editing_another_tenants_template_is_403(
            self, client, auth, templates):
        r = client.put(f"/api/templates/{templates['other_private'].id}",
                       headers=auth["acme"], json={"name": "hijacked"})
        assert r.status_code == 403, r.text

    def test_deleting_another_tenants_template_is_403(
            self, client, auth, templates):
        r = client.delete(f"/api/templates/{templates['other_private'].id}",
                          headers=auth["acme"])
        assert r.status_code == 403, r.text

    def test_a_refused_edit_really_did_not_change_anything(
            self, client, auth, db, templates):
        from app.models.models import ColumnTemplate
        tid = templates["other_private"].id
        client.put(f"/api/templates/{tid}", headers=auth["acme"],
                   json={"name": "hijacked"})
        db.expire_all()
        assert db.get(ColumnTemplate, tid).name == "other_private"

    def test_you_can_edit_your_own(self, client, auth, templates):
        tid = templates["acme_private"].id
        r = client.put(f"/api/templates/{tid}", headers=auth["acme"],
                       json={"description": GRID})
        assert r.status_code == 200, r.text

    def test_a_non_admin_cannot_share_a_template(self, client, auth, db):
        """is_shared is an admin/company_admin power. A client role asking for
        it must not get it — silently ignored, per the route's own rule."""
        r = client.post("/api/templates", headers=auth["acme2"], json={
            "name": "acme2_attempt_share", "document_type": "sales_invoice",
            "description": GRID, "columns": [], "is_shared": True})
        assert r.status_code == 201, r.text
        assert r.json()["is_shared"] is False


class TestJobOwnership:
    @staticmethod
    @pytest.fixture(scope="class")
    def jobs(db, users):
        from app.models.models import ExtractionJob
        made = {}
        for key, cid in (("acme", "acme_001"), ("other", "other_002")):
            j = db.query(ExtractionJob).filter(
                ExtractionJob.client_id == cid).first()
            if not j:
                j = ExtractionJob(user_id=users[key].id, client_id=cid,
                                  status="completed", total_docs=1,
                                  successful=1, input_source="upload")
                db.add(j)
                db.commit()
                db.refresh(j)
            made[key] = j
        return made

    def test_a_tenant_cannot_read_another_tenants_job(self, client, auth, jobs):
        r = client.get(f"/api/jobs/{jobs['other'].id}", headers=auth["acme"])
        assert r.status_code in (403, 404), r.text

    def test_a_tenant_cannot_delete_another_tenants_job(self, client, auth, jobs):
        r = client.delete(f"/api/jobs/{jobs['other'].id}", headers=auth["acme"])
        assert r.status_code in (403, 404), r.text

    def test_the_job_list_is_scoped_to_the_tenant(self, client, auth, jobs):
        ids = {j["id"] for j in client.get("/api/jobs",
                                           headers=auth["acme"]).json()}
        assert jobs["other"].id not in ids

    def test_your_own_job_is_readable(self, client, auth, jobs):
        r = client.get(f"/api/jobs/{jobs['acme'].id}", headers=auth["acme"])
        assert r.status_code == 200, r.text

    def test_a_super_admin_sees_every_job(self, client, auth, jobs):
        ids = {j["id"] for j in client.get("/api/jobs",
                                           headers=auth["super"]).json()}
        assert {jobs["acme"].id, jobs["other"].id} <= ids


class TestAdminOnlyRoutes:
    ROUTES = [("GET", "/api/admin/users"), ("GET", "/api/admin/stats")]

    def test_a_client_role_is_refused(self, client, auth):
        for method, path in self.ROUTES:
            r = client.request(method, path, headers=auth["acme2"])
            assert r.status_code == 403, f"{path} -> {r.status_code}"

    def test_an_admin_is_allowed(self, client, auth):
        for method, path in self.ROUTES:
            r = client.request(method, path, headers=auth["super"])
            assert r.status_code == 200, f"{path} -> {r.text[:120]}"

    def test_a_client_role_cannot_create_users(self, client, auth):
        r = client.post("/api/admin/users", headers=auth["acme2"], json={
            "username": "sneaky", "password": "pw123456",
            "display_name": "Sneaky", "role": "admin"})
        assert r.status_code == 403, r.text

    def test_a_client_role_cannot_delete_users(self, client, auth, users):
        r = client.delete(f"/api/admin/users/{users['acme'].id}",
                          headers=auth["acme2"])
        assert r.status_code == 403, r.text


class TestExportPermissions:
    @staticmethod
    @pytest.fixture(scope="class")
    def other_job(db, users):
        from app.models.models import ExtractionJob
        j = ExtractionJob(user_id=users["other"].id, client_id="other_002",
                          status="completed", total_docs=1, successful=1,
                          input_source="upload")
        db.add(j)
        db.commit()
        db.refresh(j)
        return j

    def test_exporting_another_tenants_job_is_refused(
            self, client, auth, other_job):
        r = client.post("/api/export/combined", headers=auth["acme"],
                        json={"job_id": other_job.id})
        assert r.status_code in (403, 404), r.text

    def test_per_file_export_is_scoped_too(self, client, auth, other_job):
        r = client.post("/api/export/perfile", headers=auth["acme"],
                        json={"job_id": other_job.id})
        assert r.status_code in (403, 404), r.text

    def test_exporting_a_job_that_does_not_exist_is_404(self, client, auth):
        r = client.post("/api/export/combined", headers=auth["acme"],
                        json={"job_id": 987654})
        assert r.status_code == 404, r.text
