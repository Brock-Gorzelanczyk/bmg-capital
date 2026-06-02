from __future__ import annotations
from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.dependencies import get_db, get_current_user
from app.db.models.users import User
from app.db.models.ipo_access import IPODeal, IPORegistration
from app.db.models.tier import UserTier
from app.services.entitlements import effective_tier

router = APIRouter(prefix="/api/ipo", tags=["ipo"])

@router.get("/deals")
def list_deals(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    deals = db.query(IPODeal).filter(IPODeal.status.notin_(["closed", "trading"])).order_by(IPODeal.expected_date).all()
    return [_deal_dict(d) for d in deals]

@router.get("/deals/{deal_id}")
def get_deal(deal_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    d = db.query(IPODeal).filter_by(id=deal_id).first()
    if not d:
        raise HTTPException(404, "Deal not found")
    return _deal_dict(d)

class RegisterBody(BaseModel):
    requested_amount: float = 500.0

@router.post("/deals/{deal_id}/register")
def register(deal_id: int, body: RegisterBody, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    deal = db.query(IPODeal).filter_by(id=deal_id).first()
    if not deal:
        raise HTTPException(404, "Deal not found")
    tier_row = db.query(UserTier).filter_by(user_id=current_user.id).first()
    tier = effective_tier(tier_row) if tier_row else "free"
    tier_rank = {"free": 0, "plus": 1, "premium": 2}
    if tier_rank.get(tier, 0) < tier_rank.get(deal.min_tier, 2):
        raise HTTPException(403, f"IPO access requires {deal.min_tier} tier")
    existing = db.query(IPORegistration).filter_by(user_id=current_user.id, ipo_deal_id=deal_id).first()
    if existing:
        raise HTTPException(400, "Already registered for this IPO")
    reg = IPORegistration(user_id=current_user.id, ipo_deal_id=deal_id, requested_amount=body.requested_amount)
    db.add(reg)
    db.commit()
    db.refresh(reg)
    return {"id": reg.id, "status": reg.status, "requested_amount": reg.requested_amount}

@router.get("/my-registrations")
def my_registrations(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    regs = db.query(IPORegistration).filter_by(user_id=current_user.id).order_by(IPORegistration.created_at.desc()).all()
    result = []
    for r in regs:
        deal = db.query(IPODeal).filter_by(id=r.ipo_deal_id).first()
        result.append({"id": r.id, "status": r.status, "requested_amount": r.requested_amount, "deal": _deal_dict(deal) if deal else None})
    return result

@router.delete("/my-registrations/{reg_id}")
def cancel_registration(reg_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    reg = db.query(IPORegistration).filter_by(id=reg_id, user_id=current_user.id).first()
    if not reg:
        raise HTTPException(404, "Not found")
    reg.status = "cancelled"
    db.commit()
    from starlette.responses import Response
    return Response(status_code=204)

@router.post("/seed")
def seed(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.email not in {"demo@bmgcapital.com", "32bgorzelanczyk@gmail.com"}:
        raise HTTPException(403, "Admin only")
    deals = [
        {"company_name": "Nexus AI", "ticker": "NAI", "expected_date": date(2026, 9, 15), "price_range_low": 12.0, "price_range_high": 14.0, "description": "AI infrastructure platform serving enterprise workloads at the edge.", "sector": "Technology", "lead_underwriter": "Goldman Sachs", "status": "upcoming", "min_tier": "premium"},
        {"company_name": "GreenGrid Energy", "ticker": "GGE", "expected_date": date(2026, 8, 20), "price_range_low": 8.0, "price_range_high": 10.0, "description": "Distributed renewable energy grid management and storage solutions.", "sector": "Clean Energy", "lead_underwriter": "Morgan Stanley", "status": "upcoming", "min_tier": "plus"},
        {"company_name": "DataVault Corp", "ticker": "DVT", "expected_date": date(2026, 11, 5), "price_range_low": 18.0, "price_range_high": 22.0, "description": "Enterprise-grade secure data vault for regulated industries.", "sector": "SaaS", "lead_underwriter": "JPMorgan", "status": "upcoming", "min_tier": "premium"},
    ]
    for d in deals:
        if not db.query(IPODeal).filter_by(company_name=d["company_name"]).first():
            db.add(IPODeal(**d))
    db.commit()
    return {"seeded": len(deals)}

def _deal_dict(d: IPODeal) -> dict:
    return {
        "id": d.id, "company_name": d.company_name, "ticker": d.ticker,
        "expected_date": d.expected_date.isoformat() if d.expected_date else None,
        "price_range_low": d.price_range_low, "price_range_high": d.price_range_high,
        "description": d.description, "sector": d.sector, "lead_underwriter": d.lead_underwriter,
        "status": d.status, "min_tier": d.min_tier,
    }
