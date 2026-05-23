from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.models.alert import AlertConfig, AlertTrigger
from app.db.models.users import User
from app.dependencies import get_db, get_current_user
from app.ws.manager import connection_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/alerts", tags=["alerts"])


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class AlertCreate(BaseModel):
    symbol: str
    signal_type: str
    threshold: Optional[float] = None


class TestSignalRequest(BaseModel):
    symbol: str
    signal_type: str
    message: str = "Test alert"
    value: Optional[float] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _alert_to_dict(a: AlertConfig) -> Dict[str, Any]:
    return {
        "id": a.id,
        "symbol": a.symbol,
        "signal_type": a.signal_type,
        "threshold": a.threshold,
        "enabled": a.enabled,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


def _trigger_to_dict(t: AlertTrigger) -> Dict[str, Any]:
    return {
        "id": t.id,
        "alert_config_id": t.alert_config_id,
        "signal_type": t.signal_type,
        "symbol": t.symbol,
        "value": t.value,
        "message": t.message,
        "triggered_at": t.triggered_at.isoformat() if t.triggered_at else None,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("")
def list_alerts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    alerts = db.query(AlertConfig).filter(AlertConfig.user_id == current_user.id).all()
    return {"alerts": [_alert_to_dict(a) for a in alerts]}


@router.post("", status_code=201)
def create_alert(
    body: AlertCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    alert = AlertConfig(
        symbol=body.symbol.upper().strip(),
        signal_type=body.signal_type,
        threshold=body.threshold,
        user_id=current_user.id,
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return _alert_to_dict(alert)


@router.delete("/{alert_id}")
def delete_alert(
    alert_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    alert = db.query(AlertConfig).filter(
        AlertConfig.id == alert_id, AlertConfig.user_id == current_user.id
    ).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    db.delete(alert)
    db.commit()
    return {"ok": True}


@router.get("/triggers")
def list_triggers(
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    triggers = (
        db.query(AlertTrigger)
        .join(AlertConfig, AlertTrigger.alert_config_id == AlertConfig.id)
        .filter(AlertConfig.user_id == current_user.id)
        .order_by(AlertTrigger.triggered_at.desc())
        .limit(limit)
        .all()
    )
    return {"triggers": [_trigger_to_dict(t) for t in triggers]}


@router.post("/test")
async def test_alert(
    body: TestSignalRequest, db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Manually fire a test signal — records a trigger and broadcasts via WebSocket."""
    # Find the matching alert config (if any) so we can record a trigger
    alert = (
        db.query(AlertConfig)
        .filter(
            AlertConfig.symbol == body.symbol.upper(),
            AlertConfig.signal_type == body.signal_type,
            AlertConfig.enabled.is_(True),
        )
        .first()
    )

    trigger_record: Optional[AlertTrigger] = None
    if alert:
        trigger_record = AlertTrigger(
            alert_config_id=alert.id,
            signal_type=body.signal_type,
            symbol=body.symbol.upper(),
            value=body.value,
            message=body.message,
        )
        db.add(trigger_record)
        db.commit()
        db.refresh(trigger_record)

    # Broadcast to all connected WebSocket clients
    ws_payload: Dict[str, Any] = {
        "type": "alert",
        "symbol": body.symbol.upper(),
        "signal_type": body.signal_type,
        "value": body.value,
        "message": body.message,
    }
    await connection_manager.broadcast(ws_payload)

    return {
        "status": "sent",
        "symbol": body.symbol.upper(),
        "signal_type": body.signal_type,
        "trigger_id": trigger_record.id if trigger_record else None,
    }
