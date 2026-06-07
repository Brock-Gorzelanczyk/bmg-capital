from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional
from app.dependencies import get_db, get_current_user, require_admin
from app.db.models.users import User
from app.db.models.dca_baskets import DCABasket, DCABasketAsset
from starlette.responses import Response

router = APIRouter(prefix="/api/dca-baskets", tags=["dca-baskets"])

DCA_TEMPLATES = [
    {"name": "Crypto Core", "total_amount": 100.0, "frequency": "weekly", "assets": [{"symbol": "BTC", "allocation_pct": 60.0, "asset_type": "crypto"}, {"symbol": "ETH", "allocation_pct": 30.0, "asset_type": "crypto"}, {"symbol": "SOL", "allocation_pct": 10.0, "asset_type": "crypto"}]},
    {"name": "Global ETF", "total_amount": 200.0, "frequency": "monthly", "assets": [{"symbol": "VTI", "allocation_pct": 60.0, "asset_type": "etf"}, {"symbol": "VXUS", "allocation_pct": 30.0, "asset_type": "etf"}, {"symbol": "BND", "allocation_pct": 10.0, "asset_type": "etf"}]},
    {"name": "Tech Growth", "total_amount": 150.0, "frequency": "biweekly", "assets": [{"symbol": "QQQ", "allocation_pct": 50.0, "asset_type": "etf"}, {"symbol": "NVDA", "allocation_pct": 30.0, "asset_type": "stock"}, {"symbol": "MSFT", "allocation_pct": 20.0, "asset_type": "stock"}]},
]

def _basket_dict(b: DCABasket) -> dict:
    return {
        "id": b.id, "name": b.name, "total_amount": b.total_amount, "frequency": b.frequency,
        "status": b.status, "executions_count": b.executions_count, "total_invested": b.total_invested,
        "created_at": b.created_at.isoformat(),
        "assets": [{"symbol": a.symbol, "allocation_pct": a.allocation_pct, "asset_type": a.asset_type} for a in (b.assets or [])],
    }

@router.get("/")
def list_baskets(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    baskets = db.query(DCABasket).filter(DCABasket.user_id == current_user.id, DCABasket.status != "cancelled").all()
    return [_basket_dict(b) for b in baskets]

@router.get("/templates")
def get_templates(current_user: User = Depends(get_current_user)):
    return DCA_TEMPLATES

class AssetInput(BaseModel):
    symbol: str
    allocation_pct: float
    asset_type: str = "etf"

class BasketCreate(BaseModel):
    name: str
    total_amount: float
    frequency: str = "weekly"
    day_of_week: Optional[int] = None
    assets: list[AssetInput]

@router.post("/")
def create_basket(body: BasketCreate, current_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    total_pct = sum(a.allocation_pct for a in body.assets)
    if abs(total_pct - 100.0) > 0.1:
        raise HTTPException(400, f"Allocations must sum to 100% (got {total_pct:.1f}%)")
    basket = DCABasket(user_id=current_user.id, name=body.name, total_amount=body.total_amount, frequency=body.frequency, day_of_week=body.day_of_week)
    db.add(basket)
    db.flush()
    for a in body.assets:
        db.add(DCABasketAsset(basket_id=basket.id, symbol=a.symbol.upper(), allocation_pct=a.allocation_pct, asset_type=a.asset_type))
    db.commit()
    db.refresh(basket)
    return _basket_dict(basket)

@router.delete("/{basket_id}")
def delete_basket(basket_id: int, current_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    b = db.query(DCABasket).filter_by(id=basket_id, user_id=current_user.id).first()
    if not b:
        raise HTTPException(404, "Not found")
    b.status = "cancelled"
    db.commit()
    return Response(status_code=204)

@router.post("/{basket_id}/pause")
def pause_basket(basket_id: int, current_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    b = db.query(DCABasket).filter_by(id=basket_id, user_id=current_user.id).first()
    if not b:
        raise HTTPException(404, "Not found")
    b.status = "paused"
    db.commit()
    return {"status": "paused"}

@router.post("/{basket_id}/resume")
def resume_basket(basket_id: int, current_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    b = db.query(DCABasket).filter_by(id=basket_id, user_id=current_user.id).first()
    if not b:
        raise HTTPException(404, "Not found")
    b.status = "active"
    db.commit()
    return {"status": "active"}
