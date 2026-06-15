"""Per-bot strategy leaderboard — all-time and windowed P&L ranked.

All-time P&L aggregates from BotDailyPnL rows.
Windowed P&L (24h/7d/30d/mtd) is computed from BotTrade realized fills
because BotDailyPnL is an audit log, not a real-time source.
"""
from __future__ import annotations

from datetime import datetime, date, timezone, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from sqlalchemy import func

from app.dependencies import get_db, get_current_user
from app.db.models.bots import BotAllocation, BotProfile, BotDailyPnL, BotTrade, BotPosition
from app.db.models.allocation import BotPerformanceStats
from app.db.models.users import User

router = APIRouter(prefix="/api/leaderboard", tags=["leaderboard"])

_DISPLAY_NAMES: dict[str, str] = {
    "stock_swing":                 "Stock Swing",
    "stock_day":                   "Stock Day",
    "stock_lt":                    "Stock Long-Term",
    "crypto_swing":                "Crypto Swing",
    "crypto_day":                  "Crypto Day",
    "crypto_lt":                   "Crypto Long-Term",
    "crypto_onchain":              "Crypto On-Chain",
    "crypto_quant_aggressive":     "Quant Aggressive",
    "crypto_quant_mean_reversion": "Quant Mean Rev",
    "crypto_quant_scalper":        "Quant Scalper",
    "options_income":              "Equity Income",
    "options_directional":         "Equity Directional",
    "crypto_meanrev_2163":         "Mean Rev 2163",
}

_SORT_FIELDS = {
    "pnl":      "all_time_pnl_pct",
    "sharpe":   "sharpe_30d",
    "drawdown": "max_drawdown_pct",
    "win_rate": "win_rate",
}


def _window_cutoff(window: str) -> datetime | None:
    now = datetime.now(timezone.utc)
    if window == "24h":
        return now - timedelta(hours=24)
    if window == "7d":
        return now - timedelta(days=7)
    if window == "30d":
        return now - timedelta(days=30)
    if window == "mtd":
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return None  # "all" — no cutoff


def _compute_window_pnl(db: Session, alloc_ids: list[int], cutoff: datetime) -> dict[int, dict]:
    """
    Compute per-allocation realized P&L within a time window from BotTrade.
    Returns {alloc_id: {window_pnl_cents: int, window_trades: int}}.
    """
    if not alloc_ids or cutoff is None:
        return {}

    all_pos = db.query(BotPosition).filter(
        BotPosition.allocation_id.in_(alloc_ids)
    ).all()
    pos_cost_map: dict[int, float] = {p.id: p.avg_cost_cents for p in all_pos}

    # Fallback avg_cost by (alloc_id, symbol) from pre-window buys
    buy_price: dict[tuple, float] = {}
    older_trades = db.query(BotTrade).filter(
        BotTrade.allocation_id.in_(alloc_ids),
        BotTrade.ts < cutoff,
        BotTrade.side.in_(["buy", "open", "short"]),
    ).all()
    for t in older_trades:
        buy_price[(t.allocation_id, t.symbol)] = t.fill_price_cents

    window_trades = db.query(BotTrade).filter(
        BotTrade.allocation_id.in_(alloc_ids),
        BotTrade.ts >= cutoff,
        BotTrade.quarantined_at.is_(None),
    ).all()

    result: dict[int, dict] = {aid: {"window_pnl_cents": 0, "window_trades": 0} for aid in alloc_ids}
    for t in window_trades:
        side = t.side.lower()
        if side in ("buy", "open", "short"):
            buy_price[(t.allocation_id, t.symbol)] = t.fill_price_cents
            continue
        if side not in ("sell", "close", "cover"):
            continue
        avg_cost = pos_cost_map.get(t.position_id) if t.position_id else None
        if avg_cost is None:
            avg_cost = buy_price.get((t.allocation_id, t.symbol), t.fill_price_cents)
        if side == "cover":
            pnl = int((avg_cost - t.fill_price_cents) * t.qty) - int(t.fees_cents or 0)
        else:
            pnl = int((t.fill_price_cents - avg_cost) * t.qty) - int(t.fees_cents or 0)
        aid = t.allocation_id
        if aid in result:
            result[aid]["window_pnl_cents"] += pnl
            result[aid]["window_trades"] += 1

    return result


@router.get("/strategies")
def get_strategy_leaderboard(
    sort: str = Query("pnl", regex="^(pnl|sharpe|drawdown|win_rate)$"),
    window: str = Query("all", regex="^(24h|7d|30d|mtd|all)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Per-bot leaderboard ranked by all-time P&L %. Accepts window=24h|7d|30d|mtd|all."""
    allocs = (
        db.query(BotAllocation)
        .join(BotProfile, BotProfile.id == BotAllocation.profile_id)
        .filter(
            BotAllocation.user_id == current_user.id,
        )
        .all()
    )
    if not allocs:
        return {"strategies": [], "total": 0}

    alloc_ids = [a.id for a in allocs]
    profile_ids = list({a.profile_id for a in allocs})
    profiles = db.query(BotProfile).filter(BotProfile.id.in_(profile_ids)).all()
    profile_map = {p.id: p for p in profiles}

    # ── Aggregate realized P&L from BotDailyPnL (single batch query) ────────
    today = date.today()
    pnl_rows = (
        db.query(BotDailyPnL)
        .filter(BotDailyPnL.allocation_id.in_(alloc_ids))
        .all()
    )
    realized_by_alloc: dict[int, int] = {}
    unrealized_today_by_alloc: dict[int, int] = {}
    for row in pnl_rows:
        aid = row.allocation_id
        realized_by_alloc[aid] = realized_by_alloc.get(aid, 0) + row.realized_cents
        if row.date == today:
            unrealized_today_by_alloc[aid] = (
                unrealized_today_by_alloc.get(aid, 0) + row.unrealized_cents
            )

    # ── Trade counts from bot_trades (nightly rollup may not have run yet) ──
    trade_count_rows = (
        db.query(BotTrade.allocation_id, func.count(BotTrade.id).label("cnt"))
        .filter(BotTrade.allocation_id.in_(alloc_ids))
        .group_by(BotTrade.allocation_id)
        .all()
    )
    trade_counts: dict[int, int] = {row.allocation_id: row.cnt for row in trade_count_rows}

    # ── Performance stats (Sharpe, win rate — from nightly rollup) ──────────
    stats_rows = (
        db.query(BotPerformanceStats)
        .filter(BotPerformanceStats.allocation_id.in_(alloc_ids))
        .all()
    )
    latest_stats: dict[int, BotPerformanceStats] = {}
    for s in stats_rows:
        existing = latest_stats.get(s.allocation_id)
        if existing is None or s.stat_date > existing.stat_date:
            latest_stats[s.allocation_id] = s

    # ── Windowed P&L (24h/7d/30d/mtd) from BotTrade ─────────────────────────
    cutoff = _window_cutoff(window)
    window_pnl_map = _compute_window_pnl(db, alloc_ids, cutoff) if cutoff else {}

    now = datetime.now(timezone.utc)
    rows = []

    for alloc in allocs:
        profile = profile_map.get(alloc.profile_id)
        bot_name = profile.name if profile else f"alloc_{alloc.id}"
        display = _DISPLAY_NAMES.get(bot_name, bot_name.replace("_", " ").title())

        starting = alloc.starting_capital_cents or 0
        realized = realized_by_alloc.get(alloc.id, 0)
        unrealized_today = unrealized_today_by_alloc.get(alloc.id, 0)

        current_value = starting + realized + unrealized_today
        current_equity_usd = round(current_value / 100, 2)
        all_time_pnl_usd = round((current_value - starting) / 100, 2)
        all_time_pnl_pct = (
            round((current_value - starting) / starting * 100, 2) if starting else 0.0
        )

        stats = latest_stats.get(alloc.id)
        sharpe_30d: float | None = stats.sharpe_ratio if stats else None
        win_rate: float | None = stats.win_rate if stats else None
        max_drawdown_pct: float | None = stats.max_drawdown_pct if stats else None
        total_trades: int = trade_counts.get(alloc.id, 0)

        created = alloc.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        days_live = max(1, (now - created).days)

        wp = window_pnl_map.get(alloc.id, {})
        window_pnl_cents = wp.get("window_pnl_cents", 0)
        window_pnl_usd   = round(window_pnl_cents / 100, 2)
        window_pnl_pct   = round(window_pnl_cents / starting * 100, 2) if starting else 0.0
        window_trades    = wp.get("window_trades", 0)

        rows.append({
            "bot_id": bot_name,
            "strategy_name": display,
            "allocation_id": alloc.id,
            "tier": alloc.tier or "T0",
            "enabled": alloc.enabled,
            "paused_reason": alloc.paused_reason,
            "is_admin_locked": alloc.paused_reason in ("admin_lock", "health_halt"),
            "starting_capital": round(starting / 100, 2),
            "current_equity": current_equity_usd,
            "all_time_pnl_usd": all_time_pnl_usd,
            "all_time_pnl_pct": all_time_pnl_pct,
            "sharpe_30d": round(sharpe_30d, 3) if sharpe_30d is not None else None,
            "max_drawdown_pct": round(max_drawdown_pct, 4) if max_drawdown_pct is not None else None,
            "win_rate": round(win_rate, 3) if win_rate is not None else None,
            "trades_count": total_trades,
            "days_live": days_live,
            "window_pnl_usd": window_pnl_usd,
            "window_pnl_pct": window_pnl_pct,
            "window_trades":  window_trades,
        })

    sort_key = _SORT_FIELDS.get(sort, "all_time_pnl_pct")
    # When viewing a specific window, sort by window P&L instead
    if window != "all" and sort == "pnl":
        rows.sort(key=lambda r: -(r["window_pnl_usd"] or 0))
    elif sort_key == "max_drawdown_pct":
        rows.sort(key=lambda r: (r[sort_key] is None, r[sort_key] or 0))
    else:
        rows.sort(key=lambda r: (r[sort_key] is None, -(r[sort_key] or 0)))

    for i, row in enumerate(rows, 1):
        row["rank"] = i

    return {"strategies": rows, "total": len(rows), "sort": sort, "window": window}
