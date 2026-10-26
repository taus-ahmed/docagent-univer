"""
DocAgent v2 — Admin Routes
GET  /api/admin/users         — list all users
POST /api/admin/users         — create user
PUT  /api/admin/users/{id}    — update user
DELETE /api/admin/users/{id}  — deactivate user
GET  /api/admin/stats         — system stats
POST /api/admin/tenants       — create a firm + its first admin (platform admin)
GET  /api/admin/tenants       — firms, user counts, page usage (platform admin)
POST /api/admin/tenants/{id}/deactivate | activate — every user of a firm
"""

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import hash_password, is_one_time
from app.core.permissions import PLATFORM_ADMIN, require, role_of
from app.core.demo import is_demo_user
from app.core.confidence import CONFIDENT_LEVELS
from app.models import get_db, User, ExtractionJob, DocumentResult
from app.schemas.schemas import (
    CLIENT_ID_PATTERN, UserCreate, UserUpdate, UserResponse, SystemStats,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/users", response_model=list[UserResponse])
def list_users(
    db: Session = Depends(get_db),
    current_admin: User = Depends(require("user.manage")),
):
    """List users visible inside the caller's administrative boundary."""
    query = db.query(User)
    if not _is_super_admin(current_admin):
        query = query.filter(User.client_id == current_admin.client_id)
    users = query.order_by(User.created_at.desc()).all()
    return [_user_to_response(u) for u in users]


@router.post("/users", response_model=UserResponse, status_code=201)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(require("user.manage")),
):
    """Create a new user."""
    if (not _is_super_admin(current_admin)
            and payload.client_id != current_admin.client_id):
        raise HTTPException(
            status_code=403,
            detail="Tenant admins can create users only in their own tenant",
        )

    existing = db.query(User).filter(User.username == payload.username).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Username '{payload.username}' already exists")

    if payload.email:
        email_exists = db.query(User).filter(User.email == payload.email).first()
        if email_exists:
            raise HTTPException(status_code=409, detail=f"Email '{payload.email}' already registered")

    user = User(
        username=payload.username,
        display_name=payload.display_name,
        email=payload.email,
        password_hash=hash_password(payload.password,
                                    one_time=payload.must_change_password),
        role=payload.role,
        client_id=payload.client_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _user_to_response(user)


@router.put("/users/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(require("user.manage")),
):
    """Update a user's details."""
    query = db.query(User).filter(User.id == user_id)
    if not _is_super_admin(current_admin):
        query = query.filter(User.client_id == current_admin.client_id)
    user = query.first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if payload.display_name is not None:
        user.display_name = payload.display_name
    if payload.email is not None:
        user.email = payload.email
    if payload.password is not None:
        if len(payload.password) < 6:
            raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
        user.password_hash = hash_password(
            payload.password, one_time=bool(payload.must_change_password))
    if payload.role is not None:
        if user.id == current_admin.id and payload.role != user.role:
            raise HTTPException(status_code=400, detail="Cannot change your own role")
        user.role = payload.role
    if "client_id" in payload.model_fields_set:
        if not _is_super_admin(current_admin):
            raise HTTPException(
                status_code=400,
                detail="Tenant admins cannot change a user's client_id",
            )
        user.client_id = payload.client_id
    if payload.is_active is not None:
        if user.id == current_admin.id:
            raise HTTPException(status_code=400, detail="Cannot deactivate yourself")
        user.is_active = payload.is_active

    db.commit()
    db.refresh(user)
    return _user_to_response(user)


@router.delete("/users/{user_id}")
def deactivate_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_admin: User = Depends(require("user.manage")),
):
    """Soft-delete (deactivate) a user."""
    if user_id == current_admin.id:
        raise HTTPException(status_code=400, detail="Cannot deactivate yourself")

    query = db.query(User).filter(User.id == user_id)
    if not _is_super_admin(current_admin):
        query = query.filter(User.client_id == current_admin.client_id)
    user = query.first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_active = False
    db.commit()
    return {"message": f"User '{user.username}' deactivated", "id": user_id}


@router.get("/stats", response_model=SystemStats)
def get_stats(
    db: Session = Depends(get_db),
    current_admin: User = Depends(require("stats.view")),
):
    """Statistics inside the caller's administrative boundary."""
    seven_days_ago = datetime.utcnow() - timedelta(days=7)

    jobs = db.query(ExtractionJob)
    docs = db.query(DocumentResult).join(
        ExtractionJob, DocumentResult.job_id == ExtractionJob.id)
    users = db.query(User)
    if not _is_super_admin(current_admin):
        jobs = jobs.filter(ExtractionJob.client_id == current_admin.client_id)
        docs = docs.filter(ExtractionJob.client_id == current_admin.client_id)
        users = users.filter(User.client_id == current_admin.client_id)

    total_jobs = jobs.count()
    total_docs = docs.count()
    total_users = users.filter(User.is_active == True).count()
    reviewed = docs.filter(DocumentResult.reviewed == True).count()
    pending_review = docs.filter(
        DocumentResult.needs_review == True,
        DocumentResult.reviewed == False,
    ).count()
    # Documents we can stand behind. Both HIGH (templated: grounded AND the
    # user authored the slot) and GROUNDED (inferred: grounded, but the model
    # named the slot) count here — the distinction matters per cell, in the UI
    # and the export; at the document-stat level "confident" is the question.
    # Testing == "high" here would have silently dropped every no-template
    # document from the count the moment the vocabulary split.
    high_conf = docs.filter(
        DocumentResult.overall_confidence.in_(CONFIDENT_LEVELS)
    ).count()
    jobs_7d = jobs.filter(
        ExtractionJob.created_at >= seven_days_ago
    ).count()

    return SystemStats(
        total_jobs=total_jobs,
        total_documents=total_docs,
        total_users=total_users,
        documents_reviewed=reviewed,
        documents_pending_review=pending_review,
        high_confidence_docs=high_conf,
        jobs_last_7_days=jobs_7d,
    )


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _is_super_admin(user: User) -> bool:
    return role_of(user) == PLATFORM_ADMIN


def _user_to_response(u: User) -> UserResponse:
    return UserResponse(
        id=u.id,
        username=u.username,
        display_name=u.display_name,
        email=u.email,
        role=u.role,
        client_id=u.client_id,
        is_demo=is_demo_user(u),
        is_active=u.is_active,
        must_change_password=is_one_time(u.password_hash),
    )


# ── firms (platform admin) ───────────────────────────────────────────────────

class TenantCreate(BaseModel):
    client_id: str = Field(..., pattern=CLIENT_ID_PATTERN)
    client_name: str = Field(..., min_length=1, max_length=200)
    admin_username: str = Field(..., min_length=3, max_length=50)
    admin_display_name: Optional[str] = None


@router.post("/tenants", status_code=201)
def create_tenant_route(payload: TenantCreate, db: Session = Depends(get_db),
                        current_admin: User = Depends(require("tenant.all"))):
    """A new firm: its schema (the default accounting schema, renamed) and its
    first administrator, whose ONE-TIME password is in this response and
    nowhere else (`core/tenants.py`). Platform admin only."""
    from app.core.tenants import TenantError, create_tenant
    try:
        return create_tenant(db, payload.client_id, payload.client_name,
                             payload.admin_username, payload.admin_display_name,
                             created_by=current_admin.id)
    except TenantError as e:
        code = 409 if ("exists" in str(e) or "taken" in str(e)) else 400
        raise HTTPException(status_code=code, detail=str(e))


@router.get("/tenants")
def list_tenants(db: Session = Depends(get_db),
                 _: User = Depends(require("tenant.all"))):
    """Every firm (a schema, or users carrying its client_id), with its user
    counts and this month's page usage. Platform admin only."""
    from app.core.usage import usage
    from app.models.models import ClientSchema
    names = {s.client_id: s.client_name for s in db.query(ClientSchema).all()}
    ids = set(names) | {c for (c,) in db.query(User.client_id).distinct() if c}
    out = []
    for cid in sorted(ids):
        users = db.query(User).filter(User.client_id == cid)
        out.append({"client_id": cid, "client_name": names.get(cid),
                    "users": users.count(),
                    "active_users": users.filter(User.is_active == True).count(),
                    "usage": usage(db, cid)})
    return out


def _set_tenant(db, client_id: str, active: bool) -> dict:
    from app.core.tenants import set_tenant_active
    from app.models.models import ClientSchema
    if not (db.query(User).filter(User.client_id == client_id).first()
            or db.query(ClientSchema).filter(ClientSchema.client_id == client_id).first()):
        raise HTTPException(status_code=404, detail="Firm not found")
    return {"client_id": client_id, "active": active,
            "users_changed": set_tenant_active(db, client_id, active)}


@router.post("/tenants/{client_id}/deactivate")
def deactivate_tenant(client_id: str, db: Session = Depends(get_db),
                      _: User = Depends(require("tenant.all"))):
    """Every user of the firm is deactivated: no sign-in, every token they
    hold stops working at once. Data is kept (delete it per job)."""
    return _set_tenant(db, client_id, False)


@router.post("/tenants/{client_id}/activate")
def activate_tenant(client_id: str, db: Session = Depends(get_db),
                    _: User = Depends(require("tenant.all"))):
    return _set_tenant(db, client_id, True)
