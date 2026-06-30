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
from sqlalchemy import bindparam, text
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
    "options_income":             "Options Income",
    "options_directional":        "Options Directional",
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
        from app.core.canonical import compute_portfolio_snapshot, compute_bot_snapshot

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

        # Build per-portfolio snapshots (used for per-sleeve breakdown + bots list)
        port_snaps = {}
        for port in portfolios:
            port_allocs = [a for a in all_allocs if a.portfolio_id == port.id]
            pairs = [(a, profile_map[a.profile_id]) for a in port_allocs if a.profile_id in profile_map]
            snap = compute_portfolio_snapshot(port, pairs, db)
            port_snaps[port.asset_class] = (port, snap)

        # ── Per-allocation snapshots — single source of truth for totals ──
        # Previously this endpoint called compute_strategy_lab_aggregate (which
        # itself does compute_bot_snapshot per alloc × 2). Combined with the
        # per_alloc_snaps loop below + port_snaps loop above that produced
        # ~4× duplicate work per allocation. Compute once here, sum directly,
        # and reuse for sleeve bucketing.
        per_alloc_snaps: dict[int, Any] = {}
        for alloc in all_allocs:
            prof = profile_map.get(alloc.profile_id)
            if not prof:
                continue
            try:
                per_alloc_snaps[alloc.id] = compute_bot_snapshot(alloc, prof, db)
            except Exception as exc:
                logger.warning("snapshot: compute_bot_snapshot failed for alloc %d: %s", alloc.id, exc)

        # Totals from per-alloc snapshots (matches Dashboard + Strategy Lab).
        # Allocs that failed the snapshot fall back to starting_capital so we
        # never silently drop a real allocation.
        total_value = 0
        total_today_pnl = 0
        total_open_pos = 0
        starting_weighted_ret30 = 0.0
        for alloc in all_allocs:
            snap = per_alloc_snaps.get(alloc.id)
            if snap:
                total_value += int(snap.portfolio_value_cents or 0)
                total_today_pnl += int(snap.today_pnl_cents or 0)
                total_open_pos += int(snap.open_positions_count or 0)
                starting_weighted_ret30 += float(snap.return_30d_pct or 0.0) * int(snap.starting_capital_cents or 0)
            else:
                total_value += int(alloc.starting_capital_cents or 0)

        total_starting = sum(int(a.starting_capital_cents or 0) for a in all_allocs)
        total_alltime_pnl = total_value - total_starting

        # SHIP 3: all-time % = SUM(realized_cents from bot_daily_pnl) / SUM(inception_capital_cents)
        # Replaces the broken (total_value - total_starting) / total_starting formula which
        # re-zeroed history whenever starting_capital_cents changed (known-issues #10).
        _alloc_ids = [a.id for a in all_allocs]
        if _alloc_ids:
            _fleet_row = db.execute(
                text(
                    "SELECT COALESCE(SUM(p.realized_cents), 0), "
                    "       COALESCE(SUM(COALESCE(a.inception_capital_cents, a.starting_capital_cents, 0)), 0) "
                    "FROM bot_allocations a "
                    "LEFT JOIN bot_daily_pnl p ON p.allocation_id = a.id "
                    "  AND (p.note IS NULL OR p.note != 'track_reset_marker') "
                    "WHERE a.id IN :ids"
                ).bindparams(bindparam("ids", expanding=True)),
                {"ids": _alloc_ids},
            ).fetchone()
            _fleet_realized = int(_fleet_row[0] or 0)
            _fleet_inception = int(_fleet_row[1] or 0)
            return_alltime_pct = round(_fleet_realized / _fleet_inception * 100, 2) if _fleet_inception else 0.0
        else:
            return_alltime_pct = 0.0

        return_30d_pct = round(starting_weighted_ret30 / total_starting, 2) if total_starting else 0.0

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

        sleeve_buckets: dict[str, dict] = {
            k: {
                "starting_capital_cents": 0,
                "current_value_cents":    0,
                "open_positions":         0,
                "today_pnl_cents":        0,
                "active_bots":            0,
                "total_bots":             0,
                "bot_ids":                [],
                "return_30d_weighted":    0.0,
                # SHIP 3: accumulate per-bot realized and inception for correct all-time %
                "_alloc_ids":             [],
            } for k in sleeve_keys
        }
        for alloc in all_allocs:
            prof = profile_map.get(alloc.profile_id)
            if not prof:
                continue
            sleeve = _PROFILE_TO_SLEEVE.get(prof.name, prof.asset_class or "stocks")
            if sleeve == "stock":
                sleeve = "stocks"
            if sleeve not in sleeve_buckets:
                sleeve = "stocks"
            snap = per_alloc_snaps.get(alloc.id)
            pv = int(snap.portfolio_value_cents or 0) if snap else int(alloc.starting_capital_cents or 0)
            start_cap = int(snap.starting_capital_cents or 0) if snap else int(alloc.starting_capital_cents or 0)
            today_pnl = int(snap.today_pnl_cents or 0) if snap else 0
            open_pos = int(snap.open_positions_count or 0) if snap else 0
            ret30 = float(snap.return_30d_pct or 0.0) if snap else 0.0

            sleeve_buckets[sleeve]["current_value_cents"] += pv
            sleeve_buckets[sleeve]["starting_capital_cents"] += start_cap
            sleeve_buckets[sleeve]["today_pnl_cents"] += today_pnl
            sleeve_buckets[sleeve]["open_positions"] += open_pos
            sleeve_buckets[sleeve]["total_bots"] += 1
            sleeve_buckets[sleeve]["return_30d_weighted"] += ret30 * start_cap
            if alloc.enabled:
                sleeve_buckets[sleeve]["active_bots"] += 1
            if prof.name not in sleeve_buckets[sleeve]["bot_ids"]:
                sleeve_buckets[sleeve]["bot_ids"].append(prof.name)
            sleeve_buckets[sleeve]["_alloc_ids"].append(alloc.id)

        # Compute each sleeve's numerator (deployed + reserved). Use the SUM
        # of numerators as the denominator — guarantees sum(sleeve_pct) == 100%
        # by identity.
        sleeve_numerators: dict[str, int] = {}
        for k in sleeve_keys:
            sleeve_numerators[k] = sleeve_buckets[k]["current_value_cents"] + _sleeve_reservations.get(k, 0)

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

        # ── Per-sleeve breakdown ── current_value_cents is sourced from the
        # canonical aggregator to GUARANTEE parity with Dashboard / Strategy
        # Lab / Diagnostics. Metadata (active_bots, bot_ids, return_30d) stays
        # accumulated from the local per-alloc snapshot loop above — canonical
        # doesn't expose those today.
        try:
            from app.core.canonical import (
                get_canonical_portfolio_state,
                _canonicalize_sleeve,
            )
            _canonical_state = get_canonical_portfolio_state(current_user.id, db)
            _canonical_sleeve_cents = _canonical_state.get("sleeve_totals", {}) or {}
        except Exception as _canon_exc:
            logger.warning(
                "[portfolio/snapshot] canonical state lookup failed (falling back to "
                "local sleeve_buckets — may diverge from Dashboard): %s",
                _canon_exc,
            )
            _canonical_state = None
            _canonical_sleeve_cents = {}

        # Map response keys (lowercase) -> canonical Title Case labels.
        # Cash Floor's canonical bucket is "Cash"; we ROLL IT INTO the stocks
        # sleeve so by_sleeve.sum equals total_value (no $1+ divergence WARN).
        # PART 5 fix: previously cash_floor's value was orphaned (not in any
        # of the 4 sleeve_keys + not in capital_allocation), causing a
        # ~10% divergence between by_sleeve and total_value.
        _RESPONSE_TO_CANONICAL = {
            "stocks":  "Stocks",
            "crypto":  "Crypto",
            "options": "Options",
            "quant":   "Quant",
        }
        # PART 5: fold canonical "Cash" (cash_floor allocations) into "stocks".
        # 2026-06-29 v2 hotfix: drop the `> 0` gate. Cash Floor may be allocated
        # $100K but not yet deployed in SPY/QQQ → canonical "Cash" sleeve = 0
        # while cash_floor's snapshot still contributes $100K to total_value.
        # Without folding even-when-Cash-is-0 we get a $100K by_sleeve undercount.
        _cash_floor_canonical_cents = int(_canonical_sleeve_cents.get("Cash", 0) or 0)
        if "Stocks" in _canonical_sleeve_cents:
            _canonical_sleeve_cents["Stocks"] = int(
                _canonical_sleeve_cents.get("Stocks", 0) or 0
            ) + _cash_floor_canonical_cents

        by_sleeve: dict = {}
        for key in sleeve_keys:
            bucket = sleeve_buckets[key]
            start = bucket["starting_capital_cents"]
            # CANONICAL is the source of truth for current_value_cents. Fall back
            # to local accumulation only if canonical lookup failed above.
            # 2026-06-29 v2 hotfix: for "stocks", canonical (even with the Cash
            # fold above) may still be lower than local if cash_floor's
            # snapshot includes idle cash that canonical bucketed as Cash=0.
            # Use max(canonical, local) for stocks to guarantee no undercount.
            canonical_value = _canonical_sleeve_cents.get(_RESPONSE_TO_CANONICAL[key])
            if canonical_value is not None:
                value = int(canonical_value)
                if key == "stocks" and bucket["current_value_cents"] > value:
                    value = bucket["current_value_cents"]
            else:
                value = bucket["current_value_cents"]
            ret_30d = round(bucket["return_30d_weighted"] / start, 2) if start else 0.0
            # SHIP 3: all-time % = SUM(realized_cents from bot_daily_pnl) / SUM(inception_capital_cents)
            # Replaces (value - start) / start which re-zeroed history on capital resets.
            _sleeve_alloc_ids = bucket["_alloc_ids"]
            if _sleeve_alloc_ids:
                _sleeve_row = db.execute(
                    text(
                        "SELECT COALESCE(SUM(p.realized_cents), 0), "
                        "       COALESCE(SUM(COALESCE(a.inception_capital_cents, a.starting_capital_cents, 0)), 0) "
                        "FROM bot_allocations a "
                        "LEFT JOIN bot_daily_pnl p ON p.allocation_id = a.id "
                        "  AND (p.note IS NULL OR p.note != 'track_reset_marker') "
                        "WHERE a.id IN :ids"
                    ).bindparams(bindparam("ids", expanding=True)),
                    {"ids": _sleeve_alloc_ids},
                ).fetchone()
                _sleeve_realized = int(_sleeve_row[0] or 0)
                _sleeve_inception = int(_sleeve_row[1] or 0)
                ret_alltime = round(_sleeve_realized / _sleeve_inception * 100, 2) if _sleeve_inception else 0.0
            else:
                ret_alltime = 0.0
            by_sleeve[key] = {
                "starting_capital_cents": start,
                "current_value_cents":    value,
                "open_positions":         bucket["open_positions"],
                "today_pnl_cents":        bucket["today_pnl_cents"],
                "alltime_pnl_cents":      value - start,
                "alltime_return_pct":     ret_alltime,
                "return_30d_pct":         ret_30d,
                "active_bots":            bucket["active_bots"],
                "total_bots":             bucket["total_bots"],
                "bot_ids":                bucket["bot_ids"],
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

        # ── Invariant: sum(sleeves.current_value_cents) == total_value ± 1¢ ──
        # Reserved capital is a SEPARATE bucket (sleeve_config.reserved_capital_cents),
        # not part of total_value (which comes from canonical's per-alloc sum).
        # Loud log if drift — protects against split-brain regression.
        sleeve_sum = sum(by_sleeve[k]["current_value_cents"] for k in sleeve_keys)
        invariant_diff = abs(total_value - sleeve_sum)
        if invariant_diff > 100:  # > $1 drift
            reserved_sum = sum(_sleeve_reservations.values())
            logger.error(
                "[portfolio/snapshot] invariant violation user=%s total=%d sleeve_sum=%d reserved=%d diff=%d",
                current_user.id, total_value, sleeve_sum, reserved_sum, invariant_diff,
            )

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

        # Use option_type as the SOLE indicator (matching canonical.py:284).
        # The prior `or sleeve == "options"` fallback over-counted by 100x for
        # leftover share-style positions written by the pre-0931c1e equity
        # simulator into options bots — TSLA qty=3.6415 × $391.74 then × 100
        # inflated to $142k instead of $1.4k. The hard gate stopped new
        # writes; this prevents the leftovers from misreporting the sleeve.
        is_options = bool(pos.option_type)

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
