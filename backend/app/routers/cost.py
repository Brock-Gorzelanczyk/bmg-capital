"""Cost analysis endpoint — round-trip cost estimation for bot trades."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.models.bots import BotAllocation, BotProfile, BotTrade
from app.db.models.users import User
from app.db.session import get_db
from app.dependencies import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cost", tags=["cost"])


class TradeInput(BaseModel):
    symbol: str
    side: str
    qty: float
    price: float
    exchange: Optional[str] = None
    adv_dollar: Optional[float] = None
    daily_vol: Optional[float] = None
    order_type: str = "market"
    holding_hours: Optional[float] = None


class CostAnalysisBody(BaseModel):
    bot_name: Optional[str] = None
    trades: Optional[list[TradeInput]] = None
    gross_return_pct: float = 0.0
    days_back: int = 30


@router.post("/analysis")
def cost_analysis(
    body: CostAnalysisBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Estimate round-trip trading costs for a bot or an explicit trade list.

    Two modes:
    - bot_name: fetches recent BotTrade records for the named bot profile and
      estimates costs using the cost model.
    - trades: accepts an explicit list of trade dicts and runs the cost model
      directly (useful for prospective analysis before trading).

    Both modes return the same response shape.
    """
    from strategy_lab.core.cost_model import cost_per_trade, estimate_bot_daily_costs, infer_exchange

    trade_dicts: list[dict[str, Any]] = []

    if body.bot_name:
        profile = db.query(BotProfile).filter(BotProfile.name == body.bot_name).first()
        if not profile:
            raise HTTPException(status_code=404, detail=f"Bot '{body.bot_name}' not found")

        allocs = db.query(BotAllocation).filter(
            BotAllocation.profile_id == profile.id,
            BotAllocation.user_id == current_user.id,
        ).all()
        alloc_ids = [a.id for a in allocs]

        if not alloc_ids:
            raise HTTPException(status_code=404, detail=f"No allocation found for bot '{body.bot_name}'")

        cutoff = datetime.now(timezone.utc).replace(tzinfo=None)
        from datetime import timedelta
        cutoff -= timedelta(days=body.days_back)

        trades_db = (
            db.query(BotTrade)
            .filter(BotTrade.allocation_id.in_(alloc_ids), BotTrade.ts >= cutoff)
            .order_by(BotTrade.ts.desc())
            .limit(500)
            .all()
        )

        for t in trades_db:
            price = (t.fill_price_cents or 0) / 100.0
            exchange = infer_exchange(body.bot_name, t.symbol)
            trade_dicts.append({
                "symbol": t.symbol,
                "side": t.side,
                "qty": t.qty,
                "price": price,
                "exchange": exchange,
            })

    elif body.trades:
        for t in body.trades:
            exchange = t.exchange or infer_exchange("", t.symbol)
            trade_dicts.append({
                "symbol": t.symbol,
                "side": t.side,
                "qty": t.qty,
                "price": t.price,
                "exchange": exchange,
                "adv_dollar": t.adv_dollar,
                "daily_vol": t.daily_vol,
                "order_type": t.order_type,
                "holding_hours": t.holding_hours,
            })
    else:
        raise HTTPException(
            status_code=422,
            detail="Provide either 'bot_name' to analyse recent trades or 'trades' for prospective analysis.",
        )

    if not trade_dicts:
        return {
            "bot_name": body.bot_name,
            "n_trades": 0,
            "total_cost_pct": 0.0,
            "net_return_pct": body.gross_return_pct,
            "cost_drag_pct": 0.0,
            "per_trade_avg_bps": 0.0,
            "gross_return_pct": body.gross_return_pct,
            "breakdown": [],
        }

    rollup = estimate_bot_daily_costs(trade_dicts, body.gross_return_pct)

    breakdown = []
    for td in trade_dicts[:50]:  # cap itemized list at 50
        try:
            est = cost_per_trade(
                symbol=td["symbol"],
                side=td["side"],
                qty=td["qty"],
                price=td["price"],
                exchange=td["exchange"],
                adv_dollar=td.get("adv_dollar"),
                daily_vol=td.get("daily_vol"),
                order_type=td.get("order_type", "market"),
                holding_hours=td.get("holding_hours"),
            )
            breakdown.append({
                "symbol": td["symbol"],
                "side": td["side"],
                "qty": td["qty"],
                "price": td["price"],
                "exchange": td["exchange"],
                "fee_bps": est.fee_bps,
                "spread_bps": est.spread_bps,
                "impact_bps": est.impact_bps,
                "slippage_bps": est.slippage_bps,
                "funding_bps": est.funding_bps,
                "total_bps": est.total_bps,
                "total_pct": est.total_pct,
            })
        except Exception as exc:
            logger.debug("[cost/analysis] skipped trade %s: %s", td.get("symbol"), exc)

    return {
        "bot_name": body.bot_name,
        "gross_return_pct": body.gross_return_pct,
        **rollup,
        "breakdown": breakdown,
    }
