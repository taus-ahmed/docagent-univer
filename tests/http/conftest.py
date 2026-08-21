"""
Shared fixtures for the HTTP-level suite.

Every test here goes through the real ASGI app with a real router, real
dependencies and real auth — the layer that had no coverage at all before, and
where both tenancy holes lived.

The database is a throwaway SQLite file per test session, injected by
overriding the `get_db` dependency. It is deliberately NOT the developer's
Postgres: these tests create users, templates and jobs, and a suite that writes
to the working database is a suite people stop running.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()


@pytest.fixture(scope="session")
def _db_url():
    d = Path(tempfile.mkdtemp(prefix="docagent_http_"))
    return f"sqlite:///{(d / 'test.db').as_posix()}"


@pytest.fixture(scope="session", autouse=True)
def _scratch_storage():
    """Point uploads/outputs/schemas at a scratch tree and give the test
    tenants a schema each.

    Upload 404s without a schema for the tenant, so the tenancy tests need
    real schema files — and they must not be written into the developer's
    backend/storage, which is a working directory, not a fixture.
    """
    from app.config import settings
    root = Path(tempfile.mkdtemp(prefix="docagent_storage_"))
    saved = {k: getattr(settings, k) for k in
             ("LOCAL_UPLOAD_DIR", "LOCAL_OUTPUT_DIR", "LOCAL_SCHEMAS_DIR")}
    settings.LOCAL_UPLOAD_DIR = root / "uploads"
    settings.LOCAL_OUTPUT_DIR = root / "outputs"
    settings.LOCAL_SCHEMAS_DIR = root / "schemas"
    settings.ensure_storage_dirs()

    src = bs.BACKEND_DIR / "engine" / "demo_accounting.yaml"
    yaml_text = src.read_text(encoding="utf-8")
    clients = root / "schemas" / "clients"
    clients.mkdir(parents=True, exist_ok=True)
    for cid in ("demo_001", "acme_001", "other_002"):
        (clients / f"{cid}.yaml").write_text(yaml_text, encoding="utf-8")

    yield root
    for k, v in saved.items():
        setattr(settings, k, v)


@pytest.fixture(scope="session")
def app(_db_url, _scratch_storage):
    """The real app, with its database pointed at a scratch SQLite file."""
    import sqlalchemy as sa
    from sqlalchemy.orm import sessionmaker

    from app.models import get_db
    from app.models.models import Base

    engine = sa.create_engine(_db_url, connect_args={"check_same_thread": False})
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(engine)

    # main.py's lifespan runs migrations and seeds an admin against the REAL
    # engine, so the app is built directly rather than via TestClient's
    # lifespan. The routers are identical either way — this suite tests
    # routing, auth and validation, not startup.
    from app.main import create_app
    application = create_app()

    def _override():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    application.dependency_overrides[get_db] = _override
    application.state._sessionmaker = Session
    return application


@pytest.fixture(scope="session")
def db(app):
    """A session on the same scratch database the app is using."""
    s = app.state._sessionmaker()
    yield s
    s.close()


@pytest.fixture(scope="session")
def client(app):
    from fastapi.testclient import TestClient
    return TestClient(app)


# ── users ────────────────────────────────────────────────────────────────────
# Four principals, covering every branch the RBAC code has:
#   super   admin with NO client_id  — sees and acts across all tenants
#   acme    admin WITH client_id     — company admin for acme
#   acme2   client in the same tenant as acme
#   other   client in a DIFFERENT tenant — the one who must be kept out

def _mkuser(db, username, role, client_id):
    from app.core.auth import hash_password
    from app.models.models import User
    u = db.query(User).filter(User.username == username).first()
    if u:
        return u
    # display_name is nullable=False with no server default, so it must be set
    # explicitly — the app's own _seed_admin does the same.
    u = User(username=username, display_name=username,
             password_hash=hash_password("pw-" + username),
             role=role, client_id=client_id, is_active=True)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture(scope="session")
def users(db):
    return {
        "super": _mkuser(db, "super", "admin", None),
        "acme": _mkuser(db, "acme_admin", "admin", "acme_001"),
        "acme2": _mkuser(db, "acme_user", "client", "acme_001"),
        "other": _mkuser(db, "other_user", "client", "other_002"),
    }


@pytest.fixture(scope="session")
def auth(users):
    """name -> Authorization header for that principal."""
    from app.core.auth import create_access_token
    out = {}
    for name, u in users.items():
        tok = create_access_token({"sub": str(u.id), "role": u.role,
                                   "client_id": u.client_id})
        out[name] = {"Authorization": f"Bearer {tok}"}
    return out


@pytest.fixture(scope="session")
def templates(db, users):
    """One template per interesting ownership case."""
    import json

    from app.models.models import ColumnTemplate
    grid = json.dumps({
        "cells": {"0,0": {"value": "Invoice Number", "style": {}},
                  "0,1": {"value": "", "style": {}},
                  "1,0": {"value": "Total", "style": {}},
                  "1,1": {"value": "", "style": {}}},
        "colWidths": [160, 160], "merges": {}, "repeatRows": [],
    })
    made = {}
    spec = [
        ("acme_private", users["acme"].id, "acme_001", False, False),
        ("acme_shared", users["acme"].id, "acme_001", True, False),
        ("system_default", users["super"].id, None, False, True),
        ("other_private", users["other"].id, "other_002", False, False),
    ]
    for name, uid, cid, shared, default in spec:
        t = db.query(ColumnTemplate).filter(ColumnTemplate.name == name).first()
        if not t:
            t = ColumnTemplate(name=name, document_type="sales_invoice",
                               description=grid, columns_json="[]",
                               user_id=uid, client_id=cid,
                               is_shared=shared, is_default=default)
            db.add(t)
            db.commit()
            db.refresh(t)
        made[name] = t
    return made


@pytest.fixture
def pdf_bytes():
    """A real one-page PDF, so uploads exercise the true path."""
    p = bs.PDF_DIR / "INV-2024-0031.pdf"
    return p.read_bytes()
