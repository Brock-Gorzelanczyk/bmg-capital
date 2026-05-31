from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from alpaca.data.enums import DataFeed
from alpaca.data.requests import StockSnapshotRequest
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.alpaca.client import get_historical_client
from app.db.models.pod import Pod, PodPosition
from app.db.models.users import User
from app.dependencies import get_db, get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/pods", tags=["pods"])


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class PodCreate(BaseModel):
    name: str
    description: Optional[str] = None
    color: str = "#3B82F6"
    emoji: str = "📊"
    allocated_capital: float = 0.0
    drawdown_stop_pct: float = 7.0


class PodUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = None
    emoji: Optional[str] = None
    allocated_capital: Optional[float] = None
    drawdown_stop_pct: Optional[float] = None
    is_active: Optional[bool] = None


class PodPositionCreate(BaseModel):
    symbol: str
    shares: float
    average_cost: float


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pod_to_dict(pod: Pod) -> Dict[str, Any]:
    return {
        "id": pod.id,
        "user_id": pod.user_id,
        "name": pod.name,
        "description": pod.description,
        "color": pod.color,
        "emoji": pod.emoji,
        "allocated_capital": pod.allocated_capital,
        "drawdown_stop_pct": pod.drawdown_stop_pct,
        "is_active": pod.is_active,
        "is_derisked": pod.is_derisked,
        "derisked_at": pod.derisked_at.isoformat() if pod.derisked_at else None,
        "created_at": pod.created_at.isoformat() if pod.created_at else None,
    }


def _pod_position_to_dict(pos: PodPosition) -> Dict[str, Any]:
    return {
        "id": pos.id,
        "pod_id": pos.pod_id,
        "symbol": pos.symbol,
        "shares": pos.shares,
        "average_cost": pos.average_cost,
        "cost_basis": pos.shares * pos.average_cost,
        "opened_at": pos.opened_at.isoformat() if pos.opened_at else None,
    }


def _fetch_prices(symbols: List[str]) -> Dict[str, float]:
    """Fetch latest prices via Alpaca snapshot. Returns {} on error."""
    if not symbols:
        return {}
    prices: Dict[str, float] = {}
    try:
        client = get_historical_client()
        req = StockSnapshotRequest(symbol_or_symbols=symbols, feed=DataFeed.IEX)
        snapshots = client.get_stock_snapshot(req)
        for sym in symbols:
            if sym in snapshots:
                snap = snapshots[sym]
                daily = snap.daily_bar
                if daily:
                    prices[sym] = float(daily.close)
    except Exception as exc:
        logger.error("Alpaca snapshot fetch error for pods: %s", exc, exc_info=True)
    return prices


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("")
def list_pods(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    pods = db.query(Pod).filter(Pod.user_id == current_user.id).all()
    return {"pods": [_pod_to_dict(p) for p in pods]}


@router.post("", status_code=201)
def create_pod(
    body: PodCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    pod = Pod(
        user_id=current_user.id,
        name=body.name,
        description=body.description,
        color=body.color,
        emoji=body.emoji,
        allocated_capital=body.allocated_capital,
        drawdown_stop_pct=body.drawdown_stop_pct,
    )
    db.add(pod)
    db.commit()
    db.refresh(pod)
    return _pod_to_dict(pod)


@router.put("/{pod_id}")
def update_pod(
    pod_id: int,
    body: PodUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    pod = db.query(Pod).filter(Pod.id == pod_id, Pod.user_id == current_user.id).first()
    if not pod:
        raise HTTPException(status_code=404, detail="Pod not found")

    if body.name is not None:
        pod.name = body.name
    if body.description is not None:
        pod.description = body.description
    if body.color is not None:
        pod.color = body.color
    if body.emoji is not None:
        pod.emoji = body.emoji
    if body.allocated_capital is not None:
        pod.allocated_capital = body.allocated_capital
    if body.drawdown_stop_pct is not None:
        pod.drawdown_stop_pct = body.drawdown_stop_pct
    if body.is_active is not None:
        pod.is_active = body.is_active

    db.commit()
    db.refresh(pod)
    return _pod_to_dict(pod)


@router.delete("/{pod_id}")
def delete_pod(
    pod_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    pod = db.query(Pod).filter(Pod.id == pod_id, Pod.user_id == current_user.id).first()
    if not pod:
        raise HTTPException(status_code=404, detail="Pod not found")

    position_count = db.query(PodPosition).filter(PodPosition.pod_id == pod_id).count()
    if position_count > 0:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot delete pod with {position_count} active position(s). Remove positions first.",
        )

    db.delete(pod)
    db.commit()
    return {"ok": True}


@router.get("/{pod_id}/positions")
def list_pod_positions(
    pod_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    pod = db.query(Pod).filter(Pod.id == pod_id, Pod.user_id == current_user.id).first()
    if not pod:
        raise HTTPException(status_code=404, detail="Pod not found")

    positions = db.query(PodPosition).filter(PodPosition.pod_id == pod_id).all()
    return {"positions": [_pod_position_to_dict(p) for p in positions]}


@router.post("/{pod_id}/positions", status_code=201)
def add_pod_position(
    pod_id: int,
    body: PodPositionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    pod = db.query(Pod).filter(Pod.id == pod_id, Pod.user_id == current_user.id).first()
    if not pod:
        raise HTTPException(status_code=404, detail="Pod not found")

    symbol = body.symbol.upper().strip()
    existing = (
        db.query(PodPosition)
        .filter(PodPosition.pod_id == pod_id, PodPosition.symbol == symbol)
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail=f"Position {symbol} already exists in this pod")

    pos = PodPosition(
        pod_id=pod_id,
        user_id=current_user.id,
        symbol=symbol,
        shares=body.shares,
        average_cost=body.average_cost,
    )
    db.add(pos)
    db.commit()
    db.refresh(pos)
    return _pod_position_to_dict(pos)


@router.delete("/{pod_id}/positions/{symbol}")
def remove_pod_position(
    pod_id: int,
    symbol: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    pod = db.query(Pod).filter(Pod.id == pod_id, Pod.user_id == current_user.id).first()
    if not pod:
        raise HTTPException(status_code=404, detail="Pod not found")

    symbol = symbol.upper()
    pos = (
        db.query(PodPosition)
        .filter(PodPosition.pod_id == pod_id, PodPosition.symbol == symbol)
        .first()
    )
    if not pos:
        raise HTTPException(status_code=404, detail=f"Position {symbol} not found in pod")

    db.delete(pos)
    db.commit()
    return {"ok": True}


@router.get("/{pod_id}/summary")
async def pod_summary(
    pod_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    pod = db.query(Pod).filter(Pod.id == pod_id, Pod.user_id == current_user.id).first()
    if not pod:
        raise HTTPException(status_code=404, detail="Pod not found")

    positions = db.query(PodPosition).filter(PodPosition.pod_id == pod_id).all()

    if not positions:
        return {
            **_pod_to_dict(pod),
            "total_value": 0.0,
            "total_cost": 0.0,
            "gain_pct": 0.0,
            "drawdown_pct": 0.0,
            "at_risk": False,
            "positions": [],
        }

    symbols = [p.symbol for p in positions]
    prices = _fetch_prices(symbols)

    enriched: List[Dict[str, Any]] = []
    total_value = 0.0
    total_cost = 0.0

    for pos in positions:
        cost_basis = pos.shares * pos.average_cost
        current_price = prices.get(pos.symbol)
        market_value = pos.shares * current_price if current_price is not None else None
        gain = (market_value - cost_basis) if market_value is not None else None
        gain_pct = (gain / cost_basis * 100) if (gain is not None and cost_basis) else None

        total_cost += cost_basis
        if market_value is not None:
            total_value += market_value
        else:
            total_value += cost_basis  # fall back to cost when no price

        enriched.append(
            {
                **_pod_position_to_dict(pos),
                "current_price": current_price,
                "market_value": market_value,
                "gain_pct": gain_pct,
            }
        )

    overall_gain_pct = ((total_value - total_cost) / total_cost * 100) if total_cost else 0.0

    # Drawdown from allocated capital (the "peak" for this pod)
    peak = pod.allocated_capital if pod.allocated_capital > 0 else total_cost
    if peak > 0:
        drawdown_pct = max(0.0, (peak - total_value) / peak * 100)
    else:
        drawdown_pct = 0.0

    at_risk = drawdown_pct >= (pod.drawdown_stop_pct * 0.75)

    return {
        **_pod_to_dict(pod),
        "total_value": round(total_value, 2),
        "total_cost": round(total_cost, 2),
        "gain_pct": round(overall_gain_pct, 4),
        "drawdown_pct": round(drawdown_pct, 4),
        "at_risk": at_risk,
        "positions": enriched,
    }


@router.post("/{pod_id}/derisk")
def derisk_pod(
    pod_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    pod = db.query(Pod).filter(Pod.id == pod_id, Pod.user_id == current_user.id).first()
    if not pod:
        raise HTTPException(status_code=404, detail="Pod not found")

    pod.is_derisked = True
    pod.derisked_at = datetime.now(tz=timezone.utc)
    db.commit()
    db.refresh(pod)

    positions = db.query(PodPosition).filter(PodPosition.pod_id == pod_id).all()
    recommendations = [
        {
            "symbol": pos.symbol,
            "current_shares": pos.shares,
            "sell_shares": round(pos.shares * 0.5, 6),
            "keep_shares": round(pos.shares * 0.5, 6),
            "action": f"Sell {round(pos.shares * 0.5, 6)} shares of {pos.symbol} (50% de-risk)",
        }
        for pos in positions
    ]

    return {
        "pod": _pod_to_dict(pod),
        "message": f"Pod '{pod.name}' marked as de-risked. Sell 50% of each position.",
        "recommendations": recommendations,
    }
