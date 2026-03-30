"""
Authentication: password hashing, JWT, and current-user dependency.

Password rules (aligned with bcrypt and production safety):
- Non-empty (after strip)
- Length in UTF-8 bytes: 1 <= len <= 72 (bcrypt's hard limit)
We reject before hashing so we never trigger bcrypt's internal error.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from fastapi.security.utils import get_authorization_scheme_param
from fastapi import Request

from app.models.user import User
from app.database import get_db
from app.config import get_settings

settings = get_settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")
log = logging.getLogger(__name__)

# Admin console roles (DB is source of truth; JWT may carry role for clients that choose to cache it)
ADMIN_ROLES = frozenset({"super_admin", "moderator", "support", "viewer"})
ROLE_SUPER_ADMIN = "super_admin"
ROLE_MODERATOR = "moderator"
ROLE_SUPPORT = "support"
ROLE_VIEWER = "viewer"

# Higher number = more privilege (for require_min_role)
ROLE_LEVEL = {
    ROLE_VIEWER: 0,
    ROLE_SUPPORT: 1,
    ROLE_MODERATOR: 2,
    ROLE_SUPER_ADMIN: 3,
}

# Bcrypt truncates at 72 bytes; we enforce the same limit so hashing never fails.
PASSWORD_MIN_BYTES = 1
PASSWORD_MAX_BYTES = 72


class PasswordError(ValueError):
    """Raised when a password fails validation before or during hashing."""
    pass


def validate_password(password: str) -> None:
    """
    Validate password for length and emptiness.
    Raises PasswordError with a clear message if invalid.
    """
    if not isinstance(password, str):
        raise PasswordError("Password must be a string")
    cleaned = password.strip()
    if not cleaned:
        raise PasswordError("Password cannot be empty")
    size = len(cleaned.encode("utf-8"))
    if size < PASSWORD_MIN_BYTES:
        raise PasswordError("Password cannot be empty")
    if size > PASSWORD_MAX_BYTES:
        raise PasswordError(
            f"Password cannot be longer than {PASSWORD_MAX_BYTES} bytes (bcrypt limit)"
        )


def hash_password(password: str) -> str:
    """
    Hash a password with bcrypt. Validates length first; on failure raises
    PasswordError instead of letting bcrypt crash the process.
    """
    validate_password(password)
    try:
        return pwd_context.hash(password)
    except ValueError as e:
        msg = str(e)
        if "72" in msg or "bytes" in msg.lower():
            raise PasswordError(
                f"Password cannot be longer than {PASSWORD_MAX_BYTES} bytes (bcrypt limit)"
            ) from e
        raise PasswordError(f"Password hashing failed: {msg}") from e
    except Exception as e:
        raise PasswordError(f"Password hashing failed: {e!s}") from e


def verify_password(plain: str, hashed: str) -> bool:
    if not plain or not hashed:
        return False
    try:
        return pwd_context.verify(plain, hashed)
    except Exception:
        return False


def create_access_token(
    user_id: int,
    *,
    is_admin: bool = False,
    role: Optional[str] = None,
) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    data = {"sub": str(user_id), "exp": expire, "is_admin": bool(is_admin)}
    if role is not None:
        data["role"] = role
    return jwt.encode(data, settings.secret_key, algorithm=settings.algorithm)


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    return db.query(User).filter(User.email == email).first()


def get_user_by_id(db: Session, user_id: int) -> Optional[User]:
    return db.query(User).filter(User.id == user_id).first()


def authenticate_user(db: Session, email: str, password: str) -> Optional[User]:
    if not password:
        return None
    if len(password.encode("utf-8")) > PASSWORD_MAX_BYTES:
        return None
    user = get_user_by_email(db, email)
    if not user or not verify_password(password, user.hashed_password):
        return None
    return user


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
        is_admin_claim = payload.get("is_admin") is True
        role_claim = payload.get("role")
        if role_claim is not None and not isinstance(role_claim, str):
            role_claim = str(role_claim)
    except JWTError:
        raise credentials_exception

    user = get_user_by_id(db, int(user_id))
    if user is None or not user.is_active or user.is_blocked:
        raise credentials_exception
    user.is_admin_claim = is_admin_claim
    user.role_claim = role_claim  # optional mirror of JWT; not used for authorization
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """
    Admin API: JWT must claim is_admin True, and DB must still mark user as admin.
    """
    admin_forbidden = HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Admin access required",
    )
    if not getattr(current_user, "is_admin_claim", False):
        raise admin_forbidden
    if not current_user.is_admin:
        raise admin_forbidden
    return current_user


def require_valid_admin_role(user: User) -> str:
    """Return DB role for an admin user. Fails closed if role is missing or not in ADMIN_ROLES."""
    raw = getattr(user, "role", None)
    r = (raw or "").strip()
    if r not in ADMIN_ROLES:
        log.error(
            "Invalid admin role in database for user_id=%s: %r",
            user.id,
            raw,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Invalid user role configuration",
        )
    return r


def require_min_role(min_role: str) -> Callable:
    """
    Admin routes: require_admin first, then DB role level must be >= min_role.
    Example: require_min_role(ROLE_MODERATOR) allows moderator + super_admin only.
    """
    if min_role not in ROLE_LEVEL:
        raise ValueError(f"Invalid min_role: {min_role!r}")
    min_level = ROLE_LEVEL[min_role]

    def _dep(user: User = Depends(require_admin)) -> User:
        r = require_valid_admin_role(user)
        if ROLE_LEVEL[r] < min_level:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions for this action",
            )
        return user

    return _dep


async def get_optional_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> Optional[User]:
    """Returns the current user if a valid token is present, otherwise None.
    Used for public endpoints that show extra data when authenticated."""
    authorization = request.headers.get("Authorization")
    if not authorization:
        return None
    scheme, token = get_authorization_scheme_param(authorization)
    if scheme.lower() != "bearer" or not token:
        return None
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        user_id: str = payload.get("sub")
        if user_id is None:
            return None
        user = get_user_by_id(db, int(user_id))
        if user and user.is_active and not user.is_blocked:
            user.is_admin_claim = payload.get("is_admin") is True
            rc = payload.get("role")
            user.role_claim = str(rc) if rc is not None else None
            return user
    except JWTError:
        pass
    return None
