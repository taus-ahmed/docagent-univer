"""
DocAgent v2 — Auth Core
JWT token creation/verification, password hashing, FastAPI dependencies.
"""

import base64
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.config import settings
from app.models import get_db, User

security = HTTPBearer()


# ─── Password Hashing ─────────────────────────────────────────────────────────

# New hashes: bcrypt over a SHA-256 pre-hash, stored as
# "bcrypt-sha256$<bcrypt hash>". The pre-hash (base64, 44 bytes) keeps a
# password over bcrypt's 72-byte limit from being truncated or rejected.
# bcrypt is pinned directly in requirements.txt (passlib is not used).
#
# Legacy hashes ("salt:sha256hex", one unsalted-cost round) still verify, in
# constant time, and are replaced on the next successful login
# (`needs_rehash`, routes/auth.py). Nothing is migrated in bulk: a hash is
# only ever upgraded by someone who has just proved they know the password.
_BCRYPT_PREFIX = "bcrypt-sha256$"

# A ONE-TIME password (one an administrator or `scripts/create_tenant.py` set
# for someone else) is the same hash behind this marker. It signs in, and
# `get_current_user` then refuses every route but ONE_TIME_ALLOWED until the
# owner chooses their own (`POST /api/auth/change-password`). No column, no
# migration: the marker lives and dies with the hash it describes.
_ONE_TIME_PREFIX = "otp$"
ONE_TIME_ALLOWED = {("GET", "/api/auth/me"), ("POST", "/api/auth/change-password"),
                    ("POST", "/api/auth/logout")}
ONE_TIME_MESSAGE = ("Choose your own password first: this account still has its "
                    "one-time password.")


def is_one_time(password_hash) -> bool:
    return str(password_hash or "").startswith(_ONE_TIME_PREFIX)


def _bcrypt_rounds() -> int:
    """Cost factor; BCRYPT_ROUNDS (4–16) exists so a test suite can run fast."""
    try:
        return max(4, min(16, int(os.environ.get("BCRYPT_ROUNDS", "12"))))
    except ValueError:
        return 12


def _prehash(password: str) -> bytes:
    return base64.b64encode(hashlib.sha256(password.encode("utf-8")).digest())


def hash_password(password: str, one_time: bool = False) -> str:
    """A bcrypt hash of `password` (see above); marked one-time on request."""
    import bcrypt
    h = bcrypt.hashpw(_prehash(password), bcrypt.gensalt(_bcrypt_rounds()))
    return (_ONE_TIME_PREFIX if one_time else "") + _BCRYPT_PREFIX + h.decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against a stored hash of either scheme."""
    password_hash = str(password_hash or "")
    if password_hash.startswith(_ONE_TIME_PREFIX):
        password_hash = password_hash[len(_ONE_TIME_PREFIX):]
    try:
        if password_hash.startswith(_BCRYPT_PREFIX):
            import bcrypt
            return bcrypt.checkpw(_prehash(password),
                                  password_hash[len(_BCRYPT_PREFIX):].encode("ascii"))
        salt, h = password_hash.split(":")
        return hmac.compare_digest(
            hashlib.sha256((salt + password).encode()).hexdigest(), h)
    except Exception:
        return False


def needs_rehash(password_hash: str) -> bool:
    """True for a legacy hash, or a bcrypt hash below the current cost. The
    one-time marker is not part of the question (a rehash keeps it)."""
    if is_one_time(password_hash):
        password_hash = password_hash[len(_ONE_TIME_PREFIX):]
    if not (password_hash or "").startswith(_BCRYPT_PREFIX):
        return True
    try:
        return int(password_hash[len(_BCRYPT_PREFIX):].split("$")[2]) < _bcrypt_rounds()
    except (IndexError, ValueError):
        return True


_DUMMY: list[str] = []


def verify_unknown_user(password: str) -> None:
    """Spend the time a real verify would, for a username that does not
    exist, so the response time does not say which usernames are real."""
    if not _DUMMY:
        _DUMMY.append(hash_password(secrets.token_hex(16)))
    verify_password(password, _DUMMY[0])


# ─── JWT ──────────────────────────────────────────────────────────────────────

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a signed JWT access token."""
    to_encode = data.copy()
    expire = datetime.utcnow() + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire, "iat": datetime.utcnow()})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode and verify a JWT token. Raises HTTPException on failure."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ─── FastAPI Dependencies ─────────────────────────────────────────────────────

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
    request: Request = None,
) -> User:
    """Dependency: extract + verify JWT, return current User ORM object."""
    token = credentials.credentials
    payload = decode_token(token)

    user_id: int = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject claim",
        )

    user = db.query(User).filter(User.id == int(user_id), User.is_active == True).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    if (request is not None and is_one_time(user.password_hash)
            and (request.method, request.url.path) not in ONE_TIME_ALLOWED):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail=ONE_TIME_MESSAGE)
    return user


def same_tenant(a, b) -> bool:
    """True when both name the SAME tenant. `None` is "no tenant", never a
    tenant shared by everyone who has none — a super-admin's templates carry
    `client_id = None`, so `a == b` handed them to every tenant-less account."""
    return bool(a) and a == b


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Dependency: require an admin (platform or tenant). Routes now name the
    action they need (`permissions.require`); kept for callers outside them."""
    from app.core.permissions import can
    if not can(current_user, "user.manage"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(
        HTTPBearer(auto_error=False)
    ),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """Dependency: return user if authenticated, None otherwise (for public routes)."""
    if credentials is None:
        return None
    try:
        return get_current_user(credentials, db)
    except HTTPException:
        return None
