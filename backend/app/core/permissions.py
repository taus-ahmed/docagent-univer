"""
Who may do what — one function, the matrix as data (docs/proposals/roles.md).

    can(user, action, resource=None) -> bool

Routes ask this instead of spelling `role == "admin" and not client_id` inline.
There is no role table and no migration: the ROLE a user acts as is derived
from the stored `role` string and `client_id`, exactly as the inline checks
derived it before.

    platform_admin   role "admin" with NO client_id (derived, as today)
    tenant_admin     role "admin" with a client_id
    company_admin    legacy role (SQL-only); today's powers, kept as they were
    reviewer         checks and edits values across its own firm's jobs;
                     no templates, schemas, users or system statistics
    user             role "client" — and any role string this module does not
                     know, which is what the inline checks did ("anything else")

Scope: a resource of another tenant is never allowed, whatever the action; the
job routes answer that as 404 (`extract.py::_get_job_or_404`). Making
platform_admin an explicit stored role needs a data migration and is not done.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, status

PLATFORM_ADMIN = "platform_admin"
TENANT_ADMIN = "tenant_admin"
COMPANY_ADMIN = "company_admin"
REVIEWER = "reviewer"
USER = "user"

#: Stored `role` values the API may assign (UserCreate). company_admin stays
#: assignable only through UserUpdate, as before.
ASSIGNABLE_ROLES = ("admin", "client", "reviewer")

_JOB = {"job.view", "job.review", "job.export", "job.upload"}

#: role -> actions it holds. Scope (all / own tenant / own jobs) is separate.
ROLE_ACTIONS: dict[str, frozenset] = {
    PLATFORM_ADMIN: frozenset(_JOB | {
        "job.cancel_any", "job.delete", "tenant.all",
        "template.create", "template.share", "template.manage_tenant",
        "schema.manage", "user.manage", "stats.view",
        "drive.use", "drive.manage_tenant"}),
    TENANT_ADMIN: frozenset(_JOB | {
        "job.cancel_any", "job.delete",
        "template.create", "template.share", "template.manage_tenant",
        "schema.manage", "user.manage", "stats.view",
        "drive.use", "drive.manage_tenant"}),
    COMPANY_ADMIN: frozenset(_JOB | {
        "template.create", "template.share", "template.manage_tenant",
        "drive.use"}),
    REVIEWER: frozenset(_JOB | {"drive.use"}),
    USER: frozenset(_JOB | {"template.create", "drive.use"}),
}

#: Which jobs a role sees: every tenant's, its own tenant's, or its own.
JOB_SCOPE = {PLATFORM_ADMIN: "all", TENANT_ADMIN: "tenant",
             COMPANY_ADMIN: "tenant", REVIEWER: "tenant", USER: "own"}


def role_of(user) -> str:
    """The role a user acts as, derived from the stored role and tenant."""
    role = getattr(user, "role", None)
    if role == "admin":
        return TENANT_ADMIN if getattr(user, "client_id", None) else PLATFORM_ADMIN
    if role in (COMPANY_ADMIN, REVIEWER):
        return role
    return USER


def _same_tenant(a, b) -> bool:
    return bool(a) and a == b


def _sees_job(user, job) -> bool:
    scope = JOB_SCOPE[role_of(user)]
    if scope == "all":
        return True
    if job.user_id is not None and job.user_id == user.id:
        return True
    return scope == "tenant" and _same_tenant(job.client_id, user.client_id)


def _sees_template(user, tpl) -> bool:
    from app.core.demo import is_demo_user
    if role_of(user) == PLATFORM_ADMIN or tpl.user_id == user.id:
        return True
    if tpl.is_shared and _same_tenant(tpl.client_id, user.client_id):
        return True
    return bool(tpl.is_default) and not is_demo_user(user)


def _edits_template(user, tpl) -> bool:
    role = role_of(user)
    if role == PLATFORM_ADMIN:
        return True
    if "template.create" not in ROLE_ACTIONS[role]:
        return False
    if tpl.user_id == user.id:
        return True
    return ("template.manage_tenant" in ROLE_ACTIONS[role]
            and _same_tenant(tpl.client_id, user.client_id))


def can(user, action: str, resource=None) -> bool:
    """May `user` do `action` (to `resource`, when the action names one)?

    Job actions (`job.*`) need the job: the user must see it (scope) and hold
    the action. `job.cancel` is the owner, or an admin holding
    `job.cancel_any`. Template actions `template.view` / `template.edit` need
    the template. Every other action is a plain role check.
    """
    if user is None or not getattr(user, "is_active", True):
        return False
    role = role_of(user)
    held = ROLE_ACTIONS[role]
    if action.startswith("job.") and resource is not None:
        if not _sees_job(user, resource):
            return False
        if action == "job.cancel":
            return "job.cancel_any" in held or resource.user_id == user.id
        return action in held
    if action == "template.view":
        return _sees_template(user, resource)
    if action == "template.edit":
        return _edits_template(user, resource)
    return action in held


def sees_job(user, job) -> bool:
    """Is the job inside the user's scope at all (the 404 question)?"""
    return _sees_job(user, job)


def job_scope(user) -> str:
    """"all", "tenant" or "own" — for the job list query."""
    return JOB_SCOPE[role_of(user)]


#: Internal scope markers, not capabilities a UI shows.
_INTERNAL = {"tenant.all", "drive.manage_tenant", "template.manage_tenant"}


def permissions_of(user) -> list[str]:
    """The actions the user's role holds, for the UI to hide controls with.
    `job.cancel` is listed for everyone: a user may cancel their own job."""
    if user is None or not getattr(user, "is_active", True):
        return []
    held = (ROLE_ACTIONS[role_of(user)] - _INTERNAL) | {"job.cancel"}
    return sorted(held)


def require(action: str):
    """A FastAPI dependency: the signed-in user, or 403 without `action`."""
    from app.core.auth import get_current_user

    def _dep(current_user=Depends(get_current_user)):
        if not can(current_user, action):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="Not permitted for this role")
        return current_user
    _dep.__name__ = f"require_{action.replace('.', '_')}"
    return _dep
