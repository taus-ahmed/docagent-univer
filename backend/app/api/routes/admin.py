"""
DocAgent v2 — Admin Routes
GET  /api/admin/users         — list all users
POST /api/admin/users         — create user
PUT  /api/admin/users/{id}    — update user
DELETE /api/admin/users/{id}  — deactivate user
GET  /api/admin/stats         — system stats
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.auth import hash_password
from app.core.permissions import PLATFORM_ADMIN, require, role_of
from app.core.demo import is_demo_user
from app.core.confidence import CONFIDENT_LEVELS
from app.models import get_db, User, ExtractionJob, DocumentResult
from app.schemas.schemas import (
    UserCreate, UserUpdate, UserResponse, SystemStats,
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
        password_hash=hash_password(payload.password),
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
        user.password_hash = hash_password(payload.password)
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
    )
