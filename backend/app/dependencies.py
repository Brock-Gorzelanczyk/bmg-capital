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
    """Authenticate + assert is_admin. Use instead of get_current_user on mutation routes."""
    user = get_current_user(token, db)
    if not user.is_admin:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "admin_only",
                "detail": "This action is disabled. Only the admin can modify portfolios and bots right now.",
            },
        )
    return user
