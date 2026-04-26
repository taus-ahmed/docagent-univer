"""
DocAgent v2 — Auth Routes
POST /api/auth/login
GET  /api/auth/me
POST /api/auth/logout  (client-side token discard)
"""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
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


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate user and return JWT token."""
    user = db.query(User).filter(
        User.username == payload.username,
        User.is_active == True,
    ).first()

    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )

    # Update last login
    from datetime import datetime
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
