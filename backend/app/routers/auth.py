from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
import bcrypt as _bcrypt
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models.users import User
from app.db.models.tier import UserTier
from app.dependencies import get_db, get_current_user

_RATE_STORE: dict[str, list[float]] = defaultdict(list)
_RATE_LIMIT = 10   # max attempts
_RATE_WINDOW = 60  # seconds


def _check_rate_limit(key: str) -> None:
    now = time.monotonic()
    window = _RATE_STORE[key]
    # drop old entries
    _RATE_STORE[key] = [t for t in window if now - t < _RATE_WINDOW]
    if len(_RATE_STORE[key]) >= _RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Too many attempts. Try again in a minute.")
    _RATE_STORE[key].append(now)

router = APIRouter(prefix="/api/auth", tags=["auth"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


# ── Schemas ────────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: str
    username: str
    password: str


class LoginRequest(BaseModel):
    email: str  # accepts username or email
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


# ── Helpers ────────────────────────────────────────────────────────────────────

def _hash_password(password: str) -> str:
    return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()


def _verify_password(plain: str, hashed: str) -> bool:
    try:
        return _bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


def _create_token(user: User) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=settings.jwt_expire_days)
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "username": user.username,
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _user_dict(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "is_admin": getattr(user, "is_admin", False),
    }


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/register", response_model=TokenResponse)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    _check_rate_limit(body.email.lower().strip())
    if db.query(User).filter(User.email == body.email.lower().strip()).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(status_code=400, detail="Username already taken")
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    has_digit = any(c.isdigit() for c in body.password)
    has_special = any(not c.isalnum() for c in body.password)
    if not (has_digit or has_special):
        raise HTTPException(status_code=400, detail="Password must contain at least one number or special character")

    user = User(
        email=body.email.lower().strip(),
        username=body.username.strip(),
        hashed_password=_hash_password(body.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Auto-start Pro+ (premium) trial for 14 days — no card required
    try:
        trial_end = datetime.now(timezone.utc) + timedelta(days=14)
        tier_row = UserTier(
            user_id=user.id,
            tier="premium",
            status="trialing",
            trial_ends_at=trial_end,
            billing_interval=None,
        )
        db.add(tier_row)
        db.commit()
    except Exception:
        db.rollback()

    return TokenResponse(access_token=_create_token(user), user=_user_dict(user))


@router.post("/login", response_model=TokenResponse)
def login(request: Request, body: LoginRequest, db: Session = Depends(get_db)):
    from app.db.models.monitoring import LoginAttempt

    _check_rate_limit(body.email.lower().strip())
    identifier = body.email.strip()
    ip = request.client.host if request.client else "unknown"

    user = db.query(User).filter(User.email == identifier.lower()).first()
    if not user:
        user = db.query(User).filter(User.username == identifier).first()
    if not user or not _verify_password(body.password, user.hashed_password):
        # Record failed attempt
        try:
            db.add(LoginAttempt(ip_address=ip, email=body.email.lower().strip(), success=False))
            db.commit()
        except Exception:
            db.rollback()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    if not user.is_active:
        try:
            db.add(LoginAttempt(ip_address=ip, email=body.email.lower().strip(), success=False))
            db.commit()
        except Exception:
            db.rollback()
        raise HTTPException(status_code=403, detail="Account disabled")

    # Record successful attempt
    try:
        db.add(LoginAttempt(ip_address=ip, email=user.email, success=True))
        db.commit()
    except Exception:
        db.rollback()

    return TokenResponse(access_token=_create_token(user), user=_user_dict(user))


@router.get("/me")
def me(current_user=Depends(get_current_user)):
    return _user_dict(current_user)
