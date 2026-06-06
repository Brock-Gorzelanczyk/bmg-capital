"""
/api/portfolio — bot-aggregate portfolio view.

All endpoints read from the same canonical source as /api/strategy-lab/portfolio:
BotAllocation + BotDailyPnL + BotPosition tables.

Legacy personal-portfolio and paper-account tables were archived 2026-06-06.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
from app.db.models.users import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.get("")
@router.get("/")
async def get_portfolio(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Aggregate portfolio across all bot allocations (same data as /api/strategy-lab/portfolio)."""
    try:
        from app.core.canonical import compute_strategy_lab_aggregate
        return compute_strategy_lab_aggregate(current_user.id, db)
    except Exception as exc:
        logger.error("portfolio aggregate failed for user %s: %s", current_user.id, exc)
        return {
            "total_value_cents": 0,
            "today_pnl_cents": 0,
            "today_pnl_pct": 0.0,
            "return_30d_pct": 0.0,
            "return_all_time_pct": 0.0,
            "portfolios": [],
            "leaderboard": [],
        }


@router.get("/summary")
async def get_portfolio_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Summary view — same as aggregate but aliased for legacy frontend callers."""
    try:
        from app.core.canonical import compute_strategy_lab_aggregate
        data = compute_strategy_lab_aggregate(current_user.id, db)
        return {
            "total_value_cents": data.get("total_value_cents", 0),
            "today_pnl_cents": data.get("today_pnl_cents", 0),
            "today_pnl_pct": data.get("today_pnl_pct", 0.0),
            "return_all_time_pct": data.get("return_all_time_pct", 0.0),
            "return_30d_pct": data.get("return_30d_pct", 0.0),
            "open_positions": data.get("total_open_positions", 0),
            "portfolios": data.get("portfolios", []),
        }
    except Exception as exc:
        logger.error("portfolio summary failed for user %s: %s", current_user.id, exc)
        return {}
