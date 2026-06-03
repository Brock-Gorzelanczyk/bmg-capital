"""
Strategy Lab — portfolio overview endpoint.

GET /api/strategy-lab/portfolio  — aggregated portfolio metrics across all enabled
                                    bot allocations for the current user.
"""
from __future__ import annotations

import logging
import statistics
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

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
    """Return aggregated portfolio metrics for the current user's enabled bots."""

    today = date.today()
    yesterday = today - timedelta(days=1)
    thirty_days_ago = today - timedelta(days=30)
    ninety_days_ago = today - timedelta(days=90)

    # ── 1. Enabled allocations (auto-seed if first visit) ────────────────────
    allocations: List[BotAllocation] = db.execute(
        select(BotAllocation).where(
            BotAllocation.user_id == current_user.id,
            BotAllocation.enabled.is_(True),
        )
    ).scalars().all()

    if not allocations:
        _seed_demo_allocations(db, current_user.id)
        allocations = db.execute(
            select(BotAllocation).where(
                BotAllocation.user_id == current_user.id,
                BotAllocation.enabled.is_(True),
            )
        ).scalars().all()

    alloc_ids = [a.id for a in allocations]

    # ── 2. Latest portfolio value per allocation ──────────────────────────────
    # Subquery: max date per allocation_id within last 90 days
    def _latest_value(alloc: BotAllocation) -> int:
        """Return the most recent portfolio_value_eod_cents for an allocation."""
        row = db.execute(
            select(BotDailyPnL.portfolio_value_eod_cents)
            .where(
                BotDailyPnL.allocation_id == alloc.id,
                BotDailyPnL.portfolio_value_eod_cents.is_not(None),
            )
            .order_by(BotDailyPnL.date.desc())
            .limit(1)
        ).scalar()
        if row is not None:
            return int(row)
        # Fall back to starting capital when no PnL history exists
        return int(alloc.starting_capital_cents or 0)

    allocation_values: Dict[int, int] = {a.id: _latest_value(a) for a in allocations}
    total_value_cents: int = sum(allocation_values.values())

    # ── 3. Yesterday's total value ────────────────────────────────────────────
    def _value_on_date(alloc: BotAllocation, target_date: date) -> int:
        row = db.execute(
            select(BotDailyPnL.portfolio_value_eod_cents)
            .where(
                BotDailyPnL.allocation_id == alloc.id,
                BotDailyPnL.date == target_date,
                BotDailyPnL.portfolio_value_eod_cents.is_not(None),
            )
            .limit(1)
        ).scalar()
        if row is not None:
            return int(row)
        return int(alloc.starting_capital_cents or 0)

    yesterday_value_cents: int = sum(
        _value_on_date(a, yesterday) for a in allocations
    )

    # ── 4. Today's PnL ───────────────────────────────────────────────────────
    today_pnl_rows = db.execute(
        select(BotDailyPnL).where(
            BotDailyPnL.allocation_id.in_(alloc_ids),
            BotDailyPnL.date == today,
        )
    ).scalars().all() if alloc_ids else []

    today_pnl_cents: int = sum(
        (r.realized_cents or 0) + (r.unrealized_cents or 0) - (r.fees_cents or 0)
        for r in today_pnl_rows
    )

    try:
        today_pnl_pct: float = round(today_pnl_cents / yesterday_value_cents * 100, 2) if yesterday_value_cents else 0.0
    except ZeroDivisionError:
        today_pnl_pct = 0.0

    # ── 5. 30-day return ─────────────────────────────────────────────────────
    value_30d_ago: int = sum(
        _value_on_date(a, thirty_days_ago) for a in allocations
    )
    try:
        return_30d_pct: float = round((total_value_cents - value_30d_ago) / value_30d_ago * 100, 2) if value_30d_ago else 0.0
    except ZeroDivisionError:
        return_30d_pct = 0.0
    return_30d_value_cents: int = total_value_cents - value_30d_ago

    # ── 6. All-time return ────────────────────────────────────────────────────
    total_starting: int = sum(int(a.starting_capital_cents or 0) for a in allocations)
    try:
        return_all_time_pct: float = round((total_value_cents - total_starting) / total_starting * 100, 2) if total_starting else 0.0
    except ZeroDivisionError:
        return_all_time_pct = 0.0

    # ── 7. Equity curve (last 90 days, daily sum across all allocations) ──────
    equity_curve: List[Dict[str, Any]] = []
    if alloc_ids:
        curve_rows = db.execute(
            select(
                BotDailyPnL.date,
                func.sum(BotDailyPnL.portfolio_value_eod_cents).label("total"),
            )
            .where(
                BotDailyPnL.allocation_id.in_(alloc_ids),
                BotDailyPnL.date >= ninety_days_ago,
                BotDailyPnL.portfolio_value_eod_cents.is_not(None),
            )
            .group_by(BotDailyPnL.date)
            .order_by(BotDailyPnL.date.asc())
        ).all()
        equity_curve = [
            {"date": str(row.date), "value_cents": int(row.total)}
            for row in curve_rows
        ]

    # ── 8. Sharpe 30d ─────────────────────────────────────────────────────────
    sharpe_30d: float = 0.0
    if len(equity_curve) >= 2:
        # Use only the last 30 days of the curve
        curve_30 = [e for e in equity_curve if e["date"] >= str(thirty_days_ago)]
        values = [e["value_cents"] for e in curve_30]
        if len(values) >= 2:
            daily_returns = [
                (values[i] - values[i - 1]) / values[i - 1]
                for i in range(1, len(values))
                if values[i - 1] != 0
            ]
            if len(daily_returns) >= 2:
                try:
                    mean_r = statistics.mean(daily_returns)
                    std_r = statistics.stdev(daily_returns)
                    sharpe_30d = round(mean_r / std_r * (252 ** 0.5), 2) if std_r != 0 else 0.0
                except (ZeroDivisionError, statistics.StatisticsError):
                    sharpe_30d = 0.0

    # ── 9. Open positions count ───────────────────────────────────────────────
    total_open_positions: int = 0
    if alloc_ids:
        pos_count = db.execute(
            select(func.count(BotPosition.id)).where(
                BotPosition.allocation_id.in_(alloc_ids),
                BotPosition.closed_at.is_(None),
            )
        ).scalar()
        total_open_positions = int(pos_count or 0)

    # ── 10. Watchlist count ───────────────────────────────────────────────────
    profile_ids = list({a.profile_id for a in allocations})
    total_watchlist_count: int = 0
    if profile_ids:
        wl_count = db.execute(
            select(func.count(BotWatchlist.id)).where(
                BotWatchlist.profile_id.in_(profile_ids),
                BotWatchlist.status.in_(["active", "inactive"]),
            )
        ).scalar()
        total_watchlist_count = int(wl_count or 0)

    # ── 11. Leaderboard (one entry per allocation) ────────────────────────────
    leaderboard: List[Dict[str, Any]] = []

    # Build a map of profile_id → profile name
    profile_name_map: Dict[int, str] = {}
    if profile_ids:
        profiles = db.execute(
            select(BotProfile).where(BotProfile.id.in_(profile_ids))
        ).scalars().all()
        profile_name_map = {p.id: p.name for p in profiles}

    for alloc in allocations:
        current_val = allocation_values[alloc.id]
        val_30d = _value_on_date(alloc, thirty_days_ago)
        try:
            r30 = round((current_val - val_30d) / val_30d * 100, 2) if val_30d else 0.0
        except ZeroDivisionError:
            r30 = 0.0

        # Today's PnL for this allocation
        alloc_today_rows = [r for r in today_pnl_rows if r.allocation_id == alloc.id]
        alloc_today_pnl = sum(
            (r.realized_cents or 0) + (r.unrealized_cents or 0) - (r.fees_cents or 0)
            for r in alloc_today_rows
        )

        # Watchlist count for this allocation's profile
        alloc_wl_count: int = 0
        if alloc.profile_id:
            wl_single = db.execute(
                select(func.count(BotWatchlist.id)).where(
                    BotWatchlist.profile_id == alloc.profile_id,
                    BotWatchlist.status.in_(["active", "inactive"]),
                )
            ).scalar()
            alloc_wl_count = int(wl_single or 0)

        profile_key = profile_name_map.get(alloc.profile_id, "")
        display_name = PROFILE_NAMES.get(profile_key, profile_key)

        leaderboard.append({
            "rank": 0,  # assigned after sort
            "profile": profile_key,
            "name": display_name,
            "return_30d_pct": r30,
            "today_pnl_cents": alloc_today_pnl,
            "watchlist_count": alloc_wl_count,
            "portfolio_value_cents": current_val,
        })

    leaderboard.sort(key=lambda x: x["return_30d_pct"], reverse=True)
    for i, entry in enumerate(leaderboard, start=1):
        entry["rank"] = i

    # ── 12. Best / worst performer ────────────────────────────────────────────
    best_performer: Optional[Dict[str, Any]] = None
    worst_performer: Optional[Dict[str, Any]] = None
    if leaderboard:
        best = leaderboard[0]
        worst = leaderboard[-1]
        best_performer = {"profile": best["profile"], "return_30d_pct": best["return_30d_pct"]}
        worst_performer = {"profile": worst["profile"], "return_30d_pct": worst["return_30d_pct"]}

    return {
        "total_value_cents": total_value_cents,
        "yesterday_value_cents": yesterday_value_cents,
        "today_pnl_cents": today_pnl_cents,
        "today_pnl_pct": today_pnl_pct,
        "return_30d_pct": return_30d_pct,
        "return_30d_value_cents": return_30d_value_cents,
        "return_all_time_pct": return_all_time_pct,
        "sharpe_30d": sharpe_30d,
        "total_open_positions": total_open_positions,
        "total_watchlist_count": total_watchlist_count,
        "equity_curve": equity_curve,
        "leaderboard": leaderboard,
        "best_performer": best_performer,
        "worst_performer": worst_performer,
    }
