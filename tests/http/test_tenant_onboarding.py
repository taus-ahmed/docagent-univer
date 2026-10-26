"""
Onboarding a firm (B1): the script, the platform-admin routes, the one-time
password and its forced change, and deactivating a firm.

The script runs as a subprocess against a throwaway SQLite file and scratch
storage, exactly as an operator would run it — never against a real database.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

SCRIPT = bs.REPO_DIR / "scripts" / "create_tenant.py"


def _run(args, env_extra, cwd):
    env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
    env.update({"PYTHONIOENCODING": "utf-8", **env_extra})
    r = subprocess.run([sys.executable, str(SCRIPT), *args], cwd=cwd, env=env,
                       capture_output=True, timeout=120)
    return r.returncode, r.stdout.decode("utf-8"), r.stderr.decode("utf-8")


ARGS = ["--firm-id", "onb_firm", "--firm-name", "Onboard Firm",
        "--admin-username", "onb_admin"]


@pytest.fixture
def scratch(tmp_path):
    url = f"sqlite:///{(tmp_path / 'onb.db').as_posix()}"
    env = {"DATABASE_URL": url, "LOCAL_UPLOAD_DIR": str(tmp_path / "u"),
           "LOCAL_OUTPUT_DIR": str(tmp_path / "o"),
           "LOCAL_SCHEMAS_DIR": str(tmp_path / "s"), "STORAGE_BACKEND": "local"}
    return url, env, tmp_path


class TestTheScript:
    def test_host_class(self):
        sys.path.insert(0, str(bs.REPO_DIR / "scripts"))
        from create_tenant import host_class
        assert host_class("sqlite:///x.db") == "local"
        assert host_class("postgresql://u:p@localhost:5432/d") == "local"
        assert host_class("postgresql://u:p@db/d") == "local"
        assert host_class("postgresql://u:p@db.example.net:5432/d") == "remote"

    def test_refuses_without_a_database(self, scratch):
        url, env, tmp = scratch
        env.pop("DATABASE_URL")
        code, out, err = _run(ARGS + ["--confirm-database", "local"], env, tmp)
        assert code == 2 and "DATABASE_URL is not set" in err

    def test_refuses_the_wrong_host_class_and_never_prints_the_url(self, scratch):
        url, env, tmp = scratch
        env["DATABASE_URL"] = "postgresql://someone:s3cret-pw@prod.example.net:5432/live"
        code, out, err = _run(ARGS + ["--confirm-database", "local"], env, tmp)
        assert code == 2 and "this database is remote" in err
        for secret in ("s3cret-pw", "prod.example.net", "someone", "live"):
            assert secret not in out + err

    def test_creates_the_firm_once_and_prints_the_password_once(self, scratch):
        import sqlalchemy as sa
        url, env, tmp = scratch
        code, out, err = _run(ARGS + ["--confirm-database", "local"], env, tmp)
        assert code == 0, err
        lines = out.splitlines()
        i = lines.index("ONE-TIME PASSWORD (shown once, not stored anywhere readable):")
        pw = lines[i + 1].strip()
        assert len(pw) >= 20 and out.count(pw) == 1 and pw not in err
        assert url not in out + err
        eng = sa.create_engine(url)
        with eng.connect() as c:
            row = c.execute(sa.text("select role, client_id, password_hash from users "
                                    "where username='onb_admin'")).one()
            assert row[0] == "admin" and row[1] == "onb_firm"
            assert pw not in row[2] and row[2].startswith("otp$")
            assert c.execute(sa.text("select client_name from client_schemas "
                                     "where client_id='onb_firm'")).scalar() == "Onboard Firm"
        eng.dispose()
        assert (tmp / "schemas" / "clients" / "onb_firm.yaml").exists()   # cwd-relative root
        code, out, err = _run(ARGS + ["--confirm-database", "local"], env, tmp)
        assert code == 2 and "already exists" in err

    def test_refuses_an_unsafe_firm_id(self, scratch):
        url, env, tmp = scratch
        args = ["--firm-id", "../x", "--firm-name", "X", "--admin-username", "xx_admin",
                "--confirm-database", "local"]
        code, out, err = _run(args, env, tmp)
        assert code == 2 and "firm id" in err


# ── the platform-admin routes and the forced change ─────────────────────────

def _login(client, username, password):
    from app.api.routes import auth as A
    with A._lock:
        A._fail_counts.clear(); A._lockout_until.clear()
    return client.post("/api/auth/login", json={"username": username, "password": password})


@pytest.fixture(scope="module")
def made(client, auth):
    r = client.post("/api/admin/tenants", headers=auth["super"],
                    json={"client_id": "onb_api_firm", "client_name": "API Firm",
                          "admin_username": "onb_api_admin"})
    assert r.status_code == 201, r.text
    return r.json()


class TestTheRoutes:
    def test_only_the_platform_admin_creates_a_firm(self, client, auth):
        for who in ("acme", "acme2", "other"):
            r = client.post("/api/admin/tenants", headers=auth[who],
                            json={"client_id": "onb_nope", "client_name": "N",
                                  "admin_username": "onb_nope_admin"})
            assert r.status_code == 403, (who, r.text)

    def test_a_firm_cannot_be_created_twice(self, client, auth, made):
        r = client.post("/api/admin/tenants", headers=auth["super"],
                        json={"client_id": "onb_api_firm", "client_name": "again",
                              "admin_username": "onb_other_admin"})
        assert r.status_code == 409

    def test_the_one_time_password_signs_in_but_opens_nothing_else(self, client, made):
        r = _login(client, "onb_api_admin", made["one_time_password"])
        assert r.status_code == 200, r.text
        assert r.json()["user"]["must_change_password"] is True
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        assert client.get("/api/auth/me", headers=h).status_code == 200
        for m, p in (("GET", "/api/jobs"), ("GET", "/api/templates"),
                     ("GET", "/api/admin/users"), ("PUT", "/api/auth/me")):
            got = client.request(m, p, headers=h, json={})
            assert got.status_code == 403 and "one-time password" in got.text, (m, p)

    def test_changing_it_opens_the_account(self, client, made):
        r = _login(client, "onb_api_admin", made["one_time_password"])
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        bad = client.post("/api/auth/change-password", headers=h,
                          json={"current_password": "wrong", "new_password": "x" * 14})
        assert bad.status_code == 400
        short = client.post("/api/auth/change-password", headers=h,
                            json={"current_password": made["one_time_password"],
                                  "new_password": "short"})
        assert short.status_code == 422
        ok = client.post("/api/auth/change-password", headers=h,
                         json={"current_password": made["one_time_password"],
                               "new_password": "a-long-new-password-1"})
        assert ok.status_code == 200, ok.text
        assert ok.json()["must_change_password"] is False
        assert client.get("/api/jobs", headers=h).status_code == 200
        assert _login(client, "onb_api_admin", made["one_time_password"]).status_code == 401
        assert _login(client, "onb_api_admin", "a-long-new-password-1").status_code == 200

    def test_a_user_created_with_a_temporary_password_must_change_it(self, client, auth):
        r = client.post("/api/admin/users", headers=auth["acme"],
                        json={"username": "onb_temp_user", "display_name": "t",
                              "password": "temporary-pass-1", "client_id": "acme_001",
                              "must_change_password": True})
        assert r.status_code == 201 and r.json()["must_change_password"] is True
        t = _login(client, "onb_temp_user", "temporary-pass-1").json()["access_token"]
        assert client.get("/api/jobs", headers={"Authorization": f"Bearer {t}"}).status_code == 403

    def test_the_platform_admin_lists_firms_with_their_usage(self, client, auth, made):
        r = client.get("/api/admin/tenants", headers=auth["super"])
        assert r.status_code == 200
        row = {t["client_id"]: t for t in r.json()}["onb_api_firm"]
        assert row["users"] == 1 and row["active_users"] == 1
        assert {"pages_used", "page_limit"} <= set(row["usage"])
        assert client.get("/api/admin/tenants", headers=auth["acme"]).status_code == 403

    def test_deactivating_a_firm_signs_out_every_user(self, client, auth, made, db):
        r = _login(client, "onb_api_admin", "a-long-new-password-1")
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        assert client.post("/api/admin/tenants/onb_api_firm/deactivate",
                           headers=auth["acme"]).status_code == 403
        d = client.post("/api/admin/tenants/onb_api_firm/deactivate", headers=auth["super"])
        assert d.status_code == 200 and d.json()["users_changed"] == 1
        assert client.get("/api/jobs", headers=h).status_code == 401
        assert _login(client, "onb_api_admin", "a-long-new-password-1").status_code in (401, 403)
        a = client.post("/api/admin/tenants/onb_api_firm/activate", headers=auth["super"])
        assert a.status_code == 200 and a.json()["users_changed"] == 1
        assert client.post("/api/admin/tenants/no_such_firm/deactivate",
                           headers=auth["super"]).status_code == 404
