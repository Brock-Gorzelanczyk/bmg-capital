"""
/api/portfolio — bot-aggregate portfolio view.

All endpoints read from the same canonical source as /api/strategy-lab/portfolio:
BotAllocation + BotDailyPnL + BotPosition tables.

Legacy personal-portfolio and paper-account tables were archived 2026-06-06.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
from app.db.models.users import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])

_ASSET_CLASS_COLOR: dict[str, str] = {
    "stock":   "#22C55E",
    "crypto":  "#FF8B00",
    "options": "#F59E0B",
    "quant":   "#8B5CF6",
}

def _bot_display(name: str) -> str:
    return name.replace("_", " ").title()

def _bot_color(asset_class: str) -> str:
    return _ASSET_CLASS_COLOR.get(asset_class, "#94A3B8")


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


@router.get("/open-positions")
def get_open_positions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """All open positions across every bot the user has allocated, enriched with live prices."""
    from app.db.models.bots import BotAllocation, BotProfile, BotPosition, BotTrade

    allocations = (
        db.query(BotAllocation)
        .filter(BotAllocation.user_id == current_user.id)
        .all()
    )
    if not allocations:
        return _empty_response()

    alloc_by_id   = {a.id: a for a in allocations}
    profile_ids   = list({a.profile_id for a in allocations})
    profiles      = db.query(BotProfile).filter(BotProfile.id.in_(profile_ids)).all()
    profile_by_id = {p.id: p for p in profiles}

    open_positions = (
        db.query(BotPosition)
        .filter(
            BotPosition.allocation_id.in_(list(alloc_by_id.keys())),
            BotPosition.closed_at.is_(None),
        )
        .order_by(BotPosition.opened_at.desc())
        .limit(50)
        .all()
    )

    if not open_positions:
        return _empty_response()

    # Batch-fetch live prices for all unique symbols
    all_symbols = list({pos.symbol for pos in open_positions})
    price_map: dict[str, float] = {}
    try:
        from app.services.live_prices import fetch_live_prices
        price_map = fetch_live_prices(all_symbols)
    except Exception as exc:
        logger.warning("open-positions: live price fetch failed: %s", exc)

    # Load trade ids keyed by position_id (for click-through links)
    position_ids = [pos.id for pos in open_positions]
    trades = (
        db.query(BotTrade)
        .filter(BotTrade.position_id.in_(position_ids))
        .all()
    )
    trade_id_by_pos: dict[int, int] = {t.position_id: t.id for t in trades if t.position_id}

    now_utc = datetime.now(timezone.utc)
    result: list[dict] = []
    total_unrealized_usd = 0.0
    distinct_bots: set[str] = set()

    for pos in open_positions:
        alloc   = alloc_by_id.get(pos.allocation_id)
        if not alloc:
            continue
        profile = profile_by_id.get(alloc.profile_id)
        if not profile:
            continue

        entry_price   = pos.avg_cost_cents / 100.0
        current_price = float(price_map.get(pos.symbol) or 0)
        if current_price <= 0:
            current_price = entry_price   # show flat when price unavailable

        unrealized_usd = round((current_price - entry_price) * pos.qty, 2)
        cost_basis     = entry_price * pos.qty
        unrealized_pct = round((unrealized_usd / cost_basis * 100) if cost_basis > 0 else 0.0, 4)

        opened_at = pos.opened_at
        if opened_at.tzinfo is None:
            opened_at = opened_at.replace(tzinfo=timezone.utc)
        held_seconds = int((now_utc - opened_at).total_seconds())

        distinct_bots.add(profile.name)
        total_unrealized_usd += unrealized_usd

        result.append({
            "position_id":       pos.id,
            "trade_id":          trade_id_by_pos.get(pos.id, pos.id),
            "bot_name":          profile.name,
            "bot_display":       _bot_display(profile.name),
            "bot_color":         _bot_color(profile.asset_class),
            "asset_class":       profile.asset_class,
            "symbol":            pos.symbol,
            "side":              "buy",
            "qty":               pos.qty,
            "entry_price":       entry_price,
            "current_price":     current_price,
            "unrealized_pnl_usd": unrealized_usd,
            "unrealized_pnl_pct": unrealized_pct,
            "opened_at":         pos.opened_at.isoformat(),
            "held_seconds":      max(0, held_seconds),
        })

    total_cost = sum(
        (pos.avg_cost_cents / 100.0) * pos.qty for pos in open_positions
    )
    total_unrealized_pct = round(
        (total_unrealized_usd / total_cost * 100) if total_cost > 0 else 0.0, 4
    )

    return {
        "positions":            result,
        "total_unrealized_usd": round(total_unrealized_usd, 2),
        "total_unrealized_pct": total_unrealized_pct,
        "position_count":       len(result),
        "distinct_bots":        len(distinct_bots),
        "fetched_at":           now_utc.isoformat(),
    }


def _empty_response() -> dict:
    return {
        "positions":            [],
        "total_unrealized_usd": 0.0,
        "total_unrealized_pct": 0.0,
        "position_count":       0,
        "distinct_bots":        0,
        "fetched_at":           datetime.now(timezone.utc).isoformat(),
    }
