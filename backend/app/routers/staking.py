from __future__ import annotations
from datetime import timezone, datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.dependencies import get_db, get_current_user
from app.db.models.users import User
from app.db.models.staking import StakingPosition, StakingRewardLog

router = APIRouter(prefix="/api/staking", tags=["staking"])

STAKING_CONFIG = {
    "ETH":  {"apy": 2.6,  "min_amount": 0.01, "unstake_days": 6,  "validator": "Figment",      "price_usd": 3800.0},
    "SOL":  {"apy": 5.8,  "min_amount": 0.1,  "unstake_days": 2,  "validator": "P2P Validator", "price_usd": 170.0},
    "ATOM": {"apy": 9.2,  "min_amount": 1.0,  "unstake_days": 21, "validator": "Figment",      "price_usd": 8.5},
    "DOT":  {"apy": 12.0, "min_amount": 1.0,  "unstake_days": 28, "validator": "Kiln",         "price_usd": 7.2},
    "ADA":  {"apy": 3.5,  "min_amount": 5.0,  "unstake_days": 5,  "validator": "Kiln",         "price_usd": 0.45},
}

def _accrue_rewards(position: StakingPosition) -> float:
    if position.status != "active":
        return position.rewards_earned
    days = (datetime.now(timezone.utc) - position.staked_at).total_seconds() / 86400
    return position.amount_staked * position.apy / 100 / 365 * days

@router.get("/assets")
def get_assets(current_user: User = Depends(get_current_user)):
    return [{"asset": asset, **cfg} for asset, cfg in STAKING_CONFIG.items()]

@router.get("/positions")
def get_positions(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    positions = db.query(StakingPosition).filter_by(user_id=current_user.id).all()
    result = []
    for p in positions:
        cfg = STAKING_CONFIG.get(p.asset, {})
        accrued = _accrue_rewards(p)
        result.append({
            "id": p.id, "asset": p.asset, "amount_staked": p.amount_staked, "apy": p.apy,
            "rewards_earned": round(accrued, 6), "rewards_usd": round(accrued * cfg.get("price_usd", 1), 2),
            "status": p.status, "staked_at": p.staked_at.isoformat(),
            "estimated_unstake_at": p.estimated_unstake_at.isoformat() if p.estimated_unstake_at else None,
            "validator": cfg.get("validator", ""), "staked_value_usd": round(p.amount_staked * cfg.get("price_usd", 1), 2),
        })
    return result

@router.get("/summary")
def get_summary(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    positions = db.query(StakingPosition).filter_by(user_id=current_user.id, status="active").all()
    total_staked_usd = sum(p.amount_staked * STAKING_CONFIG.get(p.asset, {}).get("price_usd", 1) for p in positions)
    total_rewards_usd = sum(_accrue_rewards(p) * STAKING_CONFIG.get(p.asset, {}).get("price_usd", 1) for p in positions)
    avg_apy = sum(p.apy for p in positions) / len(positions) if positions else 0
    return {"total_staked_usd": round(total_staked_usd, 2), "total_rewards_usd": round(total_rewards_usd, 2), "avg_apy": round(avg_apy, 2), "positions_count": len(positions)}

class StakeBody(BaseModel):
    asset: str
    amount: float

@router.post("/stake")
def stake(body: StakeBody, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    cfg = STAKING_CONFIG.get(body.asset.upper())
    if not cfg:
        raise HTTPException(400, f"Unsupported asset: {body.asset}")
    if body.amount < cfg["min_amount"]:
        raise HTTPException(400, f"Minimum stake for {body.asset} is {cfg['min_amount']}")
    position = StakingPosition(
        user_id=current_user.id, asset=body.asset.upper(),
        amount_staked=body.amount, apy=cfg["apy"],
    )
    db.add(position)
    db.commit()
    db.refresh(position)
    return {"id": position.id, "asset": position.asset, "amount_staked": position.amount_staked, "apy": position.apy, "validator": cfg["validator"], "status": position.status}

@router.post("/unstake/{position_id}")
def unstake(position_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = db.query(StakingPosition).filter_by(id=position_id, user_id=current_user.id).first()
    if not p:
        raise HTTPException(404, "Position not found")
    if p.status != "active":
        raise HTTPException(400, "Position is not active")
    cfg = STAKING_CONFIG.get(p.asset, {})
    p.status = "unstaking"
    p.unstake_requested_at = datetime.now(timezone.utc)
    p.estimated_unstake_at = datetime.now(timezone.utc) + timedelta(days=cfg.get("unstake_days", 7))
    db.commit()
    return {"status": "unstaking", "estimated_unstake_at": p.estimated_unstake_at.isoformat()}
