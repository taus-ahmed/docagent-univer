"""
DocAgent v2 — Auth Routes
POST /api/auth/login
GET  /api/auth/me
POST /api/auth/logout
"""

from datetime import datetime, timedelta
from collections import defaultdict
from threading import Lock
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import settings
from app.core.auth import (
    verify_password, create_access_token,
    get_current_user, hash_password,
)
from app.models import get_db, User
from app.schemas.schemas import (
    LoginRequest, TokenResponse, UserResponse, UserUpdate,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# ── Login rate limiter ────────────────────────────────────────────────────────
# In-memory: per IP address, max 5 failed attempts → 15 minute lockout
# Resets on successful login. No Redis needed — works on single instance.
_lock            = Lock()
_fail_counts:  dict = defaultdict(int)
_lockout_until: dict = {}

MAX_ATTEMPTS    = 5
LOCKOUT_MINUTES = 15


def _check_rate_limit(ip: str):
    """Raise 429 if IP is locked out."""
    with _lock:
        locked_until = _lockout_until.get(ip)
        if locked_until and datetime.utcnow() < locked_until:
            wait = int((locked_until - datetime.utcnow()).total_seconds() / 60) + 1
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many failed attempts. Try again in {wait} minute(s).",
            )
        # Clear expired lockout
        if locked_until and datetime.utcnow() >= locked_until:
            del _lockout_until[ip]
            _fail_counts[ip] = 0


def _record_failure(ip: str):
    """Increment failure count and lock out if threshold reached."""
    with _lock:
        _fail_counts[ip] += 1
        if _fail_counts[ip] >= MAX_ATTEMPTS:
            _lockout_until[ip] = datetime.utcnow() + timedelta(minutes=LOCKOUT_MINUTES)
            print(f"[AUTH] IP {ip} locked out for {LOCKOUT_MINUTES}m "
                  f"after {MAX_ATTEMPTS} failed attempts", flush=True)


def _record_success(ip: str):
    """Clear failure count on successful login."""
    with _lock:
        _fail_counts.pop(ip, None)
        _lockout_until.pop(ip, None)


def _get_client_ip(request: Request) -> str:
    """Get real client IP, respecting X-Forwarded-For from Railway proxy."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    """Authenticate user and return JWT token."""
    ip = _get_client_ip(request)

    # Check rate limit before touching the database
    _check_rate_limit(ip)

    user = db.query(User).filter(
        User.username == payload.username,
        User.is_active == True,
    ).first()

    if not user or not verify_password(payload.password, user.password_hash):
        _record_failure(ip)
        # Same message for both cases — don't reveal whether username exists
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )

    # Successful login — clear failure count
    _record_success(ip)

    # Update last login timestamp
    user.last_login = datetime.utcnow()
    db.commit()

    token = create_access_token(
        data={"sub": str(user.id), "role": user.role, "client_id": user.client_id},
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )

    return TokenResponse(
        access_token=token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserResponse(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            email=user.email,
            role=user.role,
            client_id=user.client_id,
            is_active=user.is_active,
        ),
    )


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    """Return current user info."""
    return UserResponse(
        id=current_user.id,
        username=current_user.username,
        display_name=current_user.display_name,
        email=current_user.email,
        role=current_user.role,
        client_id=current_user.client_id,
        is_active=current_user.is_active,
    )


@router.put("/me", response_model=UserResponse)
def update_me(
    payload: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update current user's own profile."""
    if payload.display_name is not None:
        current_user.display_name = payload.display_name
    if payload.email is not None:
        current_user.email = payload.email
    if payload.password is not None:
        if len(payload.password) < 6:
            raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
        current_user.password_hash = hash_password(payload.password)

    db.commit()
    db.refresh(current_user)

    return UserResponse(
        id=current_user.id,
        username=current_user.username,
        display_name=current_user.display_name,
        email=current_user.email,
        role=current_user.role,
        client_id=current_user.client_id,
        is_active=current_user.is_active,
    )


@router.post("/logout")
def logout():
    """Client should discard the token. Stateless JWT — no server-side action."""
    return {"message": "Logged out. Discard your token on the client."}
