"""
Google Drive is not part of the demo, and the backend is what says so.

Two reasons the whole of `routes/drive.py` is closed to a demo tenant rather
than just the one obvious route:

  * INGESTION BYPASSES THE DEMO'S RULES. `/api/drive/extract` and the watch
    loop build their own `ExtractionJob` instead of going through
    `extract.py::_start_extraction_job`, so a document arriving by Drive would
    face none of PDF-only, DEMO_MAX_MB, the quota or the scanned-document
    refusal.
  * BROWSING IS NOT HARMLESS. Drive here is a single server-wide OAuth
    credential, so `/api/drive/folders` would show a demo user whatever Drive
    that credential belongs to.

Non-demo users must be untouched, and that is asserted the strongest way
available: the same request is made with DEMO_CLIENT_IDS unset and then set,
and the two answers must be the same.
"""
import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

DRIVE_MSG = "Google Drive is not available in this demo."

# Every route in routes/drive.py, as (method, path, kwargs).
DRIVE_ROUTES = [
    ("get", "/api/drive/auth/status", {}),
    ("post", "/api/drive/auth", {}),
    ("get", "/api/drive/folders/root", {}),
    ("post", "/api/drive/extract?folder_id=abc&client_id=pearx_demo", {}),
    ("get", "/api/watch", {}),
    ("post", "/api/watch", {"json": {"folder_id": "abc", "folder_name": "n",
                                     "client_id": "pearx_demo"}}),
    ("post", "/api/watch/check", {}),
    ("delete", "/api/watch/1", {}),
]


@pytest.mark.parametrize("method,path,kwargs", DRIVE_ROUTES)
class TestADemoAccountCannotReachDrive:
    def test_it_is_403_with_the_exact_sentence(
            self, client, demo_auth, demo_on, method, path, kwargs):
        r = getattr(client, method)(path, headers=demo_auth, **kwargs)
        assert r.status_code == 403, (path, r.status_code, r.text)
        assert r.json()["detail"] == DRIVE_MSG, r.text

    def test_the_refusal_is_tagged_as_a_demo_message(
            self, client, demo_auth, demo_on, method, path, kwargs):
        """So the Extract page shows this sentence instead of replacing it with
        the neutral one (`frontend/lib/demo-error.ts`)."""
        r = getattr(client, method)(path, headers=demo_auth, **kwargs)
        assert r.headers.get("x-demo-notice") == "1", dict(r.headers)

    def test_with_the_variable_unset_the_demo_user_is_not_blocked(
            self, client, demo_auth, method, path, kwargs):
        """No `demo_on`: the shipped default, so this account is an ordinary
        one and Drive answers whatever it answers to anybody."""
        r = getattr(client, method)(path, headers=demo_auth, **kwargs)
        assert r.status_code != 403 or r.json().get("detail") != DRIVE_MSG


@pytest.mark.parametrize("method,path,kwargs", DRIVE_ROUTES)
def test_a_non_demo_user_gets_the_same_answer_either_way(
        client, auth, monkeypatch, method, path, kwargs):
    from app.config import settings

    def shot(n):
        """One request, with a folder id of its own.

        POST /api/watch is a CREATE, and the second identical call is a 409 for
        reasons that have nothing to do with the demo — so each phase gets a
        fresh folder id and the comparison stays about the gate.
        """
        fresh = dict(kwargs)
        if "json" in fresh:
            fresh["json"] = {**fresh["json"], "folder_id": f"cmp-{n}"}
        return getattr(client, method)(
            path.replace("folder_id=abc", f"folder_id=cmp-{n}"),
            headers=auth["acme2"], **fresh)

    monkeypatch.setattr(settings, "DEMO_CLIENT_IDS", "")
    off = shot("off")
    monkeypatch.setattr(settings, "DEMO_CLIENT_IDS", "pearx_demo")
    on = shot("on")
    assert off.status_code == on.status_code, (path, off.text, on.text)
    assert DRIVE_MSG not in off.text and DRIVE_MSG not in on.text


def test_the_gate_is_on_the_router_so_a_new_route_cannot_miss_it():
    """The reason this is a router dependency and not eight calls: the next
    Drive route added is covered without anybody remembering to cover it."""
    from app.api.routes.drive import _drive_not_in_the_demo, router

    names = [d.dependency.__name__ for d in router.dependencies]
    assert _drive_not_in_the_demo.__name__ in names
    # Every route in the file inherits it.
    assert len(router.routes) == len(DRIVE_ROUTES), (
        "a Drive route was added or removed — extend DRIVE_ROUTES above so it "
        "is covered by the tests in this file")
