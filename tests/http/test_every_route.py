"""
Every API route, checked for the property that has no exceptions: you cannot
call it without a valid token.

Routes are enumerated from the running app rather than listed here, so a route
added tomorrow is covered tomorrow. That is the point — a hand-written list of
40 paths is out of date the first time someone adds the 41st, and the whole
reason this suite exists is that nobody was checking.

PUBLIC is the allowlist, and it is deliberately short. Adding to it is a
security decision and should look like one in the diff.
"""
import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

PUBLIC = {
    ("POST", "/api/auth/login"),        # issues the token; cannot require one

    # Found by this suite on its first run: logout takes no token and answers
    # 200 to anyone. It is a stateless no-op — JWT has no server-side session
    # to end, and the body just tells the client to discard its token — so it
    # discloses nothing and changes nothing. Left public deliberately: adding
    # auth would make logout fail for exactly the user most likely to press
    # it, the one whose token has already expired.
    ("POST", "/api/auth/logout"),
}

# Path params filled with values that are syntactically valid but cannot exist,
# so an authorised call would 404 rather than mutate anything real.
_FILLERS = {"job_id": "999999", "doc_id": "999999", "template_id": "999999",
            "user_id": "999999", "watch_id": "999999", "folder_id": "nope",
            "client_id": "no_such_client"}


def _routes(app):
    import re
    from fastapi.routing import APIRoute
    out = []
    for r in app.routes:
        if not isinstance(r, APIRoute) or not r.path.startswith("/api/"):
            continue
        path = r.path
        for name, val in _FILLERS.items():
            path = path.replace("{" + name + "}", val)
        path = re.sub(r"\{[^}]+\}", "1", path)          # any param not listed
        for method in sorted(r.methods - {"HEAD", "OPTIONS"}):
            out.append((method, r.path, path))
    return sorted(set(out))


@pytest.fixture(scope="module")
def routes(app):
    rs = _routes(app)
    assert len(rs) >= 35, f"only found {len(rs)} routes — enumeration broke"
    return rs


def _call(client, method, path, headers):
    return client.request(method, path, headers=headers, json={})


class TestNothingIsReachableWithoutAToken:
    def test_every_route_refuses_an_anonymous_caller(self, client, routes):
        leaked = []
        for method, template, path in routes:
            if (method, template) in PUBLIC:
                continue
            r = _call(client, method, path, {})
            if r.status_code not in (401, 403):
                leaked.append(f"{method} {template} -> {r.status_code}")
        assert not leaked, (
            "these routes answered an unauthenticated caller with something "
            "other than 401/403:\n  " + "\n  ".join(leaked))

    def test_every_route_refuses_a_malformed_token(self, client, routes):
        bad = {"Authorization": "Bearer not.a.real.jwt"}
        leaked = []
        for method, template, path in routes:
            if (method, template) in PUBLIC:
                continue
            r = _call(client, method, path, bad)
            if r.status_code not in (401, 403):
                leaked.append(f"{method} {template} -> {r.status_code}")
        assert not leaked, "malformed token accepted:\n  " + "\n  ".join(leaked)

    def test_a_token_signed_with_the_wrong_key_is_refused(self, client, routes):
        """The failure mode the SECRET_KEY guard exists to prevent, checked
        from the other end: a token minted with a different secret must not
        verify."""
        from jose import jwt
        forged = jwt.encode({"sub": "1", "role": "admin", "client_id": None},
                            "a-different-secret-entirely", algorithm="HS256")
        headers = {"Authorization": f"Bearer {forged}"}
        leaked = []
        for method, template, path in routes:
            if (method, template) in PUBLIC:
                continue
            r = _call(client, method, path, headers)
            if r.status_code not in (401, 403):
                leaked.append(f"{method} {template} -> {r.status_code}")
        assert not leaked, "forged token accepted:\n  " + "\n  ".join(leaked)

    def test_an_expired_token_is_refused(self, client):
        from datetime import datetime, timedelta

        from jose import jwt

        from app.config import settings
        tok = jwt.encode(
            {"sub": "1", "role": "admin", "client_id": None,
             "exp": datetime.utcnow() - timedelta(hours=1)},
            settings.SECRET_KEY, algorithm=settings.ALGORITHM)
        r = client.get("/api/templates",
                       headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 401, r.text


class TestNoRouteReturns500ToAnAuthenticatedCaller:
    def test_absent_resources_are_404_not_a_crash(self, client, auth, routes):
        """A 500 is a bug leaking to the client. Every id used here is one
        that cannot exist, so the honest answers are 404, 400, 405 or 422.

        502/503 are permitted: they say an OPTIONAL upstream (Google Drive) is
        unavailable, which is a true statement about the deployment rather
        than an unhandled exception. Before this suite those routes answered
        500 with the raw ImportError text in the body.
        """
        crashed = []
        for method, template, path in routes:
            if (method, template) in PUBLIC:
                continue
            if method == "POST" and template == "/api/extract/upload":
                continue                     # needs multipart; covered elsewhere
            r = _call(client, method, path, auth["acme"])
            if r.status_code == 500 or r.status_code > 503:
                crashed.append(f"{method} {template} -> {r.status_code} "
                               f"{r.text[:120]}")
        assert not crashed, "unhandled errors:\n  " + "\n  ".join(crashed)

    def test_no_route_hands_an_internal_error_to_the_client(self, client, auth,
                                                            routes):
        """Drive answered 500 with "No module named 'gdrive'" in the body —
        internal module paths given to whoever asked."""
        leaks = []
        for method, template, path in routes:
            if (method, template) in PUBLIC:
                continue
            if method == "POST" and template == "/api/extract/upload":
                continue
            body = _call(client, method, path, auth["acme"]).text.casefold()
            for tell in ("no module named", "traceback (most recent",
                         "sqlalchemy.exc", "site-packages"):
                if tell in body:
                    leaks.append(f"{method} {template}: {body[:110]}")
                    break
        assert not leaks, "internal detail in responses:\n  " + "\n  ".join(leaks)


class TestPublicRoutesAreDeliberate:
    def test_login_is_reachable_without_a_token(self, client):
        r = client.post("/api/auth/login",
                        json={"username": "nobody", "password": "wrong"})
        assert r.status_code != 403
        assert r.status_code in (401, 422), r.text

    def test_the_allowlist_matches_reality(self, client, routes):
        """If a route stops requiring auth, PUBLIC must be updated on purpose
        — this test is what forces that conversation."""
        actually_public = set()
        for method, template, path in routes:
            r = _call(client, method, path, {})
            if r.status_code not in (401, 403):
                actually_public.add((method, template))
        assert actually_public == {p for p in PUBLIC
                                   if p in {(m, t) for m, t, _ in routes}}, (
            f"public routes changed: {actually_public} vs allowlist {PUBLIC}")
