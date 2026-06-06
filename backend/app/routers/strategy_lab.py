"""
Strategy Lab — portfolio overview endpoint.

GET /api/strategy-lab/portfolio  — aggregated portfolio metrics across all enabled
                                    bot allocations for the current user.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Dict, List

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
import random
from datetime import datetime, timezone

from app.db.models.bots import (
    BotAllocation,
    BotDailyPnL,
    BotPosition,
    BotProfile,
    BotSignal,
    BotWatchlist,
)
from app.db.models.users import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/strategy-lab", tags=["strategy-lab"])

PROFILE_NAMES: Dict[str, str] = {
    "stock_swing": "Stock Swing",
    "stock_day": "Stock Day",
    "stock_lt": "Stock Long-Term",
    "crypto_swing": "Crypto Swing",
    "crypto_day": "Crypto Day",
    "crypto_lt": "Crypto Long-Term",
}


# ── Demo seed config ──────────────────────────────────────────────────────────

_DEMO_BOTS = [
    {"name": "stock_swing",  "starting_cents": 2500000,  "daily_drift": 0.0024, "daily_vol": 0.008},
    {"name": "stock_day",    "starting_cents": 1500000,  "daily_drift": 0.0041, "daily_vol": 0.012},
    {"name": "stock_lt",     "starting_cents": 5000000,  "daily_drift": 0.0010, "daily_vol": 0.004},
    {"name": "crypto_swing", "starting_cents": 1000000,  "daily_drift": 0.0062, "daily_vol": 0.022},
    {"name": "crypto_day",   "starting_cents": 1000000,  "daily_drift": 0.0031, "daily_vol": 0.016},
    {"name": "crypto_lt",    "starting_cents": 2000000,  "daily_drift": 0.0019, "daily_vol": 0.010},
]

_DEMO_WATCHLISTS = {
    "stock_swing":  [("NVDA",88),("META",82),("MSFT",79),("AAPL",76),("AMZN",73),("GOOGL",69),("TSM",65),("AMD",61)],
    "stock_day":    [("SPY",91),("QQQ",87),("TSLA",83),("GME",76),("AMC",71),("PLTR",68),("RIVN",63)],
    "stock_lt":     [("VTI",94),("VOO",92),("QQQ",88),("VEA",81),("BND",77),("VNQ",72),("GLD",68),("IWM",64)],
    "crypto_swing": [("BTC/USD",89),("ETH/USD",85),("SOL/USD",78),("AVAX/USD",72),("LINK/USD",65)],
    "crypto_day":   [("BTC/USD",92),("ETH/USD",88),("SOL/USD",81),("BNB/USD",74),("MATIC/USD",67)],
    "crypto_lt":    [("BTC/USD",95),("ETH/USD",91),("SOL/USD",84),("AVAX/USD",77),("LINK/USD",70),("DOT/USD",63)],
}

_DEMO_POSITIONS = {
    "stock_swing":  [("NVDA", 12, 108700), ("META", 8, 51200)],
    "stock_day":    [("SPY",  10, 52800)],
    "crypto_swing": [("BTC/USD", 0.15, 990000), ("ETH/USD", 1.2, 320000)],
    "crypto_day":   [("ETH/USD", 0.8, 319500)],
}

_DEMO_SIGNALS = {
    "stock_swing": [
        ("NVDA","buy","golden_cross","Golden cross on daily chart — 50MA crossed above 200MA with 2.3× vol surge.",0.82),
        ("META","buy","momentum_breakout","Broke 52-week high on earnings beat; RSI 68 but not overbought yet.",0.75),
    ],
    "stock_day":   [("SPY","buy","orb_stocks_in_play","5-min ORB breakout above VWAP; RVOL 1.8×; first 30-min trend intact.",0.79)],
    "crypto_swing":[
        ("BTC/USD","buy","crypto_momentum_breakout","BTC cleared $66k resistance on above-avg volume; funding rate neutral.",0.84),
        ("ETH/USD","buy","crypto_ema_cross","EMA20 crossed EMA50 on 4h; ETH/BTC ratio rising.",0.71),
    ],
    "crypto_day":  [("ETH/USD","buy","crypto_intraday_momentum","1h momentum band break; volume 1.5× 20-day avg.",0.73)],
}


def _seed_demo_allocations(db: Session, user_id: int) -> None:
    """Create default allocations + 30-day history for a new user. Idempotent."""
    today = date.today()
    rng = random.Random(user_id * 42)  # deterministic per user

    for cfg in _DEMO_BOTS:
        profile = db.execute(
            select(BotProfile).where(BotProfile.name == cfg["name"])
        ).scalar()
        if not profile:
            continue

        alloc = db.execute(
            select(BotAllocation).where(
                BotAllocation.user_id == user_id,
                BotAllocation.profile_id == profile.id,
            )
        ).scalar()

        if not alloc:
            alloc = BotAllocation(
                user_id=user_id,
                profile_id=profile.id,
                capital_pct=10.0,
                risk_profile="standard",
                paper_mode=True,
                enabled=True,
                starting_capital_cents=cfg["starting_cents"],
            )
            db.add(alloc)
            db.flush()

        # Seed 35 days of daily P&L (skip if already has data)
        existing_count = db.execute(
            select(func.count(BotDailyPnL.id)).where(BotDailyPnL.allocation_id == alloc.id)
        ).scalar() or 0
        if existing_count < 5:
            value = cfg["starting_cents"]
            for days_ago in range(34, -1, -1):
                d = today - timedelta(days=days_ago)
                if d.weekday() >= 5 and not cfg["name"].startswith("crypto"):
                    continue  # skip weekends for stock bots
                daily_ret = rng.gauss(cfg["daily_drift"], cfg["daily_vol"])
                daily_ret = max(-0.04, min(0.06, daily_ret))
                delta = int(value * daily_ret)
                realized = max(0, delta)
                unrealized = min(0, delta)
                value = value + delta
                db.add(BotDailyPnL(
                    allocation_id=alloc.id,
                    date=d,
                    realized_cents=realized,
                    unrealized_cents=unrealized,
                    fees_cents=abs(int(realized * 0.002)),
                    portfolio_value_eod_cents=value,
                ))

        # Seed watchlist (skip if already has rows)
        wl_count = db.execute(
            select(func.count(BotWatchlist.id)).where(BotWatchlist.profile_id == profile.id)
        ).scalar() or 0
        if wl_count == 0:
            for rank, (sym, score) in enumerate(_DEMO_WATCHLISTS.get(cfg["name"], []), 1):
                db.add(BotWatchlist(
                    profile_id=profile.id,
                    symbol=sym,
                    score=float(score),
                    rank=rank,
                    reasons={"momentum": score * 0.4, "volume": score * 0.35, "rsi": score * 0.25},
                    status="active",
                    last_evaluated_at=datetime.now(timezone.utc),
                ))

        # Seed open positions (skip if already has rows)
        pos_count = db.execute(
            select(func.count(BotPosition.id)).where(
                BotPosition.allocation_id == alloc.id,
                BotPosition.closed_at.is_(None),
            )
        ).scalar() or 0
        if pos_count == 0:
            for sym, qty, cost in _DEMO_POSITIONS.get(cfg["name"], []):
                pos = BotPosition(
                    allocation_id=alloc.id,
                    symbol=sym,
                    qty=qty,
                    avg_cost_cents=cost,
                    opened_at=datetime.now(timezone.utc) - timedelta(days=rng.randint(1, 5)),
                    is_paper=True,
                )
                db.add(pos)
                db.flush()

                # Seed the signal that opened it
                for sig_sym, side, strategy, reason, conf in _DEMO_SIGNALS.get(cfg["name"], []):
                    if sig_sym == sym:
                        db.add(BotSignal(
                            allocation_id=alloc.id,
                            ts=pos.opened_at,
                            symbol=sym,
                            side=side,
                            confidence=conf,
                            size_hint=0.15,
                            reason=reason,
                            strategy=strategy,
                        ))

    try:
        db.commit()
        logger.info("Demo allocations seeded for user %d", user_id)
    except Exception as exc:
        db.rollback()
        logger.error("Demo seed failed for user %d: %s", user_id, exc)


@router.get("/portfolio")
def get_portfolio(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Return aggregated portfolio metrics for the current user's Strategy Lab bots.

    Delegates entirely to compute_strategy_lab_aggregate() — the single canonical
    source of truth — so that the headline numbers and the leaderboard always derive
    from the same computation as every other surface that shows bot performance.

    If no StrategyPortfolio rows exist yet for this user (first visit before
    /bots/portfolios/setup has run), we fall back to seeding demo allocations via
    the legacy path so the page always shows something useful.
    """
    from app.core.canonical import compute_strategy_lab_aggregate
    from app.db.models.bots import StrategyPortfolio
    from app.routers.bots import _ensure_portfolios_for_user

    # Ensure the user has StrategyPortfolio rows (idempotent — creates them if missing).
    # This is the same setup that /api/bots/portfolios/setup calls, so calling it here
    # guarantees the canonical aggregate always has portfolios to read from.
    port_count = db.execute(
        select(func.count()).select_from(StrategyPortfolio).where(
            StrategyPortfolio.user_id == current_user.id
        )
    ).scalar() or 0

    if port_count == 0:
        try:
            # Create StrategyPortfolio rows and link allocations (canonical setup).
            _ensure_portfolios_for_user(db, current_user.id)
            # Seed 35 days of demo BotDailyPnL history so the headline has real values.
            _seed_demo_allocations(db, current_user.id)
        except Exception:
            logger.exception("Failed to auto-setup portfolios for user %d", current_user.id)

    result = compute_strategy_lab_aggregate(current_user.id, db)

    # If aggregate returns empty (no portfolios seeded), return safe zeros.
    if not result:
        return {
            "total_value_cents": 0,
            "yesterday_value_cents": 0,
            "today_pnl_cents": 0,
            "today_pnl_pct": 0.0,
            "return_30d_pct": 0.0,
            "return_30d_value_cents": 0,
            "return_all_time_pct": 0.0,
            "sharpe_30d": 0.0,
            "total_open_positions": 0,
            "total_watchlist_count": 0,
            "equity_curve": [],
            "leaderboard": [],
            "best_performer": None,
            "worst_performer": None,
        }

    return result
