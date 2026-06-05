from __future__ import annotations
import random
from datetime import timezone, datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.dependencies import get_db, get_current_user
from app.db.models.users import User
from app.db.models.referral import ReferralCode, ReferralReward

router = APIRouter(prefix="/api/referral", tags=["referral"])

REWARD_STOCKS = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA", "META", "SPY", "QQQ", "VTI"]

def _generate_reward():
    r = random.random()
    if r < 0.99:
        return 5.0, random.choice(["SPY", "QQQ", "VTI"])
    elif r < 0.999:
        return 50.0, random.choice(["AAPL", "MSFT"])
    else:
        return 200.0, random.choice(["NVDA", "TSLA", "GOOGL"])

@router.get("/my-code")
def get_my_code(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.query(ReferralCode).filter_by(user_id=current_user.id).first()
    if not row:
        row = ReferralCode(user_id=current_user.id)
        db.add(row)
        db.commit()
        db.refresh(row)
    return {
        "code": row.code,
        "total_referrals": row.total_referrals,
        "total_rewards_earned": row.total_rewards_earned,
        "share_url": f"https://bmgcapital.com/join?ref={row.code}",
    }

@router.get("/rewards")
def get_rewards(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rewards = db.query(ReferralReward).filter_by(referrer_id=current_user.id).order_by(ReferralReward.created_at.desc()).all()
    return [{"id": r.id, "referred_email": r.referred_email[:3] + "***" + r.referred_email[r.referred_email.find("@"):], "status": r.status, "reward_amount": r.reward_amount, "reward_symbol": r.reward_symbol, "created_at": r.created_at.isoformat()} for r in rewards]

@router.get("/stats")
def get_stats(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    code_row = db.query(ReferralCode).filter_by(user_id=current_user.id).first()
    rewards = db.query(ReferralReward).filter_by(referrer_id=current_user.id).all()
    return {
        "total_referrals": code_row.total_referrals if code_row else 0,
        "pending_rewards": sum(1 for r in rewards if r.status == "pending"),
        "qualified_rewards": sum(1 for r in rewards if r.status == "qualified"),
        "total_earned": sum(r.reward_amount or 0 for r in rewards if r.status == "rewarded"),
    }

class ValidateBody(BaseModel):
    code: str
    email: str

@router.post("/validate")
def validate_referral(body: ValidateBody, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    code_row = db.query(ReferralCode).filter_by(code=body.code.upper()).first()
    if not code_row:
        raise HTTPException(400, "Invalid referral code")
    if code_row.user_id == current_user.id:
        raise HTTPException(400, "Cannot use your own referral code")
    amount, symbol = _generate_reward()
    reward = ReferralReward(
        referrer_id=code_row.user_id,
        referred_email=body.email,
        code_used=body.code.upper(),
        status="pending",
        reward_amount=amount,
        reward_symbol=symbol,
        expires_at=datetime.now(timezone.utc) + timedelta(days=60),
    )
    db.add(reward)
    code_row.total_referrals = (code_row.total_referrals or 0) + 1
    db.commit()
    return {"ok": True, "message": "Referral recorded"}
