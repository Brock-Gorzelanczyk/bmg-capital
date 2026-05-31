from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from alpaca.data.enums import DataFeed
from alpaca.data.requests import StockSnapshotRequest
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.alpaca.client import get_historical_client
from app.db.models.portfolio import Portfolio, Position
from app.db.models.users import User
from app.dependencies import get_db, get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class PortfolioCreate(BaseModel):
    name: str


class PositionCreate(BaseModel):
    symbol: str
    shares: float
    average_cost: float


class PositionUpdate(BaseModel):
    shares: Optional[float] = None
    average_cost: Optional[float] = None


class KellyRequest(BaseModel):
    win_rate: float           # 0.0–1.0
    avg_win_pct: float        # e.g. 0.15 for 15%
    avg_loss_pct: float       # e.g. 0.08 for 8% (positive number)
    account_size: float       # total account value in dollars
    kelly_fraction: float = 0.25  # default to quarter-Kelly


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _portfolio_to_dict(p: Portfolio, include_positions: bool = False) -> Dict[str, Any]:
    d: Dict[str, Any] = {
        "id": p.id,
        "name": p.name,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }
    if include_positions:
        d["positions"] = [_position_to_dict(pos) for pos in p.positions]
    return d


def _position_to_dict(pos: Position) -> Dict[str, Any]:
    return {
        "id": pos.id,
        "portfolio_id": pos.portfolio_id,
        "symbol": pos.symbol,
        "shares": pos.shares,
        "average_cost": pos.average_cost,
        "cost_basis": pos.shares * pos.average_cost,
        "opened_at": pos.opened_at.isoformat() if pos.opened_at else None,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("")
def list_portfolios(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    portfolios = db.query(Portfolio).filter(Portfolio.user_id == current_user.id).all()
    return {"portfolios": [_portfolio_to_dict(p) for p in portfolios]}


@router.post("", status_code=201)
def create_portfolio(
    body: PortfolioCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    p = Portfolio(name=body.name, user_id=current_user.id)
    db.add(p)
    db.commit()
    db.refresh(p)
    return _portfolio_to_dict(p, include_positions=True)


@router.get("/{portfolio_id}")
def get_portfolio(
    portfolio_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    p = db.query(Portfolio).filter(
        Portfolio.id == portfolio_id, Portfolio.user_id == current_user.id
    ).first()
    if not p:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    return _portfolio_to_dict(p, include_positions=True)


@router.post("/{portfolio_id}/positions", status_code=201)
def add_position(
    portfolio_id: int,
    body: PositionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    p = db.query(Portfolio).filter(
        Portfolio.id == portfolio_id, Portfolio.user_id == current_user.id
    ).first()
    if not p:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    symbol = body.symbol.upper().strip()
    existing = (
        db.query(Position)
        .filter(Position.portfolio_id == portfolio_id, Position.symbol == symbol)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=409, detail=f"Position for {symbol} already exists in this portfolio"
        )

    pos = Position(
        portfolio_id=portfolio_id,
        symbol=symbol,
        shares=body.shares,
        average_cost=body.average_cost,
    )
    db.add(pos)
    db.commit()
    db.refresh(pos)
    return _position_to_dict(pos)


@router.put("/{portfolio_id}/positions/{symbol}")
def update_position(
    portfolio_id: int,
    symbol: str,
    body: PositionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    symbol = symbol.upper()
    p = db.query(Portfolio).filter(
        Portfolio.id == portfolio_id, Portfolio.user_id == current_user.id
    ).first()
    if not p:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    pos = (
        db.query(Position)
        .filter(Position.portfolio_id == portfolio_id, Position.symbol == symbol)
        .first()
    )
    if not pos:
        raise HTTPException(status_code=404, detail=f"Position {symbol} not found")

    if body.shares is not None:
        pos.shares = body.shares
    if body.average_cost is not None:
        pos.average_cost = body.average_cost
    db.commit()
    db.refresh(pos)
    return _position_to_dict(pos)


@router.delete("/{portfolio_id}/positions/{symbol}")
def delete_position(
    portfolio_id: int,
    symbol: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    symbol = symbol.upper()
    p = db.query(Portfolio).filter(
        Portfolio.id == portfolio_id, Portfolio.user_id == current_user.id
    ).first()
    if not p:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    pos = (
        db.query(Position)
        .filter(Position.portfolio_id == portfolio_id, Position.symbol == symbol)
        .first()
    )
    if not pos:
        raise HTTPException(status_code=404, detail=f"Position {symbol} not found")
    db.delete(pos)
    db.commit()
    return {"ok": True}


@router.post("/kelly")
def kelly_position_sizer(
    body: KellyRequest,
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Kelly Criterion position sizer.

    Formula: K = (win_rate * avg_win_pct - loss_rate * avg_loss_pct) / avg_win_pct
    """
    win_rate = body.win_rate
    loss_rate = 1.0 - win_rate
    avg_win = body.avg_win_pct
    avg_loss = body.avg_loss_pct

    # Edge = expected value per dollar risked
    edge = win_rate * avg_win - loss_rate * avg_loss

    if avg_win <= 0:
        raise HTTPException(status_code=422, detail="avg_win_pct must be greater than 0")

    full_kelly_pct = edge / avg_win

    warning: Optional[str] = None
    if edge <= 0:
        warning = "Negative edge — do not trade"
        full_kelly_pct = 0.0

    recommended_pct = body.kelly_fraction * full_kelly_pct
    recommended_dollars = recommended_pct * body.account_size

    fraction_labels = {
        1.0:  "Full Kelly",
        0.5:  "Half-Kelly",
        0.25: "Quarter-Kelly",
        0.1:  "Tenth-Kelly",
    }
    fraction_label = fraction_labels.get(body.kelly_fraction, f"{body.kelly_fraction:.0%}-Kelly")

    if warning:
        interpretation = (
            f"This setup has a negative expected edge ({edge:.2%} per dollar risked). "
            "Do not size a position until the statistics improve."
        )
    else:
        interpretation = (
            f"Full Kelly suggests {full_kelly_pct:.1%} of capital. "
            f"At {fraction_label} ({body.kelly_fraction:.0%}× Kelly) that is "
            f"{recommended_pct:.1%} of your account, or "
            f"${recommended_dollars:,.0f} on a ${body.account_size:,.0f} account. "
            f"Expected edge is {edge:.2%} per dollar risked."
        )

    return {
        "full_kelly_pct": round(full_kelly_pct * 100, 4),
        "recommended_pct": round(recommended_pct * 100, 4),
        "recommended_dollars": round(recommended_dollars, 2),
        "max_shares_example": None,
        "edge": round(edge * 100, 4),
        "interpretation": interpretation,
        "warning": warning,
    }


@router.get("/{portfolio_id}/summary")
async def portfolio_summary(
    portfolio_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    p = db.query(Portfolio).filter(
        Portfolio.id == portfolio_id, Portfolio.user_id == current_user.id
    ).first()
    if not p:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    positions = p.positions
    if not positions:
        return {
            "portfolio_id": portfolio_id,
            "name": p.name,
            "positions": [],
            "total_value": 0.0,
            "total_cost": 0.0,
            "total_gain": 0.0,
            "total_gain_pct": 0.0,
        }

    symbols = [pos.symbol for pos in positions]
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
    except Exception as e:
        logger.error(f"Snapshot fetch error for portfolio {portfolio_id}: {e}", exc_info=True)

    enriched: List[Dict[str, Any]] = []
    total_value = 0.0
    total_cost = 0.0

    for pos in positions:
        current_price = prices.get(pos.symbol)
        cost_basis = pos.shares * pos.average_cost
        market_value = pos.shares * current_price if current_price is not None else None
        gain = (market_value - cost_basis) if market_value is not None else None
        gain_pct = (gain / cost_basis * 100) if (gain is not None and cost_basis) else None

        total_cost += cost_basis
        if market_value is not None:
            total_value += market_value

        enriched.append(
            {
                **_position_to_dict(pos),
                "current_price": current_price,
                "market_value": market_value,
                "gain": gain,
                "gain_pct": gain_pct,
            }
        )

    total_gain = total_value - total_cost
    total_gain_pct = (total_gain / total_cost * 100) if total_cost else 0.0

    return {
        "portfolio_id": portfolio_id,
        "name": p.name,
        "positions": enriched,
        "total_value": total_value,
        "total_cost": total_cost,
        "total_gain": total_gain,
        "total_gain_pct": total_gain_pct,
    }
