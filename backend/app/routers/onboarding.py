from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
from app.db.models.users import User
from app.db.models.profile import UserProfile
from app.db.models.learn import UserProgress

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])

WELCOME_XP = 100


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


@router.post("/complete")
def complete_onboarding(
    body: CompleteBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = db.query(UserProfile).filter_by(user_id=current_user.id).first()
    if profile:
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

    # Grant welcome XP via learning progress
    progress = db.query(UserProgress).filter_by(user_id=current_user.id).first()
    xp_granted = 0
    if progress and not profile.onboarding_complete:
        progress.xp = (progress.xp or 0) + WELCOME_XP
        xp_granted = WELCOME_XP
    elif not progress:
        progress = UserProgress(user_id=current_user.id, xp=WELCOME_XP, level=1)
        db.add(progress)
        xp_granted = WELCOME_XP

    db.commit()
    return {"ok": True, "xp_granted": xp_granted}
