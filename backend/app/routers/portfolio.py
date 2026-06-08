"""
/api/portfolio — bot-aggregate portfolio view.

All endpoints read from the same canonical source as /api/strategy-lab/portfolio:
BotAllocation + BotDailyPnL + BotPosition tables.

Legacy personal-portfolio and paper-account tables were archived 2026-06-06.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
from app.db.models.users import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])

# Module-level 5s TTL price cache so repeated calls within one 30s poll cycle
# don't hammer Kraken with identical requests.
_price_cache: dict[str, tuple[float, float, str]] = {}  # sym → (price, fetched_ts, source)
_PRICE_TTL = 5.0  # seconds


def _fetch_prices(symbols: list[str]) -> dict[str, tuple[float, str]]:
    """Return {symbol: (price, source)} using a 5-second TTL module cache."""
    now = time.time()
    fresh: dict[str, tuple[float, float, str]] = {
        sym: entry for sym, entry in _price_cache.items()
        if now - entry[1] < _PRICE_TTL
    }
    stale = [sym for sym in symbols if sym not in fresh]

    if stale:
        try:
            from app.services.live_prices import fetch_live_prices
            live_map = fetch_live_prices(stale)
            for sym in stale:
                price = float(live_map.get(sym) or 0)
                source = ("kraken" if "/" in sym else "alpaca") if price > 0 else "unavailable"
                _price_cache[sym] = (price, now, source)
                fresh[sym] = (price, now, source)
            logger.debug("open-positions: fetched live prices for %d symbols", len(stale))
        except Exception as exc:
            logger.warning("open-positions: live_prices failed: %s", exc)
            for sym in stale:
                _price_cache[sym] = (0.0, now, "unavailable")
                fresh[sym] = (0.0, now, "unavailable")

    return {sym: (fresh[sym][0], fresh[sym][2]) if sym in fresh else (0.0, "unavailable")
            for sym in symbols}

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
            BotPosition.quarantined_at.is_(None),
        )
        .order_by(BotPosition.opened_at.desc())
        .limit(50)
        .all()
    )

    if not open_positions:
        return _empty_response()

    # Batch-fetch live prices with 5s TTL cache
    all_symbols = list({pos.symbol for pos in open_positions})
    price_result = _fetch_prices(all_symbols)   # {sym: (price, source)}
    price_fetched_at_iso = datetime.now(timezone.utc).isoformat()

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

        entry_price          = pos.avg_cost_cents / 100.0
        live_price, source   = price_result.get(pos.symbol, (0.0, "unavailable"))
        live_price           = float(live_price or 0)

        if live_price > 0:
            current_price  = live_price
            price_source   = source
        else:
            # Fall back to entry price; flag as stale so the UI can show a warning
            current_price  = entry_price
            price_source   = "stale"

        current_value_usd = round(current_price * pos.qty, 2)
        unrealized_usd    = round((current_price - entry_price) * pos.qty, 2)
        cost_basis        = entry_price * pos.qty
        unrealized_pct    = round((unrealized_usd / cost_basis * 100) if cost_basis > 0 else 0.0, 4)

        opened_at = pos.opened_at
        if opened_at.tzinfo is None:
            opened_at = opened_at.replace(tzinfo=timezone.utc)
        held_seconds = int((now_utc - opened_at).total_seconds())

        distinct_bots.add(profile.name)
        total_unrealized_usd += unrealized_usd

        result.append({
            "position_id":        pos.id,
            "trade_id":           trade_id_by_pos.get(pos.id, pos.id),
            "bot_name":           profile.name,
            "bot_display":        _bot_display(profile.name),
            "bot_color":          _bot_color(profile.asset_class),
            "asset_class":        profile.asset_class,
            "symbol":             pos.symbol,
            "side":               "buy",
            "qty":                pos.qty,
            "entry_price":        entry_price,
            "current_price":      current_price,
            "current_value_usd":  current_value_usd,
            "unrealized_pnl_usd": unrealized_usd,
            "unrealized_pnl_pct": unrealized_pct,
            "price_source":       price_source,
            "price_fetched_at":   price_fetched_at_iso,
            "opened_at":          pos.opened_at.isoformat(),
            "held_seconds":       max(0, held_seconds),
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
