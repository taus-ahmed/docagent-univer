"""
DocAgent v2 — Auth Routes
POST /api/auth/login
GET  /api/auth/me
POST /api/auth/logout
"""

from datetime import datetime, timedelta
from collections import defaultdict
from threading import Lock

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import settings
from app.core.auth import (
    verify_password, needs_rehash, verify_unknown_user, create_access_token,
    get_current_user, hash_password, is_one_time,
)
from app.core.permissions import permissions_of
from app.core.demo import is_demo_user
from app.core import demo_audit
from app.models import get_db, User
from app.schemas.schemas import (
    ChangePasswordRequest, LoginRequest, TokenResponse, UserResponse, UserUpdate,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# ── Login rate limiter ────────────────────────────────────────────────────────
# In-memory, per (client IP, username): MAX_ATTEMPTS failed attempts lock THAT
# username from THAT address for LOCKOUT_MINUTES. Keyed by the pair so that
# nobody can lock out another firm's users: failures against one username lock
# only that username, and only from the address they came from. Resets on a
# successful login. Single instance; a shared store is needed beyond one.
_lock            = Lock()
_fail_counts:  dict = defaultdict(int)
_lockout_until: dict = {}

MAX_ATTEMPTS    = 5
LOCKOUT_MINUTES = 15


def _key(ip: str, username: str) -> tuple:
    return (ip, (username or "").strip().casefold())


def _check_rate_limit(key):
    """Raise 429 if this (IP, username) is locked out."""
    with _lock:
        locked_until = _lockout_until.get(key)
        if locked_until and datetime.utcnow() < locked_until:
            wait = int((locked_until - datetime.utcnow()).total_seconds() / 60) + 1
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many failed attempts. Try again in {wait} minute(s).",
            )
        # Clear expired lockout
        if locked_until and datetime.utcnow() >= locked_until:
            del _lockout_until[key]
            _fail_counts[key] = 0


def _record_failure(key):
    """Increment failure count and lock out if threshold reached."""
    with _lock:
        _fail_counts[key] += 1
        if _fail_counts[key] >= MAX_ATTEMPTS:
            _lockout_until[key] = datetime.utcnow() + timedelta(minutes=LOCKOUT_MINUTES)
            # the address only: a username is not logged
            print(f"[AUTH] IP {key[0]} locked out of one account for "
                  f"{LOCKOUT_MINUTES}m after {MAX_ATTEMPTS} failed attempts", flush=True)


def _record_success(key):
    """Clear failure count on successful login."""
    with _lock:
        _fail_counts.pop(key, None)
        _lockout_until.pop(key, None)


def _get_client_ip(request: Request) -> str:
    """The client's address as the nearest proxy saw it.

    The LAST X-Forwarded-For entry is the one the platform's own proxy
    appended (Railway's edge — VERIFY in docs/OPERATIONS.md); every entry
    before it is whatever the caller chose to send. Reading the first one let
    anyone rotate addresses past the limiter, or name someone else's."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        if parts:
            return parts[-1]
    return request.client.host if request.client else "unknown"


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    """Authenticate user and return JWT token."""
    ip = _get_client_ip(request)

    # Check rate limit before touching the database
    key = _key(ip, payload.username)
    _check_rate_limit(key)

    user = db.query(User).filter(
        User.username == payload.username,
        User.is_active == True,
    ).first()

    if not user:
        verify_unknown_user(payload.password)
    if not user or not verify_password(payload.password, user.password_hash):
        _record_failure(key)
        # The activity trail, for a demo tenant only. A wrong password on a
        # known demo account is a row; an attempt on a username that does not
        # exist is NOT, because nothing identifies which tenant it was aimed
        # at. The password is never recorded, here or anywhere.
        demo_audit.record_for_client(
            db, getattr(user, "client_id", None), demo_audit.LOGIN_FAILED,
            user_id=getattr(user, "id", None),
            detail={"username": payload.username, "ip": ip})
        # Same message for both cases — don't reveal whether username exists
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )

    # Successful login — clear failure count
    _record_success(key)

    # A legacy (salted SHA-256) hash is replaced now, while the password is in
    # hand, in the same commit as the login. A failure to rehash never fails
    # the login: the old hash still verifies and is upgraded next time.
    if needs_rehash(user.password_hash):
        try:
            user.password_hash = hash_password(
                payload.password, one_time=is_one_time(user.password_hash))
        except Exception as exc:
            print(f"[AUTH] password rehash skipped for user {user.id}: "
                  f"{type(exc).__name__}", flush=True)

    # Update last login timestamp
    user.last_login = datetime.utcnow()
    db.commit()

    # Recorded AFTER the login's own commit, so the audit row can never be the
    # reason a successful login fails. A no-op for every non-demo tenant.
    demo_audit.record(db, user, demo_audit.LOGIN,
                      detail={"username": user.username, "ip": ip})

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
            is_demo=is_demo_user(user),
            permissions=permissions_of(user),
            must_change_password=is_one_time(user.password_hash),
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
        is_demo=is_demo_user(current_user),
        permissions=permissions_of(current_user),
        must_change_password=is_one_time(current_user.password_hash),
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
        is_demo=is_demo_user(current_user),
        permissions=permissions_of(current_user),
        must_change_password=is_one_time(current_user.password_hash),
    )


@router.post("/change-password", response_model=UserResponse)
def change_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Replace the caller's password, proving the current one. The only way
    out of a one-time password (`auth.is_one_time`); the new one is never
    one-time and must differ from it."""
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="The current password is not right")
    if payload.new_password == payload.current_password:
        raise HTTPException(status_code=400,
                            detail="Choose a password different from the current one")
    current_user.password_hash = hash_password(payload.new_password)
    db.commit()
    db.refresh(current_user)
    print(f"[AUTH] user {current_user.id} changed their password", flush=True)
    return get_me(current_user)


@router.post("/logout")
def logout():
    """Client should discard the token. Stateless JWT — no server-side action."""
    return {"message": "Logged out. Discard your token on the client."}
