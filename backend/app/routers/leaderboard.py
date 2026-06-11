"""Per-bot strategy leaderboard — all-time P&L ranked."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
from app.db.models.bots import BotAllocation, BotProfile
from app.db.models.allocation import BotPerformanceStats
from app.db.models.users import User

router = APIRouter(prefix="/api/leaderboard", tags=["leaderboard"])

_DISPLAY_NAMES: dict[str, str] = {
    "stock_swing":              "Stock Swing",
    "stock_day":                "Stock Day",
    "stock_lt":                 "Stock Long-Term",
    "crypto_swing":             "Crypto Swing",
    "crypto_day":               "Crypto Day",
    "crypto_lt":                "Crypto Long-Term",
    "crypto_onchain":           "Crypto On-Chain",
    "crypto_quant_aggressive":  "Quant Aggressive",
    "options_income":           "Options Income",
    "options_directional":      "Options Directional",
}

_SORT_FIELDS = {
    "pnl":       "all_time_pnl_pct",
    "sharpe":    "sharpe_30d",
    "drawdown":  "max_drawdown_pct",
    "win_rate":  "win_rate",
}


def _latest_stats(db: Session, allocation_id: int) -> BotPerformanceStats | None:
    return (
        db.query(BotPerformanceStats)
        .filter(BotPerformanceStats.allocation_id == allocation_id)
        .order_by(BotPerformanceStats.stat_date.desc())
        .first()
    )


@router.get("/strategies")
def get_strategy_leaderboard(
    sort: str = Query("pnl", regex="^(pnl|sharpe|drawdown|win_rate)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Per-bot leaderboard ranked by all-time P&L %."""
    allocs = (
        db.query(BotAllocation)
        .filter(BotAllocation.user_id == current_user.id)
        .all()
    )
    if not allocs:
        return {"strategies": [], "total": 0}

    profile_ids = list({a.profile_id for a in allocs})
    profiles = db.query(BotProfile).filter(BotProfile.id.in_(profile_ids)).all()
    profile_map = {p.id: p for p in profiles}

    now = datetime.now(timezone.utc)
    rows = []

    for alloc in allocs:
        profile = profile_map.get(alloc.profile_id)
        bot_name = profile.name if profile else f"alloc_{alloc.id}"
        display = _DISPLAY_NAMES.get(bot_name, bot_name.replace("_", " ").title())

        # Snapshot via canonical service
        all_time_pnl_pct: float = 0.0
        all_time_pnl_usd: float = 0.0
        current_equity_usd: float = 0.0
        try:
            from app.core.canonical import compute_bot_snapshot
            snap = compute_bot_snapshot(alloc, profile, db)
            starting = alloc.starting_capital_cents or 0
            current_equity_usd = round(snap.portfolio_value_cents / 100, 2)
            all_time_pnl_usd = round((snap.portfolio_value_cents - starting) / 100, 2)
            all_time_pnl_pct = snap.all_time_return_pct or 0.0
        except Exception:
            starting = alloc.starting_capital_cents or 0
            current_equity_usd = round(starting / 100, 2)

        # Performance stats (from nightly rollup)
        stats = _latest_stats(db, alloc.id)
        sharpe_30d: float | None = stats.sharpe_ratio if stats else None
        win_rate: float | None = stats.win_rate if stats else None
        max_drawdown_pct: float | None = stats.max_drawdown_pct if stats else None
        total_trades: int = stats.total_trades if stats else 0

        # Days live since allocation created
        created = alloc.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        days_live = max(1, (now - created).days)

        rows.append({
            "bot_id": bot_name,
            "strategy_name": display,
            "allocation_id": alloc.id,
            "tier": alloc.tier or "T0",
            "enabled": alloc.enabled,
            "starting_capital": round((alloc.starting_capital_cents or 0) / 100, 2),
            "current_equity": current_equity_usd,
            "all_time_pnl_usd": all_time_pnl_usd,
            "all_time_pnl_pct": all_time_pnl_pct,
            "sharpe_30d": round(sharpe_30d, 3) if sharpe_30d is not None else None,
            "max_drawdown_pct": round(max_drawdown_pct, 4) if max_drawdown_pct is not None else None,
            "win_rate": round(win_rate, 3) if win_rate is not None else None,
            "trades_count": total_trades,
            "days_live": days_live,
        })

    sort_key = _SORT_FIELDS.get(sort, "all_time_pnl_pct")
    if sort_key in ("max_drawdown_pct",):
        rows.sort(key=lambda r: (r[sort_key] is None, r[sort_key] or 0))
    else:
        rows.sort(key=lambda r: (r[sort_key] is None, -(r[sort_key] or 0)))

    for i, row in enumerate(rows, 1):
        row["rank"] = i

    return {"strategies": rows, "total": len(rows), "sort": sort}
