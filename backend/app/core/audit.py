"""Overnight H1 — the audit log: one append-only row per security action.

    record(db, "login.failed", actor=user_or_None, client_id=..., target=...)

What is written: the action, the actor (account id and username), the firm,
the target (a type and an id — a job id, a user id, a template id), the
outcome and the request id. What is NEVER written: document contents,
extracted values, file names, passwords, tokens, e-mail addresses, IP
addresses, or a username typed at a failed sign-in that matches no account
(that string may be a password typed into the wrong box).

A failure to write the audit row is logged as an ERROR and never breaks the
action being audited: a sign-in must not fail because the audit insert did.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("docagent.audit")

#: The vocabulary. A new action is added here first, so the read endpoint's
#: filter and the admin page can list them.
ACTIONS = (
    "login.ok", "login.failed", "logout", "logout.everywhere",
    "user.create", "user.update", "user.disable", "user.enable", "user.delete",
    "password.change", "password.reset",
    "template.create", "template.update", "template.delete",
    "job.create", "job.delete",
    "export.download",
    "review.mark", "review.edit", "review.add_row", "review.approve",
)


def _request_id() -> Optional[str]:
    try:
        from app.core.observability import REQUEST_ID
        rid = REQUEST_ID.get()
        return None if rid in (None, "-") else str(rid)[:64]
    except Exception:
        return None


def record(db, action: str, *, actor=None, client_id: Optional[str] = None,
           target_type: Optional[str] = None, target_id=None,
           outcome: str = "ok") -> None:
    """Append one audit event. `actor` is a User (or None); `client_id`
    defaults to the actor's firm. Commits its own row."""
    from app.models.models import AuditEvent
    if action not in ACTIONS:
        logger.error("audit: unknown action %r not recorded", action)
        return
    try:
        evt = AuditEvent(
            client_id=(client_id if client_id is not None
                       else getattr(actor, "client_id", None)),
            actor_id=getattr(actor, "id", None),
            actor=(str(getattr(actor, "username", "") or "")[:100] or None),
            action=action,
            target_type=(str(target_type)[:50] if target_type else None),
            target_id=(str(target_id)[:100] if target_id is not None else None),
            outcome=str(outcome or "ok")[:20],
            request_id=_request_id(),
        )
        db.add(evt)
        db.commit()
    except Exception as e:                     # never break the audited action
        try:
            db.rollback()
        except Exception:
            pass
        logger.error("audit: %s not recorded (%s)", action, type(e).__name__)


# ── routes audited by the middleware ────────────────────────────────────────
#
# (method, route template) -> (action, target type, where the target id is:
# a path parameter name, or "body:<key>" for the id a create returns).
# Sign-in, sign-out and user administration are recorded inside their
# routes (they know things a middleware cannot: which account a failed
# password belonged to, what changed on a user).
ROUTE_ACTIONS = {
    ("POST", "/api/templates"): ("template.create", "template", "body:id"),
    ("PUT", "/api/templates/{template_id}"): ("template.update", "template", "template_id"),
    ("DELETE", "/api/templates/{template_id}"): ("template.delete", "template", "template_id"),
    ("POST", "/api/extract/upload"): ("job.create", "job", "body:job_id"),
    ("DELETE", "/api/jobs/{job_id}"): ("job.delete", "job", "job_id"),
    ("DELETE", "/api/jobs/{job_id}/data"): ("job.delete", "job", "job_id"),
    ("GET", "/api/jobs/{job_id}/export"): ("export.download", "job", "job_id"),
    ("GET", "/api/jobs/{job_id}/export/zip"): ("export.download", "job", "job_id"),
    ("POST", "/api/export/combined"): ("export.download", "job", None),
    ("POST", "/api/export/perfile"): ("export.download", "job", None),
    ("POST", "/api/jobs/{job_id}/docs/{doc_id}/review"): ("review.mark", "document", "doc_id"),
    ("PUT", "/api/jobs/{job_id}/docs/{doc_id}"): ("review.edit", "document", "doc_id"),
    ("PATCH", "/api/jobs/{job_id}/docs/{doc_id}/fields/{ref}"): ("review.edit", "document", "doc_id"),
    ("PATCH", "/api/jobs/{job_id}/docs/{doc_id}/rows/{table}/{row}"): ("review.edit", "document", "doc_id"),
    ("POST", "/api/jobs/{job_id}/docs/{doc_id}/rows/{table}"): ("review.add_row", "document", "doc_id"),
    ("POST", "/api/jobs/{job_id}/docs/{doc_id}/approve"): ("review.approve", "document", "doc_id"),
}


def install_middleware(app) -> None:
    """Record ROUTE_ACTIONS after each response. An unauthenticated request
    (401) is not recorded: there is no actor and no firm to file it under."""
    import json as _json

    from fastapi import Request
    from fastapi.responses import Response

    @app.middleware("http")
    async def _audit(request: Request, call_next):
        response = await call_next(request)
        route = request.scope.get("route")
        key = (request.method, getattr(route, "path", None))
        spec = ROUTE_ACTIONS.get(key)
        if spec is None or response.status_code == 401:
            return response
        action, ttype, where = spec
        target = None
        if where and where.startswith("body:") and response.status_code < 400:
            body = b"".join([chunk async for chunk in response.body_iterator])
            try:
                target = (_json.loads(body or b"{}") or {}).get(where[5:])
            except (ValueError, AttributeError):
                target = None
            response = Response(content=body, status_code=response.status_code,
                                headers=dict(response.headers),
                                media_type=response.media_type)
        elif where:
            target = (request.path_params or {}).get(where)
        _record_from_request(request, action, ttype, target,
                             "ok" if response.status_code < 400 else "failed")
        return response


def _record_from_request(request, action, ttype, target, outcome) -> None:
    from fastapi.security import HTTPAuthorizationCredentials
    from app.models.models import SessionLocal
    sm = getattr(request.app.state, "_sessionmaker", None) or SessionLocal
    auth = request.headers.get("authorization") or ""
    if not auth.lower().startswith("bearer "):
        return
    db = sm()
    try:
        from app.core.auth import get_current_user
        try:
            user = get_current_user(HTTPAuthorizationCredentials(
                scheme="Bearer", credentials=auth.split(" ", 1)[1].strip()), db)
        except Exception:
            return
        record(db, action, actor=user, target_type=ttype, target_id=target,
               outcome=outcome)
    finally:
        db.close()
