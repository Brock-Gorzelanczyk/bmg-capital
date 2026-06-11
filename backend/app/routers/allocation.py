"""Allocation tier API — performance stats and promotion candidates."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
from app.db.models.bots import BotAllocation, BotProfile
from app.db.models.allocation import BotPerformanceStats, BotTierHistory
from app.db.models.users import User
from app.services.allocation_rules import TIERS, PROMOTION_RULES, evaluate_bot, BotMetrics

router = APIRouter(prefix="/api/bots", tags=["allocation"])

_DISPLAY_NAMES: dict[str, str] = {
    "stock_swing": "Stock Swing",
    "stock_day": "Stock Day",
    "stock_lt": "Stock Long-Term",
    "crypto_swing": "Crypto Swing",
    "crypto_day": "Crypto Day",
    "crypto_lt": "Crypto Long-Term",
    "crypto_onchain": "Crypto On-Chain",
    "crypto_quant_aggressive": "Quant Aggressive",
    "options_flow": "Options Flow",
    "stock_momentum": "Stock Momentum",
    "stock_breakout": "Stock Breakout",
    "stock_mean_reversion": "Stock Mean Rev",
}


def _latest_stats(db: Session, allocation_id: int) -> BotPerformanceStats | None:
    return (
        db.query(BotPerformanceStats)
        .filter(BotPerformanceStats.allocation_id == allocation_id)
        .order_by(BotPerformanceStats.stat_date.desc())
        .first()
    )


@router.get("/allocation")
def get_allocation_overview(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Return all allocations with their current tier and latest stats."""
    allocs = (
        db.query(BotAllocation)
        .filter(BotAllocation.user_id == current_user.id)
        .all()
    )
    profile_ids = list({a.profile_id for a in allocs})
    profiles = (
        db.query(BotProfile).filter(BotProfile.id.in_(profile_ids)).all()
        if profile_ids else []
    )
    profile_map = {p.id: p for p in profiles}

    rows = []
    for alloc in allocs:
        profile = profile_map.get(alloc.profile_id)
        stats = _latest_stats(db, alloc.id)
        tier = alloc.tier or "T0"
        tier_info = TIERS.get(tier, TIERS["T0"])
        starting = alloc.starting_capital_cents or 0
        current_val = stats.current_value_cents if stats else starting
        pnl_usd = round((current_val - starting) / 100, 2) if starting else 0.0
        all_time_pct = round((current_val - starting) / starting * 100, 2) if starting else 0.0
        rows.append({
            "allocation_id": alloc.id,
            "bot_name": profile.name if profile else "",
            "display_name": _DISPLAY_NAMES.get(
                profile.name, profile.name.replace("_", " ").title() if profile else ""
            ),
            "enabled": alloc.enabled,
            "tier": tier,
            "tier_label": tier_info["label"],
            "tier_color": tier_info["color"],
            "max_capital_pct": tier_info["max_capital_pct"],
            "starting_capital_usd": round(starting / 100, 2),
            "current_equity_usd": round(current_val / 100, 2),
            "all_time_pnl_usd": pnl_usd,
            "all_time_pnl_pct": all_time_pct,
            "stats": {
                "return_30d_pct": stats.return_30d_pct if stats else None,
                "win_rate": stats.win_rate if stats else None,
                "profit_factor": stats.profit_factor if stats else None,
                "max_drawdown_pct": stats.max_drawdown_pct if stats else None,
                "sharpe_ratio": stats.sharpe_ratio if stats else None,
                "total_trades": stats.total_trades if stats else 0,
                "stat_date": stats.stat_date.isoformat() if stats and stats.stat_date else None,
            },
        })

    rows.sort(key=lambda r: r["tier"], reverse=True)
    return {"allocations": rows, "total": len(rows)}


@router.get("/{bot_id}/performance")
def get_bot_performance(
    bot_id: int,
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Return time-series performance stats for a specific allocation."""
    alloc = (
        db.query(BotAllocation)
        .filter(
            BotAllocation.id == bot_id,
            BotAllocation.user_id == current_user.id,
        )
        .first()
    )
    if not alloc:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Allocation not found")

    cutoff = date.today() - timedelta(days=days)
    stats_rows = (
        db.query(BotPerformanceStats)
        .filter(
            BotPerformanceStats.allocation_id == bot_id,
            BotPerformanceStats.stat_date >= cutoff,
        )
        .order_by(BotPerformanceStats.stat_date)
        .all()
    )

    tier_history = (
        db.query(BotTierHistory)
        .filter(BotTierHistory.allocation_id == bot_id)
        .order_by(BotTierHistory.changed_at.desc())
        .limit(20)
        .all()
    )

    current_tier = alloc.tier or "T0"

    return {
        "allocation_id": bot_id,
        "current_tier": current_tier,
        "tier_label": TIERS.get(current_tier, TIERS["T0"])["label"],
        "time_series": [
            {
                "date": s.stat_date.isoformat(),
                "return_30d_pct": s.return_30d_pct,
                "win_rate": s.win_rate,
                "profit_factor": s.profit_factor,
                "max_drawdown_pct": s.max_drawdown_pct,
                "sharpe_ratio": s.sharpe_ratio,
                "total_trades": s.total_trades,
                "current_value_cents": s.current_value_cents,
            }
            for s in stats_rows
        ],
        "tier_history": [
            {
                "changed_at": h.changed_at.isoformat() if h.changed_at else None,
                "previous_tier": h.previous_tier,
                "new_tier": h.new_tier,
                "reason": h.reason,
                "triggered_by": h.triggered_by,
                "return_30d_pct_at_change": h.return_30d_pct_at_change,
                "win_rate_at_change": h.win_rate_at_change,
            }
            for h in tier_history
        ],
    }


@router.get("/promotion-candidates")
def get_promotion_candidates(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Return bots that are close to a tier promotion."""
    allocs = (
        db.query(BotAllocation)
        .filter(
            BotAllocation.user_id == current_user.id,
            BotAllocation.enabled.is_(True),
        )
        .all()
    )
    profile_ids = list({a.profile_id for a in allocs})
    profiles = (
        db.query(BotProfile).filter(BotProfile.id.in_(profile_ids)).all()
        if profile_ids else []
    )
    profile_map = {p.id: p for p in profiles}

    candidates = []
    for alloc in allocs:
        stats = _latest_stats(db, alloc.id)
        if not stats:
            continue
        tier = alloc.tier or "T0"
        metrics = BotMetrics(
            allocation_id=alloc.id,
            current_tier=tier,
            total_trades=stats.total_trades or 0,
            win_rate=stats.win_rate or 0.0,
            return_30d_pct=stats.return_30d_pct or 0.0,
            profit_factor=stats.profit_factor or 1.0,
            max_drawdown_pct=stats.max_drawdown_pct or 0.0,
            sharpe_ratio=stats.sharpe_ratio or 0.0,
        )
        new_tier, reason = evaluate_bot(metrics)

        # Check how close to promotion
        promo_key = f"{tier}_to_T{int(tier[1]) + 1}"
        promo_rule = PROMOTION_RULES.get(promo_key)

        profile = profile_map.get(alloc.profile_id)
        candidates.append({
            "allocation_id": alloc.id,
            "display_name": _DISPLAY_NAMES.get(
                profile.name if profile else "",
                profile.name.replace("_", " ").title() if profile else "",
            ),
            "current_tier": tier,
            "recommended_tier": new_tier,
            "change_reason": reason,
            "next_tier_requirements": promo_rule,
            "current_metrics": {
                "return_30d_pct": stats.return_30d_pct,
                "win_rate": stats.win_rate,
                "profit_factor": stats.profit_factor,
                "max_drawdown_pct": stats.max_drawdown_pct,
                "total_trades": stats.total_trades,
            },
        })

    candidates.sort(key=lambda c: c["current_tier"], reverse=True)
    return {"candidates": candidates, "total": len(candidates)}
