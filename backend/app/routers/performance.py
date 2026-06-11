"""
Read-only performance analytics endpoints.
Feature-flagged by ENABLE_PERFORMANCE_ANALYTICS env var.
"""
from __future__ import annotations

import os
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies import get_current_user
from app.db.models.users import User
from app.db.models.bots import BotAllocation, BotProfile

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/performance", tags=["performance"])


def _flag():
    if os.getenv("ENABLE_PERFORMANCE_ANALYTICS", "true").strip().lower() != "true":
        raise HTTPException(status_code=404, detail="Performance analytics not enabled")


def _parse_days(period: str) -> Optional[int]:
    return {"7d": 7, "30d": 30, "90d": 90, "all": None}.get(period, 30)


def _alloc_for_bot(db: Session, bot_name: str, user_id: int) -> BotAllocation:
    profile = db.query(BotProfile).filter(BotProfile.name == bot_name).first()
    if not profile:
        raise HTTPException(status_code=404, detail=f"Bot '{bot_name}' not found")
    alloc = (
        db.query(BotAllocation)
        .filter(BotAllocation.profile_id == profile.id, BotAllocation.user_id == user_id)
        .first()
    )
    if not alloc:
        raise HTTPException(status_code=404, detail="No allocation for this bot")
    return alloc


# ── Portfolio ─────────────────────────────────────────────────────────────────

@router.get("/portfolio")
def get_portfolio_performance(
    period: str = Query("30d", regex="^(7d|30d|90d|all)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: None = Depends(_flag),
):
    from app.services.performance_service import compute_portfolio_metrics
    days = _parse_days(period)
    return compute_portfolio_metrics(db, current_user.id, days=days)


# ── Bot leaderboard ───────────────────────────────────────────────────────────

@router.get("/leaderboard")
def get_leaderboard(
    metric: str = Query("sharpe", regex="^(sharpe|total_return_pct|win_rate|profit_factor|today_pnl_usd)$"),
    period: str = Query("30d", regex="^(7d|30d|90d|all)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: None = Depends(_flag),
):
    from app.services.performance_service import compute_leaderboard
    days = _parse_days(period)
    return {"leaderboard": compute_leaderboard(db, current_user.id, metric=metric, days=days)}


# ── Per-bot metrics ───────────────────────────────────────────────────────────

@router.get("/bots/{bot_name}")
def get_bot_performance(
    bot_name: str,
    period: str = Query("30d", regex="^(7d|30d|90d|all)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: None = Depends(_flag),
):
    from app.services.performance_service import compute_bot_metrics
    alloc = _alloc_for_bot(db, bot_name, current_user.id)
    days = _parse_days(period)
    return compute_bot_metrics(db, alloc.id, days=days)


@router.get("/bots/{bot_name}/equity-curve")
def get_equity_curve(
    bot_name: str,
    days: int = Query(30, ge=1, le=3650),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: None = Depends(_flag),
):
    from app.services.performance_service import (
        _ckey, _cget, _cset, _EQUITY_CURVE_TTL,
        _build_equity_curve,
    )
    from app.db.models.bots import BotDailyPnL
    alloc = _alloc_for_bot(db, bot_name, current_user.id)
    cache_key = _ckey("eq_curve", alloc.id, days)
    cached = _cget(cache_key, _EQUITY_CURVE_TTL)
    if cached is not None:
        return {"curve": cached}

    pnl_rows = (
        db.query(BotDailyPnL)
        .filter(BotDailyPnL.allocation_id == alloc.id)
        .order_by(BotDailyPnL.date)
        .all()
    )
    curve = _build_equity_curve(pnl_rows, alloc.starting_capital_cents, days=days)
    _cset(cache_key, curve, _EQUITY_CURVE_TTL)
    return {"curve": curve}


@router.get("/bots/{bot_name}/monthly-returns")
def get_monthly_returns(
    bot_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: None = Depends(_flag),
):
    from app.services.performance_service import (
        _ckey, _cget, _cset, _EQUITY_CURVE_TTL,
        _build_equity_curve, _get_monthly_returns,
    )
    from app.db.models.bots import BotDailyPnL
    alloc = _alloc_for_bot(db, bot_name, current_user.id)
    cache_key = _ckey("monthly", alloc.id)
    cached = _cget(cache_key, _EQUITY_CURVE_TTL)
    if cached is not None:
        return {"monthly": cached}

    pnl_rows = (
        db.query(BotDailyPnL)
        .filter(BotDailyPnL.allocation_id == alloc.id)
        .order_by(BotDailyPnL.date)
        .all()
    )
    curve = _build_equity_curve(pnl_rows, alloc.starting_capital_cents)
    monthly = _get_monthly_returns(curve)
    _cset(cache_key, monthly, _EQUITY_CURVE_TTL)
    return {"monthly": monthly}


@router.get("/bots/{bot_name}/strategy-attribution")
def get_strategy_attribution(
    bot_name: str,
    period: str = Query("all", regex="^(7d|30d|90d|all)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: None = Depends(_flag),
):
    from app.services.performance_service import (
        _ckey, _cget, _cset, _DEFAULT_TTL,
        _get_closed_trade_pnls, _get_strategy_attribution,
    )
    from datetime import timedelta, timezone
    alloc = _alloc_for_bot(db, bot_name, current_user.id)
    days = _parse_days(period)
    since = (
        (__import__("datetime").datetime.now(timezone.utc) - timedelta(days=days))
        if days else None
    )
    cache_key = _ckey("strat_attr", alloc.id, period)
    cached = _cget(cache_key, _DEFAULT_TTL)
    if cached is not None:
        return {"attribution": cached}

    closed = _get_closed_trade_pnls(db, [alloc.id], since_date=since)
    attribution = _get_strategy_attribution(db, alloc.id, closed)

    # Compute raw_return_pct per strategy using allocated capital share
    starting_usd = (alloc.starting_capital_cents or 0) / 100
    for row in attribution:
        pnl_usd = row["pnl_cents"] / 100
        cap = starting_usd * (row.get("weight_pct", 100) or 100) / 100
        row["pnl_usd"] = round(pnl_usd, 2)
        row["raw_return_pct"] = round(pnl_usd / cap, 4) if cap > 0 else None
        row["capital_deployed_usd"] = round(cap, 2)
        del row["pnl_cents"]

    _cset(cache_key, attribution, _DEFAULT_TTL)
    return {"attribution": attribution, "total_capital_usd": round(starting_usd, 2)}


@router.get("/bots/{bot_name}/symbol-attribution")
def get_symbol_attribution(
    bot_name: str,
    top: int = Query(5, ge=1, le=20),
    period: str = Query("all", regex="^(7d|30d|90d|all)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: None = Depends(_flag),
):
    from app.services.performance_service import _get_closed_trade_pnls, _get_symbol_attribution
    from datetime import timedelta, timezone
    alloc = _alloc_for_bot(db, bot_name, current_user.id)
    days = _parse_days(period)
    since = (
        (__import__("datetime").datetime.now(timezone.utc) - timedelta(days=days))
        if days else None
    )
    closed = _get_closed_trade_pnls(db, [alloc.id], since_date=since)
    syms = _get_symbol_attribution(closed, top=top)
    for row in syms:
        row["pnl_usd"] = round(row.pop("pnl_cents") / 100, 2)
    return {"symbols": syms}


@router.get("/bots/{bot_name}/time-of-day")
def get_time_of_day(
    bot_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: None = Depends(_flag),
):
    from app.services.performance_service import _get_closed_trade_pnls, _get_time_of_day
    alloc = _alloc_for_bot(db, bot_name, current_user.id)
    closed = _get_closed_trade_pnls(db, [alloc.id])
    tod = _get_time_of_day(closed)
    for row in tod:
        row["avg_pnl_usd"] = round(row.pop("avg_pnl_cents") / 100, 2)
    return {"time_of_day": tod}


@router.get("/bots/{bot_name}/regime-breakdown")
def get_regime_breakdown(
    bot_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: None = Depends(_flag),
):
    from app.services.performance_service import _get_closed_trade_pnls, _get_regime_breakdown
    alloc = _alloc_for_bot(db, bot_name, current_user.id)
    closed = _get_closed_trade_pnls(db, [alloc.id])
    regime = _get_regime_breakdown(db, closed)
    for row in regime:
        row["pnl_usd"] = round(row.pop("pnl_cents") / 100, 2)
    return {"regimes": regime}


# ── Strategy leaderboard ──────────────────────────────────────────────────────

@router.get("/strategy-leaderboard")
def get_strategy_leaderboard(
    period: str = Query("30d", regex="^(7d|30d|90d|all)$"),
    sort: str = Query("pnl", regex="^(pnl|return|win_rate|trades|sharpe)$"),
    category: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: None = Depends(_flag),
):
    from app.services.performance_service import compute_strategy_leaderboard
    days = _parse_days(period)
    rows = compute_strategy_leaderboard(db, current_user.id, period_days=days, sort_by=sort)
    if category and category.lower() != "all":
        rows = [r for r in rows if r.get("category", "").lower() == category.lower()]
    return {"strategies": rows, "period": period, "sort": sort}
