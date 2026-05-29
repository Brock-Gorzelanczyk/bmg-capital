from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
from app.db.models.users import User
from app.db.models.profile import UserProfile
from app.db.models.learn import UserProgress

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])

WELCOME_XP = 200
REWARD_SYMBOL = "AAPL"
REWARD_SHARES = Decimal("0.1")  # fractional share


@router.get("/status")
def get_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = db.query(UserProfile).filter_by(user_id=current_user.id).first()
    return {
        "onboarding_complete": profile.onboarding_complete if profile else False,
        "goal": profile.goal if profile else None,
        "experience": profile.experience if profile else None,
        "risk_tolerance": profile.risk_tolerance if profile else None,
        "time_horizon": profile.time_horizon if profile else None,
    }


class CompleteBody(BaseModel):
    goal: str
    experience: str
    risk_tolerance: str
    time_horizon: str
    asset_classes: Optional[list[str]] = None
    interests: Optional[list[str]] = None
    deposit_amount: Optional[float] = None


@router.post("/complete")
def complete_onboarding(
    body: CompleteBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = db.query(UserProfile).filter_by(user_id=current_user.id).first()
    already_complete = False
    if profile:
        already_complete = profile.onboarding_complete
        profile.goal = body.goal
        profile.experience = body.experience
        profile.risk_tolerance = body.risk_tolerance
        profile.time_horizon = body.time_horizon
        profile.onboarding_complete = True
        profile.onboarding_completed_at = datetime.utcnow()
        profile.updated_at = datetime.utcnow()
    else:
        profile = UserProfile(
            user_id=current_user.id,
            goal=body.goal,
            experience=body.experience,
            risk_tolerance=body.risk_tolerance,
            time_horizon=body.time_horizon,
            onboarding_complete=True,
            onboarding_completed_at=datetime.utcnow(),
        )
        db.add(profile)

    # Grant welcome XP
    progress = db.query(UserProgress).filter_by(user_id=current_user.id).first()
    xp_granted = 0
    if not already_complete:
        if progress:
            progress.xp = (progress.xp or 0) + WELCOME_XP
        else:
            progress = UserProgress(user_id=current_user.id, xp=WELCOME_XP, level=1)
            db.add(progress)
        xp_granted = WELCOME_XP

    db.commit()
    return {"ok": True, "xp_granted": xp_granted}


@router.post("/claim-reward")
async def claim_reward(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Grant the welcome reward: seed a fractional AAPL paper position."""
    from app.db.models.paper import PaperPosition

    # Check if already claimed
    existing = db.query(PaperPosition).filter_by(user_id=current_user.id, symbol=REWARD_SYMBOL).first()
    if existing:
        return {"ok": True, "already_claimed": True, "symbol": REWARD_SYMBOL, "shares": float(REWARD_SHARES)}

    # Get a current price estimate
    price = Decimal("220.00")  # fallback
    try:
        import yfinance as yf
        ticker = yf.Ticker(REWARD_SYMBOL)
        hist = ticker.history(period="1d")
        if not hist.empty:
            price = Decimal(str(round(float(hist["Close"].iloc[-1]), 2)))
    except Exception:
        pass

    cost = price * REWARD_SHARES

    # Create position (free gift — doesn't deduct from cash)
    position = PaperPosition(
        user_id=current_user.id,
        symbol=REWARD_SYMBOL,
        qty=float(REWARD_SHARES),
        avg_cost=float(price),
    )
    db.add(position)
    db.commit()
    return {
        "ok": True,
        "already_claimed": False,
        "symbol": REWARD_SYMBOL,
        "shares": float(REWARD_SHARES),
        "price": float(price),
        "value": float(cost),
    }
