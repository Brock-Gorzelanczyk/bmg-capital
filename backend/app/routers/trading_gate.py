"""Trading gate admin endpoints — halt, reopen, status, audit."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
from app.db.models.users import User
from app.services.trading_gate import TradingGate

router = APIRouter(prefix="/api/trading-gate", tags=["trading-gate"])

_ALLOWED_IPS = {ip.strip() for ip in os.getenv("GATE_ADMIN_IPS", "127.0.0.1").split(",") if ip.strip()}


def _require_admin(request: Request, current_user: User = Depends(get_current_user)):
    """Restrict halt/reopen to admin users or allowed IPs."""
    if not getattr(current_user, "is_admin", False):
        client_ip = request.client.host if request.client else ""
        if client_ip not in _ALLOWED_IPS:
            raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


class HaltBody(BaseModel):
    reason: str


@router.get("/status")
def gate_status(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    try:
        row = db.execute(text(
            "SELECT is_open, halt_reason, halted_at, halted_by, reopened_at FROM trading_gate_state "
            "ORDER BY id DESC LIMIT 1"
        )).fetchone()
    except Exception:
        return {"is_open": True, "error": "table not yet created"}

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff = now - timedelta(hours=24)
    try:
        block_count = db.execute(text(
            "SELECT COUNT(*) FROM trading_gate_audit "
            "WHERE event='order_blocked' AND created_at >= :cutoff"
        ), {"cutoff": cutoff}).scalar() or 0
    except Exception:
        block_count = 0

    if row is None:
        return {"is_open": True, "halt_reason": None, "halted_at": None,
                "last_24h_blocks_count": block_count}
    return {
        "is_open": bool(row[0]),
        "halt_reason": row[1],
        "halted_at": row[2],
        "halted_by": row[3],
        "reopened_at": row[4],
        "last_24h_blocks_count": block_count,
    }


@router.post("/halt")
def halt_trading(
    body: HaltBody,
    request: Request,
    current_user: User = Depends(_require_admin),
) -> dict[str, Any]:
    TradingGate.halt(reason=body.reason, halted_by="manual")
    return {"status": "halted", "reason": body.reason}


@router.post("/reopen")
def reopen_trading(
    request: Request,
    current_user: User = Depends(_require_admin),
) -> dict[str, Any]:
    TradingGate.reopen(reopened_by="manual")
    return {"status": "open"}


@router.get("/audit")
def gate_audit(
    days: int = 7,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).replace(tzinfo=None)
    try:
        rows = db.execute(text(
            "SELECT id, event, reason, symbol, bot_id, metadata, created_at "
            "FROM trading_gate_audit WHERE created_at >= :cutoff ORDER BY id DESC LIMIT 200"
        ), {"cutoff": cutoff}).fetchall()
    except Exception:
        return {"events": [], "error": "table not yet created"}

    return {
        "events": [
            {
                "id": r[0], "event": r[1], "reason": r[2],
                "symbol": r[3], "bot_id": r[4], "metadata": r[5], "created_at": r[6],
            }
            for r in rows
        ]
    }
