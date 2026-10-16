"""
The demo's activity trail: one row per thing that happened, append-only.

WHY THIS IS NOT A LOG LINE. A demo account is handed to someone outside the
company and comes back with a story about what it did. stdout on Railway is
retained for days and is not queryable per tenant; `users.last_login` keeps one
timestamp and overwrites it every time. A table survives a redeploy, can be
read per client_id, and can be read months later.

FOUR RULES, each of which is a decision rather than a default:

  1. DEMO TENANTS ONLY. `record()` returns immediately unless the user's
     client_id is in DEMO_CLIENT_IDS, so with the variable unset — the shipped
     default — this module writes nothing for anybody, ever.

  2. A FAILED AUDIT WRITE MUST NEVER BREAK THE REQUEST. Every write is wrapped,
     every exception is swallowed with a printed warning, and the write happens
     on a SEPARATE SESSION bound to the same engine. The separate session is
     the part that matters: an INSERT that fails inside the request's own
     session (a missing table, a constraint, a dead connection) leaves that
     session in a failed transaction, and the caller's next `commit()` — the
     one that saves the user's actual work — would fail too. A second session
     cannot do that. It costs one connection from the pool, briefly.

  3. NO DOCUMENT CONTENT. `detail` carries a filename, a byte size, a template
     name, a refusal reason. It never carries extracted values, page text, a
     password, or a token. The helpers here are the only writers, so there is
     one place to check that.

  4. NOTHING READS IT AT RUNTIME. No route returns it, no UI renders it, and
     the history cutoff does not filter it — it is not the demo user's history,
     it is the record of what they did. `scripts/demo_activity_report.py` is
     the only reader.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy.orm import Session as SASession

from app.core.demo import is_demo_client, is_demo_user

# ── the event vocabulary ──────────────────────────────────────────────────────
#
# Closed, and spelled once. A typo in an event name is invisible until someone
# reads the report and finds a gap, so the names are constants.
LOGIN = "login"
LOGIN_FAILED = "login_failed"
UPLOAD = "upload"
SAMPLE_EXTRACT = "sample_extract"
EXPORT = "export"
UPLOAD_REFUSED = "upload_refused"

EVENTS = (LOGIN, LOGIN_FAILED, UPLOAD, SAMPLE_EXTRACT, EXPORT, UPLOAD_REFUSED)

#: Keys `detail` is allowed to carry. A whitelist rather than a blacklist,
#: because the failure mode being guarded against is someone adding a field in
#: a hurry — `{"value": ...}` or `{"text": ...}` — and a blacklist would not
#: have a name for the thing it had never seen.
_ALLOWED_DETAIL_KEYS = frozenset({
    "files",            # [{"filename": str, "size_bytes": int}]
    "filename",         # one file, for the sample-document route
    "size_bytes",
    "template",         # the template's NAME, never its grid
    "template_id",
    "reason",           # a refusal: scanned | too_large | quota | ...
    "status",           # the HTTP status the refusal answered with
    "kind",             # which export: template | zip | combined | perfile
    "documents",        # how many documents an export covered
    "username",         # a failed login names the account it tried
    "ip",
    "count",
    "options_requested",
})


def _clean(detail: Optional[dict]) -> Optional[str]:
    """`detail` as a JSON string, with anything unrecognised dropped.

    Dropping is deliberate: an unknown key is a key nobody has checked for
    document content, and an audit row with a missing field is better than an
    audit row that quietly stores a customer's data.
    """
    if not detail:
        return None
    kept = {k: v for k, v in detail.items() if k in _ALLOWED_DETAIL_KEYS}
    dropped = sorted(set(detail) - set(kept))
    if dropped:
        print(f"[DEMO-AUDIT] refusing to store unrecognised detail key(s) "
              f"{dropped} — add them to _ALLOWED_DETAIL_KEYS if they are safe",
              flush=True)
    try:
        return json.dumps(kept, default=str, ensure_ascii=False)
    except Exception:
        return None


def _write(bind, *, client_id: str, event: str, user_id=None, job_id=None,
           detail: Optional[dict] = None) -> None:
    from app.models.models import DemoActivity

    with SASession(bind=bind) as session:
        session.add(DemoActivity(
            user_id=user_id, client_id=client_id, event=event,
            job_id=job_id, detail=_clean(detail)))
        session.commit()


def record(db, user, event: str, *, job_id: Optional[int] = None,
           detail: Optional[dict] = None) -> None:
    """Record one event about a demo user. Never raises.

    `db` is the request's session and is used ONLY for its engine — see rule 2
    in the module docstring. Pass the session you have; nothing is added to it.
    """
    try:
        if not is_demo_user(user):
            return
        _write(db.get_bind(), client_id=user.client_id, event=event,
               user_id=getattr(user, "id", None), job_id=job_id, detail=detail)
    except Exception as exc:                      # noqa: BLE001 — see rule 2
        print(f"[DEMO-AUDIT] could not record {event!r}: "
              f"{type(exc).__name__}: {exc}", flush=True)


def record_for_client(db, client_id: Optional[str], event: str, *,
                      user_id=None, detail: Optional[dict] = None) -> None:
    """Record an event when there is no User object to hand.

    The failed-login path: the password did not match, so there is a row but no
    authenticated user. It still has a client_id, and that is what decides
    whether this is a demo event at all.

    ⚠ A failed login for a username that does NOT EXIST records nothing,
    because nothing identifies it as an attempt on the demo tenant rather than
    on any other account. That is a real gap in the trail and it is better than
    the alternative, which is writing a row against a guessed client_id.
    """
    try:
        if not is_demo_client(client_id):
            return
        _write(db.get_bind(), client_id=client_id, event=event,
               user_id=user_id, job_id=None, detail=detail)
    except Exception as exc:                      # noqa: BLE001
        print(f"[DEMO-AUDIT] could not record {event!r}: "
              f"{type(exc).__name__}: {exc}", flush=True)


def refusal_detail(exc, filename: Optional[str] = None) -> dict:
    """The `detail` for a refused upload, read off the exception itself.

    `core/demo.py::_demo_error` tags each refusal with a machine-readable
    `demo_reason`, so this does not have to pattern-match the sentence shown to
    the user — a sentence that is deliberately written for an investor and will
    be reworded.
    """
    out: dict[str, Any] = {
        "reason": getattr(exc, "demo_reason", "unknown"),
        "status": getattr(exc, "status_code", None),
    }
    if filename:
        out["filename"] = filename
    return out
