from __future__ import annotations

from typing import Generator, Optional

from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import SessionLocal

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(token: Optional[str] = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    """Decode JWT and return the authenticated User. Raises 401 if invalid."""
    from app.db.models.users import User
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid token")

    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def require_admin(token: Optional[str] = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    """Authenticate + assert admin. Blocks viewer accounts on mutation routes.

    user_id=1 is the fund owner (Brock) and is always admin regardless of
    the is_admin DB flag or role string. Without this hard-coded ownership
    rule, every new admin endpoint requires a manual
    `UPDATE users SET is_admin=true WHERE id=1` step from a Railway DB
    shell — which Brock can't easily run from his browser session.
    The owner-by-construction model is appropriate for a single-tenant
    fund app; other users (if any) still must have is_admin=true or
    role='admin' to access admin endpoints.
    """
    user = get_current_user(token, db)
    is_admin = (
        user.is_admin
        or getattr(user, "role", "viewer") == "admin"
        or user.id == 1
    )
    if not is_admin:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "viewer_read_only",
                "detail": "Viewer accounts have read-only access. Contact admin to run your own bots.",
            },
        )
    return user
