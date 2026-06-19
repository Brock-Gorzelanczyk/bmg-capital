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
from sqlalchemy import text
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


_SLEEVE_COLORS = {
    "stocks":  "#10B981",
    "crypto":  "#9333EA",
    "options": "#F97316",
    "quant":   "#6366F1",
    "cash":    "#94A3B8",
}

_SLEEVE_LABELS = {
    "stocks":  "Stocks",
    "crypto":  "Crypto",
    "options": "Options",
    "quant":   "Quant",
    "cash":    "Cash",
}

_PROFILE_TO_SLEEVE = {
    "stock_swing":                "stocks",
    "stock_day":                  "stocks",
    "stock_lt":                   "stocks",
    "crypto_swing":               "crypto",
    "crypto_day":                 "crypto",
    "crypto_lt":                  "crypto",
    "crypto_onchain":             "crypto",
    "crypto_quant_aggressive":    "quant",
    "crypto_quant_scalper":       "quant",
    "crypto_quant_mean_reversion":"quant",
    "crypto_meanrev_2163":        "quant",
    "options_income":             "options",
    "options_directional":        "options",
}


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


# ── /snapshot canonical endpoint ─────────────────────────────────────────────

_BOT_DISPLAY = {
    "stock_swing":                "Stock Swing",
    "stock_day":                  "Stock Day",
    "stock_lt":                   "Stock Long-Term",
    "crypto_swing":               "Crypto Swing",
    "crypto_day":                 "Crypto Day",
    "crypto_lt":                  "Crypto Long-Term",
    "crypto_onchain":             "Crypto Onchain",
    "crypto_quant_aggressive":    "Quant Aggressive",
    "crypto_quant_scalper":       "Quant Scalper",
    "crypto_quant_mean_reversion":"Quant Mean Reversion",
    "crypto_meanrev_2163":        "Mean Rev 2163",
    "options_income":             "Equity Income",
    "options_directional":        "Equity Directional",
}

_BOT_CATEGORY = {
    "stock_swing":                "stocks",
    "stock_day":                  "stocks",
    "stock_lt":                   "stocks",
    "crypto_swing":               "crypto",
    "crypto_day":                 "crypto",
    "crypto_lt":                  "crypto",
    "crypto_onchain":             "crypto",
    "crypto_quant_aggressive":    "quant",
    "crypto_quant_scalper":       "quant",
    "crypto_quant_mean_reversion":"quant",
    "crypto_meanrev_2163":        "quant",
    "options_income":             "stocks",
    "options_directional":        "stocks",
}

_BOT_DESCRIPTIONS = {
    "stock_swing":                "Russell 1000 momentum, 1–30 day holds",
    "stock_day":                  "Intraday gappers & earnings momentum, EOD flat",
    "stock_lt":                   "S&P 500 factor model, monthly rebalance",
    "crypto_swing":               "Top 20 crypto by mcap, 1–30 day holds",
    "crypto_day":                 "BTC/ETH/SOL intraday momentum, 8h force-close",
    "crypto_lt":                  "BTC/ETH + majors, weekly DCA & monthly rebalance",
    "crypto_onchain":             "On-chain flow — large wallet moves, DEX volume anomalies",
    "crypto_quant_aggressive":    "8-strategy quant stack, 5m bars, 20-coin universe",
    "crypto_quant_scalper":       "1m scalping, 5-strategy ensemble, liquid majors only",
    "crypto_quant_mean_reversion":"5m mean-reversion, 6-strategy fade stack, mid-cap alts",
    "crypto_meanrev_2163":        "Experimental mean-reversion variant, paper-only",
    "options_income":             "Equity income — quality stocks, dividend + growth focus",
    "options_directional":        "Equity directional — tactical momentum & mean-reversion",
}


def _compute_bot_status(alloc) -> str:
    if alloc is None:
        return "unknown"
    pr = alloc.paused_reason or ""
    if pr in ("admin_lock", "health_halt"):
        return "admin_locked"
    if not alloc.enabled:
        return "disabled"
    if pr:
        return "paused"
    return "active"


def _empty_sleeve() -> dict:
    return {
        "starting_capital_cents": 0,
        "current_value_cents":    0,
        "open_positions":         0,
        "today_pnl_cents":        0,
        "alltime_pnl_cents":      0,
        "alltime_return_pct":     0.0,
        "return_30d_pct":         0.0,
        "active_bots":            0,
        "total_bots":             0,
        "bot_ids":                [],
    }


@router.get("/snapshot")
def get_portfolio_snapshot(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Single canonical endpoint: total metrics + per-sleeve + all-bot rows."""
    try:
        from app.routers.bots import _ensure_portfolios_for_user
        try:
            _ensure_portfolios_for_user(db, current_user.id)
            db.commit()
        except Exception as init_exc:
            logger.warning("snapshot: portfolio init failed (non-fatal): %s", init_exc)
            db.rollback()

        from app.db.models.bots import StrategyPortfolio, BotAllocation, BotProfile
        from app.core.canonical import compute_portfolio_snapshot

        portfolios = (
            db.query(StrategyPortfolio)
            .filter(StrategyPortfolio.user_id == current_user.id)
            .order_by(StrategyPortfolio.id)
            .all()
        )

        all_allocs = (
            db.query(BotAllocation)
            .filter(BotAllocation.user_id == current_user.id)
            .all()
        )
        profile_ids = list({a.profile_id for a in all_allocs})
        profiles = db.query(BotProfile).filter(BotProfile.id.in_(profile_ids)).all()
        profile_map = {p.id: p for p in profiles}

        # Build per-portfolio snapshots
        port_snaps = {}
        for port in portfolios:
            port_allocs = [a for a in all_allocs if a.portfolio_id == port.id]
            pairs = [(a, profile_map[a.profile_id]) for a in port_allocs if a.profile_id in profile_map]
            snap = compute_portfolio_snapshot(port, pairs, db)
            port_snaps[port.asset_class] = (port, snap)

        # Aggregate totals
        total_value = sum(s.portfolio_value_cents for _, s in port_snaps.values())
        total_starting = sum(s.starting_capital_cents for _, s in port_snaps.values())
        total_open_pos = sum(s.open_positions_count for _, s in port_snaps.values())
        total_today_pnl = sum(s.today_pnl_cents for _, s in port_snaps.values())
        total_alltime_pnl = total_value - total_starting

        return_alltime_pct = round(
            (total_value - total_starting) / total_starting * 100, 2
        ) if total_starting else 0.0

        return_30d_pct = 0.0
        if total_starting:
            return_30d_pct = round(
                sum(
                    s.return_30d_pct * s.starting_capital_cents
                    for _, s in port_snaps.values()
                    if s.starting_capital_cents
                ) / total_starting,
                2,
            )

        # Sleeve reservations
        try:
            _sleeve_reservations: dict[str, int] = {
                row[0]: int(row[1])
                for row in db.execute(
                    text("SELECT sleeve_name, reserved_capital_cents FROM sleeve_config")
                ).fetchall()
            }
        except Exception:
            _sleeve_reservations = {}

        sleeve_keys = ["stocks", "crypto", "options", "quant"]

        # Compute each sleeve's numerator (deployed + reserved) independently.
        # Use the SUM of numerators as the denominator — this guarantees
        # sum(sleeve_pct) == 100% by identity, even if StrategyPortfolio rows
        # double-count quant bots across the crypto and quant sleeves.
        sleeve_numerators: dict[str, int] = {}
        for k in sleeve_keys:
            deployed = port_snaps[k][1].portfolio_value_cents if k in port_snaps else 0
            reserved = _sleeve_reservations.get(k, 0)
            sleeve_numerators[k] = deployed + reserved

        total_aum = sum(sleeve_numerators.values())

        def sleeve_pct(key: str) -> float:
            if total_aum <= 0:
                return 0.0
            return round(sleeve_numerators[key] / total_aum * 100, 2)

        capital_allocation = {
            "stocks_pct":  sleeve_pct("stocks"),
            "crypto_pct":  sleeve_pct("crypto"),
            "options_pct": sleeve_pct("options"),
            "quant_pct":   sleeve_pct("quant"),
            "cash_pct":    0.0,
        }

        # Per-sleeve breakdown
        by_sleeve: dict = {}
        for key in sleeve_keys:
            if key not in port_snaps:
                empty = _empty_sleeve()
                empty["reserved_capital_cents"] = _sleeve_reservations.get(key, 0)
                by_sleeve[key] = empty
                continue
            _, snap = port_snaps[key]
            bot_ids_in_sleeve = [
                bot.profile_name for bot in snap.bots
            ]
            by_sleeve[key] = {
                "starting_capital_cents": snap.starting_capital_cents,
                "current_value_cents":    snap.portfolio_value_cents,
                "open_positions":         snap.open_positions_count,
                "today_pnl_cents":        snap.today_pnl_cents,
                "alltime_pnl_cents":      snap.portfolio_value_cents - snap.starting_capital_cents,
                "alltime_return_pct":     snap.all_time_return_pct,
                "return_30d_pct":         snap.return_30d_pct,
                "active_bots":            snap.bots_active,
                "total_bots":             snap.bots_total,
                "bot_ids":                bot_ids_in_sleeve,
                "reserved_capital_cents": _sleeve_reservations.get(key, 0),
            }

        # Alloc map for status lookups
        alloc_by_profile_name: dict = {}
        for alloc in all_allocs:
            prof = profile_map.get(alloc.profile_id)
            if prof:
                alloc_by_profile_name[prof.name] = alloc

        # Build flat bots list
        bots_out = []
        for key in sleeve_keys:
            if key not in port_snaps:
                continue
            _, snap = port_snaps[key]
            for bot_snap in snap.bots:
                profile_name = bot_snap.profile_name
                alloc = alloc_by_profile_name.get(profile_name)
                tier = getattr(alloc, "tier", None) if alloc else None
                status = _compute_bot_status(alloc)
                is_admin_locked = status == "admin_locked"
                category = _BOT_CATEGORY.get(profile_name, key)
                display_name = _BOT_DISPLAY.get(profile_name, profile_name.replace("_", " ").title())

                # allocation_pct_of_sleeve
                sleeve_val = port_snaps[key][1].portfolio_value_cents if key in port_snaps else 0
                alloc_pct = round(
                    bot_snap.portfolio_value_cents / sleeve_val * 100, 2
                ) if sleeve_val > 0 else 0.0

                bots_out.append({
                    "id":                     profile_name,
                    "display_name":           display_name,
                    "category":               category,
                    "tier":                   tier,
                    "status":                 status,
                    "enabled":                bot_snap.enabled,
                    "is_admin_locked":        is_admin_locked,
                    "open_positions":         bot_snap.open_positions_count,
                    "today_pnl_cents":        bot_snap.today_pnl_cents,
                    "alltime_pnl_cents":      bot_snap.portfolio_value_cents - bot_snap.starting_capital_cents,
                    "return_30d_pct":         bot_snap.return_30d_pct,
                    "return_alltime_pct":     bot_snap.all_time_return_pct,
                    "starting_capital_cents": bot_snap.starting_capital_cents,
                    "current_value_cents":    bot_snap.portfolio_value_cents,
                    "allocation_pct_of_sleeve": alloc_pct,
                    "description":            _BOT_DESCRIPTIONS.get(profile_name, ""),
                })

        return {
            "as_of":                      datetime.now(timezone.utc).isoformat(),
            "user_id":                    current_user.id,
            "total_value_cents":          total_value,
            "total_starting_capital_cents": total_starting,
            "total_open_positions":       total_open_pos,
            "total_pnl_today_cents":      total_today_pnl,
            "total_pnl_alltime_cents":    total_alltime_pnl,
            "return_30d_pct":             return_30d_pct,
            "return_alltime_pct":         return_alltime_pct,
            "capital_allocation":         capital_allocation,
            "by_sleeve":                  by_sleeve,
            "bots":                       bots_out,
        }

    except Exception as exc:
        logger.error("portfolio snapshot failed for user %s: %s", current_user.id, exc, exc_info=True)
        empty_sleeve = _empty_sleeve()
        return {
            "as_of":                      datetime.now(timezone.utc).isoformat(),
            "user_id":                    current_user.id,
            "total_value_cents":          0,
            "total_starting_capital_cents": 0,
            "total_open_positions":       0,
            "total_pnl_today_cents":      0,
            "total_pnl_alltime_cents":    0,
            "return_30d_pct":             0.0,
            "return_alltime_pct":         0.0,
            "capital_allocation":         {"stocks_pct": 0.0, "crypto_pct": 0.0, "options_pct": 0.0, "quant_pct": 0.0, "cash_pct": 100.0},
            "by_sleeve":                  {"stocks": empty_sleeve, "crypto": empty_sleeve, "options": empty_sleeve, "quant": empty_sleeve},
            "bots":                       [],
        }


@router.get("/allocation-live")
def get_allocation_live(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Live capital allocation by sleeve: deployed positions + cash residual.

    Response: {as_of, total_portfolio_value, deployed_value, cash_value, slices: [...]}
    Each slice: {key, label, dollars, pct, color, position_count}
    """
    from app.db.models.bots import BotAllocation, BotProfile, BotPosition

    allocations = (
        db.query(BotAllocation)
        .filter(BotAllocation.user_id == current_user.id)
        .all()
    )
    if not allocations:
        return {
            "as_of": datetime.now(timezone.utc).isoformat(),
            "total_portfolio_value": 0.0,
            "deployed_value": 0.0,
            "cash_value": 0.0,
            "slices": [],
        }

    alloc_by_id = {a.id: a for a in allocations}
    profile_ids = list({a.profile_id for a in allocations})
    profiles = db.query(BotProfile).filter(BotProfile.id.in_(profile_ids)).all()
    profile_by_id = {p.id: p for p in profiles}

    open_positions = (
        db.query(BotPosition)
        .filter(
            BotPosition.allocation_id.in_(list(alloc_by_id.keys())),
            BotPosition.closed_at.is_(None),
            BotPosition.quarantined_at.is_(None),
        )
        .all()
    )

    # Batch live prices for non-options positions
    non_opt_symbols: list[str] = []
    for pos in open_positions:
        alloc = alloc_by_id.get(pos.allocation_id)
        if not alloc:
            continue
        profile = profile_by_id.get(alloc.profile_id)
        if not profile:
            continue
        sleeve = _PROFILE_TO_SLEEVE.get(profile.name, profile.asset_class)
        if sleeve != "options" and not pos.option_type:
            non_opt_symbols.append(pos.symbol)

    price_map: dict[str, tuple[float, str]] = {}
    if non_opt_symbols:
        try:
            price_map = _fetch_prices(list(set(non_opt_symbols)))
        except Exception as exc:
            logger.warning("allocation-live: price fetch failed: %s", exc)

    # Aggregate by sleeve
    sleeve_dollars: dict[str, float] = {k: 0.0 for k in _SLEEVE_LABELS if k != "cash"}
    sleeve_positions: dict[str, int] = {k: 0 for k in _SLEEVE_LABELS if k != "cash"}

    for pos in open_positions:
        alloc = alloc_by_id.get(pos.allocation_id)
        if not alloc:
            continue
        profile = profile_by_id.get(alloc.profile_id)
        if not profile:
            continue

        sleeve = _PROFILE_TO_SLEEVE.get(profile.name, profile.asset_class or "stocks")
        if sleeve not in sleeve_dollars:
            sleeve = "stocks"

        is_options = bool(pos.option_type) or sleeve == "options"

        if is_options:
            # Premium paid: avg_cost_cents stores premium in cents (per share equivalent)
            # Deployed = premium_dollars × contracts × 100
            premium_dollars = (pos.avg_cost_cents or 0) / 100.0
            contracts = pos.contract_count or max(1, int(pos.qty or 1))
            value = premium_dollars * contracts * 100
        else:
            live_price, _ = price_map.get(pos.symbol, (0.0, "unavailable"))
            if live_price and float(live_price) > 0:
                value = float(live_price) * pos.qty
            else:
                value = (pos.avg_cost_cents / 100.0) * pos.qty

        sleeve_dollars[sleeve] += value
        sleeve_positions[sleeve] += 1

    # Get total portfolio value from snapshot for cash calculation
    total_portfolio_dollars = 0.0
    try:
        from app.core.canonical import compute_strategy_lab_aggregate
        agg = compute_strategy_lab_aggregate(current_user.id, db)
        total_portfolio_dollars = (agg.get("total_value_cents") or 0) / 100.0
    except Exception as exc:
        logger.warning("allocation-live: aggregate failed: %s", exc)
        total_portfolio_dollars = sum(sleeve_dollars.values())

    deployed_total = sum(sleeve_dollars.values())
    cash_dollars = max(0.0, total_portfolio_dollars - deployed_total)
    grand_total = max(total_portfolio_dollars, deployed_total)

    slices = []
    for key in ["stocks", "crypto", "options", "quant"]:
        dollars = sleeve_dollars[key]
        pos_count = sleeve_positions[key]
        if dollars > 0 or pos_count > 0:
            slices.append({
                "key": key,
                "label": _SLEEVE_LABELS[key],
                "dollars": round(dollars, 2),
                "pct": round(dollars / grand_total * 100, 1) if grand_total > 0 else 0.0,
                "color": _SLEEVE_COLORS[key],
                "position_count": pos_count,
            })

    if cash_dollars > 0.01:
        slices.append({
            "key": "cash",
            "label": "Cash",
            "dollars": round(cash_dollars, 2),
            "pct": round(cash_dollars / grand_total * 100, 1) if grand_total > 0 else 0.0,
            "color": _SLEEVE_COLORS["cash"],
            "position_count": 0,
        })

    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "total_portfolio_value": round(grand_total, 2),
        "deployed_value": round(deployed_total, 2),
        "cash_value": round(cash_dollars, 2),
        "slices": slices,
    }


@router.get("/regime/current")
def get_current_playbook_regime(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Return the most recent confirmed playbook regime from regime_snapshots table."""
    try:
        from strategy_lab.core.regime.regime_router_v2 import (
            get_current_regime,
            REGIME_ROUTING_ENABLED,
        )
        regime_data = get_current_regime(db)
        return {
            "regime": regime_data.get("regime", "CHOPPY"),
            "confidence": regime_data.get("confidence"),
            "snapshot_date": regime_data.get("snapshot_date"),
            "days_in_regime": regime_data.get("days_in_regime", 0),
            "days_since_snapshot": regime_data.get("days_since_snapshot"),
            "vix_level": regime_data.get("vix_level"),
            "routing_enabled": REGIME_ROUTING_ENABLED,
        }
    except Exception as exc:
        logger.warning("get_current_playbook_regime failed: %s", exc)
        return {"regime": "CHOPPY", "confidence": None, "days_in_regime": 0, "routing_enabled": False}
