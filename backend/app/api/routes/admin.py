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
from sqlalchemy import func

from app.core.auth import get_current_user, require_admin, hash_password
from app.models import get_db, User, ExtractionJob, DocumentResult
from app.schemas.schemas import (
    UserCreate, UserUpdate, UserResponse, SystemStats,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/users", response_model=list[UserResponse])
def list_users(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """List all users."""
    users = db.query(User).order_by(User.created_at.desc()).all()
    return [_user_to_response(u) for u in users]


@router.post("/users", response_model=UserResponse, status_code=201)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Create a new user."""
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
    current_admin: User = Depends(require_admin),
):
    """Update a user's details."""
    user = db.query(User).filter(User.id == user_id).first()
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
        # Can't demote self from admin
        if user.id == current_admin.id and payload.role != "admin":
            raise HTTPException(status_code=400, detail="Cannot remove your own admin role")
        user.role = payload.role
    if payload.client_id is not None:
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
    current_admin: User = Depends(require_admin),
):
    """Soft-delete (deactivate) a user."""
    if user_id == current_admin.id:
        raise HTTPException(status_code=400, detail="Cannot deactivate yourself")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_active = False
    db.commit()
    return {"message": f"User '{user.username}' deactivated", "id": user_id}


@router.get("/stats", response_model=SystemStats)
def get_stats(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """System-wide statistics."""
    seven_days_ago = datetime.utcnow() - timedelta(days=7)

    total_jobs = db.query(ExtractionJob).count()
    total_docs = db.query(DocumentResult).count()
    total_users = db.query(User).filter(User.is_active == True).count()
    reviewed = db.query(DocumentResult).filter(DocumentResult.reviewed == True).count()
    pending_review = db.query(DocumentResult).filter(
        DocumentResult.needs_review == True,
        DocumentResult.reviewed == False,
    ).count()
    high_conf = db.query(DocumentResult).filter(
        DocumentResult.overall_confidence == "high"
    ).count()
    jobs_7d = db.query(ExtractionJob).filter(
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

def _user_to_response(u: User) -> UserResponse:
    return UserResponse(
        id=u.id,
        username=u.username,
        display_name=u.display_name,
        email=u.email,
        role=u.role,
        client_id=u.client_id,
        is_active=u.is_active,
    )
