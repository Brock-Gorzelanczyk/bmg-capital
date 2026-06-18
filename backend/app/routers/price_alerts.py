from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
from app.db.models.price_alert import PriceAlert

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/price-alerts", tags=["price-alerts"])


class AlertCreate(BaseModel):
    ticker: str
    price: float                         # dollars
    direction: str                       # "above" | "below"
    message: Optional[str] = None
    workshop_chart_id: Optional[int] = None
    notif_discord: bool = True
    notif_inapp: bool = True


def _serialize(r: PriceAlert) -> dict:
    return {
        "id": r.id,
        "workshop_chart_id": r.workshop_chart_id,
        "ticker": r.ticker,
        "price": r.price_cents / 100,
        "direction": r.direction,
        "message": r.message,
        "status": r.status,
        "notif_discord": r.notif_discord,
        "notif_inapp": r.notif_inapp,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "triggered_at": r.triggered_at.isoformat() if r.triggered_at else None,
    }


@router.get("")
def list_alerts(
    ticker: Optional[str] = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    q = db.query(PriceAlert).filter_by(user_id=user.id)
    if ticker:
        q = q.filter(PriceAlert.ticker == ticker.upper())
    rows = q.order_by(PriceAlert.created_at.desc()).all()
    return {"alerts": [_serialize(r) for r in rows]}


@router.post("", status_code=201)
def create_alert(
    body: AlertCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    row = PriceAlert(
        user_id=user.id,
        ticker=body.ticker.upper(),
        price_cents=round(body.price * 100),
        direction=body.direction,
        message=body.message,
        workshop_chart_id=body.workshop_chart_id,
        notif_discord=body.notif_discord,
        notif_inapp=body.notif_inapp,
        status="armed",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _serialize(row)


@router.delete("/{alert_id}")
def cancel_alert(
    alert_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    row = db.query(PriceAlert).filter_by(id=alert_id, user_id=user.id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Alert not found")
    row.status = "cancelled"
    db.commit()
    return {"ok": True}
