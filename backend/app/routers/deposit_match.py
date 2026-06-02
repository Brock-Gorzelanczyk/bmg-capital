from __future__ import annotations
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.dependencies import get_db, get_current_user
from app.db.models.users import User
from app.db.models.deposit_match import DepositMatch
from app.db.models.tier import UserTier
from app.services.entitlements import effective_tier, get_entitlements

router = APIRouter(prefix="/api/deposit-match", tags=["deposit-match"])

@router.get("/summary")
def get_summary(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tier_row = db.query(UserTier).filter_by(user_id=current_user.id).first()
    ents = get_entitlements(tier_row) if tier_row else {}
    match_pct = float(ents.get("deposit_match_pct", 0.0))
    all_matches = db.query(DepositMatch).filter_by(user_id=current_user.id).all()
    pending = sum(m.match_amount for m in all_matches if m.status == "pending")
    credited = sum(m.match_amount for m in all_matches if m.status == "credited")
    return {
        "current_match_pct": match_pct,
        "pending_match": round(pending, 2),
        "credited_ytd": round(credited, 2),
        "next_tier_match_pct": 2.0 if match_pct < 2.0 else None,
    }

class SimulateBody(BaseModel):
    deposit_amount: float
    deposit_type: str = "recurring"

@router.post("/simulate")
def simulate(body: SimulateBody, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tier_row = db.query(UserTier).filter_by(user_id=current_user.id).first()
    ents = get_entitlements(tier_row) if tier_row else {}
    match_pct = float(ents.get("deposit_match_pct", 0.0))
    match_amount = body.deposit_amount * match_pct / 100
    return {
        "deposit_amount": body.deposit_amount,
        "match_pct": match_pct,
        "match_amount": round(match_amount, 2),
        "annual_match": round(match_amount * 12, 2),
        "lock_days": 90,
        "total_after_match": round(body.deposit_amount + match_amount, 2),
    }
