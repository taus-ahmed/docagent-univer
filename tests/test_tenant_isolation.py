"""Accounts/security audit: two ordinary users cannot cross firm boundaries.

The larger HTTP isolation suite owns the canonical route inventory and rich
two-firm fixture.  This audit-facing test deliberately reuses both: user B
calls every persistent id-taking route with user A's ids through TestClient,
and the response must be indistinguishable from the same call with an id that
does not exist.  A route added to the app without being classified also fails.
"""
from __future__ import annotations

import pytest

# These are the existing real-ASGI, scratch-database fixtures.  Importing the
# fixture functions (rather than registering the nested conftest as a plugin)
# keeps this requested top-level test runnable both alone and in the full suite.
from tests.http.conftest import (  # noqa: F401
    _db_url,
    _scratch_storage,
    app,
    client,
    db,
)
from tests.http.test_tenant_isolation_all_routes import (  # noqa: F401
    A,
    B,
    BODIES,
    ID_ROUTES,
    MISSING_IDS,
    ROUTES,
    _a_ids,
    _fill,
    _inert,
    _norm,
    _scan_bytes,
    firms,
)


# Empty after the audit run.  If a current leak is found, put only that route
# here: the generated parameter becomes strict xfail and its reason names the
# exact route/rule.  An unanticipated future regression remains a hard failure.
CURRENT_LEAKS: dict[tuple[str, str], str] = {}


def _route_case(route: tuple[str, str]):
    method, path = route
    reason = CURRENT_LEAKS.get(route)
    if reason:
        return pytest.param(
            route,
            id=f"{method} {path}",
            marks=pytest.mark.xfail(
                strict=True,
                reason=f"TENANT ISOLATION -- {method} {path}: {reason}",
            ),
        )
    return pytest.param(route, id=f"{method} {path}")


ID_CASES = [_route_case(route) for route in ID_ROUTES]


def test_inventory_classifies_every_path_parameter_route(app):
    """Every path parameter is a persistent id probe or a demo file name.

    Demo sample names are resolved only inside the signed-in demo tenant's
    fixed whitelist; the canonical suite classifies and tests them as ``demo``.
    Everything else with a path parameter must be in ID_ROUTES below.
    """
    from fastapi.routing import APIRoute

    actual = {
        (method, route.path)
        for route in app.routes
        if isinstance(route, APIRoute) and "{" in route.path
        for method in route.methods - {"HEAD", "OPTIONS"}
    }
    demo_names = {route for route, case in ROUTES.items() if case == "demo" and "{" in route[1]}
    assert actual == set(ID_ROUTES) | demo_names


def test_the_two_users_have_separate_job_lists(client, firms):
    a = firms[A]
    b = firms[B]

    a_jobs = client.get("/api/jobs", headers=a.hdr["user"])
    b_jobs = client.get("/api/jobs", headers=b.hdr["user"])

    assert a_jobs.status_code == b_jobs.status_code == 200
    assert a.job in {item["id"] for item in a_jobs.json()}
    assert b.job not in {item["id"] for item in a_jobs.json()}
    assert b.job in {item["id"] for item in b_jobs.json()}
    assert a.job not in {item["id"] for item in b_jobs.json()}


@pytest.mark.parametrize("route", ID_CASES)
def test_user_b_cannot_probe_user_a_ids(client, firms, route):
    """User A's id gives user B exactly the missing-id response."""
    method, path = route
    headers = firms[B].hdr["user"]
    body = BODIES.get(route)
    a_ids = _a_ids(firms)

    got = client.request(method, _fill(path, a_ids), headers=headers, json=body)
    missing = client.request(
        method,
        _fill(path, MISSING_IDS),
        headers=headers,
        json=body,
    )

    assert got.status_code >= 400, (route, got.status_code, got.text[:200])
    assert got.status_code == missing.status_code
    assert _norm(got.text, a_ids) == _norm(missing.text, MISSING_IDS)
    assert not _scan_bytes(_norm(got.text, a_ids).encode())


def test_user_a_records_survive_all_user_b_probes(db, firms):
    """The mutation-shaped probes above did not alter user A's records."""
    from app.models.models import ColumnTemplate, DocumentResult, ExtractionJob, User, WatchFolder

    db.expire_all()
    a = firms[A]
    job = db.get(ExtractionJob, a.job)
    doc = db.get(DocumentResult, a.doc)

    assert job.status == "completed" and not job.marks().get("deleted")
    assert doc is not None and not doc.reviewed
    assert db.get(ColumnTemplate, a.tpl).name == "isoA-template-marker"
    assert db.get(WatchFolder, a.watch).is_active
    assert db.get(User, a.users["user"].id).is_active
