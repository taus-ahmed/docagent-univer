"""Tenant-bound admins must not cross tenant boundaries through admin routes."""

from __future__ import annotations

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()


@pytest.fixture
def tenant_stats_rows(db, users):
    from app.models.models import DocumentResult, ExtractionJob

    jobs = [
        ExtractionJob(user_id=users["acme"].id, client_id="acme_001",
                      status="completed", total_docs=2),
        ExtractionJob(user_id=users["other"].id, client_id="other_002",
                      status="completed", total_docs=1),
    ]
    db.add_all(jobs)
    db.flush()
    docs = [
        DocumentResult(job_id=jobs[0].id, filename="a.pdf",
                       overall_confidence="high", needs_review=False,
                       reviewed=True),
        DocumentResult(job_id=jobs[0].id, filename="b.pdf",
                       overall_confidence="low", needs_review=True,
                       reviewed=False),
        DocumentResult(job_id=jobs[1].id, filename="other.pdf",
                       overall_confidence="high", needs_review=False,
                       reviewed=True),
    ]
    db.add_all(docs)
    db.commit()
    yield jobs, docs
    for row in docs + jobs:
        current = db.get(type(row), row.id)
        if current:
            db.delete(current)
    db.commit()


def test_tenant_admin_stats_include_only_its_tenant(
        client, auth, tenant_stats_rows):
    response = client.get("/api/admin/stats", headers=auth["acme"])

    assert response.status_code == 200, response.text
    assert response.json() == {
        "total_jobs": 1,
        "total_documents": 2,
        "total_users": 2,
        "documents_reviewed": 1,
        "documents_pending_review": 1,
        "high_confidence_docs": 1,
        "jobs_last_7_days": 1,
    }


def test_unscoped_super_admin_stats_remain_system_wide(
        client, auth, tenant_stats_rows):
    response = client.get("/api/admin/stats", headers=auth["super"])

    assert response.status_code == 200, response.text
    assert response.json() == {
        "total_jobs": 2,
        "total_documents": 3,
        "total_users": 4,
        "documents_reviewed": 2,
        "documents_pending_review": 1,
        "high_confidence_docs": 2,
        "jobs_last_7_days": 2,
    }


class RecordingStorage:
    def __init__(self):
        self.saved = []

    def save_schema(self, yaml_text, client_id):
        self.saved.append((yaml_text, client_id))
        return f"/fake/{client_id}.yaml", f"schemas/{client_id}.yaml"


@pytest.fixture
def schema_write_rows(app, db, users):
    from app.core.storage import get_storage
    from app.models.models import ClientSchema

    original = {}
    for client_id, name, owner in (
            ("acme_001", "Acme", users["acme"]),
            ("other_002", "Other", users["other"])):
        row = db.query(ClientSchema).filter_by(client_id=client_id).first()
        if row:
            original[row.id] = {
                "client_name": row.client_name,
                "yaml_content": row.yaml_content,
                "s3_key": row.s3_key,
                "document_types": row.document_types,
                "is_active": row.is_active,
                "updated_at": row.updated_at,
            }
        else:
            row = ClientSchema(
                client_id=client_id,
                client_name=name,
                yaml_content=f"client_id: {client_id}\nclient_name: {name}\n",
                s3_key=f"schemas/{client_id}.yaml",
                document_types="[]",
                is_active=True,
                created_by=owner.id,
            )
            db.add(row)
    db.commit()

    storage = RecordingStorage()
    app.dependency_overrides[get_storage] = lambda: storage
    rows = {cid: db.query(ClientSchema).filter_by(client_id=cid).one()
            for cid in ("acme_001", "other_002")}
    snapshots = {cid: (row.client_name, row.yaml_content, row.s3_key,
                       row.document_types, row.is_active, row.updated_at)
                 for cid, row in rows.items()}
    yield rows, snapshots, storage

    app.dependency_overrides.pop(get_storage, None)
    for cid, row in rows.items():
        db.refresh(row)
        (row.client_name, row.yaml_content, row.s3_key, row.document_types,
         row.is_active, row.updated_at) = snapshots[cid]
    db.commit()


def _schema_file(client_id, name):
    body = (f"client_id: {client_id}\nclient_name: {name}\n"
            "document_types:\n  cheque: {}\n")
    return {"file": ("schema.yaml", body.encode(), "application/x-yaml")}


def test_tenant_admin_cannot_overwrite_another_tenants_schema(
        client, auth, db, schema_write_rows):
    rows, snapshots, storage = schema_write_rows

    response = client.post("/api/schemas", headers=auth["acme"],
                           files=_schema_file("other_002", "Stolen"))

    assert response.status_code == 404, response.text
    db.refresh(rows["other_002"])
    assert rows["other_002"].client_name == snapshots["other_002"][0]
    assert rows["other_002"].yaml_content == snapshots["other_002"][1]
    assert storage.saved == []


def test_tenant_admin_can_update_its_own_schema(
        client, auth, schema_write_rows):
    _rows, _snapshots, storage = schema_write_rows

    response = client.post("/api/schemas", headers=auth["acme"],
                           files=_schema_file("acme_001", "Acme Updated"))

    assert response.status_code == 201, response.text
    assert response.json()["client_name"] == "Acme Updated"
    assert [client_id for _text, client_id in storage.saved] == ["acme_001"]


def test_unscoped_super_admin_can_still_update_any_schema(
        client, auth, schema_write_rows):
    _rows, _snapshots, storage = schema_write_rows

    response = client.post("/api/schemas", headers=auth["super"],
                           files=_schema_file("other_002", "Other Updated"))

    assert response.status_code == 201, response.text
    assert response.json()["client_name"] == "Other Updated"
    assert [client_id for _text, client_id in storage.saved] == ["other_002"]


def test_tenant_admin_cannot_deactivate_another_tenants_schema(
        client, auth, db, schema_write_rows):
    rows, _snapshots, _storage = schema_write_rows

    response = client.delete("/api/schemas/other_002", headers=auth["acme"])

    assert response.status_code == 404, response.text
    db.refresh(rows["other_002"])
    assert rows["other_002"].is_active is True


def test_unscoped_super_admin_can_still_deactivate_any_schema(
        client, auth, db, schema_write_rows):
    rows, _snapshots, _storage = schema_write_rows

    response = client.delete("/api/schemas/other_002", headers=auth["super"])

    assert response.status_code == 200, response.text
    db.refresh(rows["other_002"])
    assert rows["other_002"].is_active is False
