"""
Strategy Lab — eight-bot automated paper trading framework router.

GET  /api/bots                          — list all 8 BotProfiles + user's allocations
GET  /api/bots/{profile_name}           — single bot detail + positions + recent signals
POST /api/bots/{profile_name}/allocate  — create/update BotAllocation for current user
GET  /api/bots/{profile_name}/backtest  — stub: demo equity curve + metrics
GET  /api/bots/{profile_name}/positions — open positions for user's allocation
GET  /api/bots/{profile_name}/trades    — recent trades
GET  /api/bots/{profile_name}/signals   — recent signals
POST /api/bots/waitlist/{profile_name}  — join GoLiveWaitlist
DELETE /api/bots/waitlist/{profile_name} — opt out of waitlist
"""
from __future__ import annotations

import hashlib
import logging
import os
import random
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
from app.db.models.bots import (
    BotProfile,
    BotAllocation,
    BotSignal,
    BotPosition,
    BotTrade,
    BotDailyPnL,
    GoLiveWaitlist,
    BotWatchlist,
    BotHealth,
    RegimeSnapshot,
    StrategyWeight,
    CrossBotPosition,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bots", tags=["bots"])


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class AllocateBody(BaseModel):
    capital_pct: float = 10.0
    risk_profile: str = "standard"
    paper_mode: bool = True
    enabled: bool = True


class CustomBotAllocateBody(BaseModel):
    name: str
    description: str = ""
    riskProfile: str = "standard"
    capitalPct: float = 10.0


# ── Demo data helpers ─────────────────────────────────────────────────────────

_DISPLAY_NAMES: dict[str, str] = {
    "stock_swing":          "Stock Swing",
    "stock_day":            "Stock Day",
    "stock_lt":             "Stock Long-Term",
    "crypto_swing":         "Crypto Swing",
    "crypto_day":           "Crypto Day",
    "crypto_lt":            "Crypto Long-Term",
    "options_income":       "Options Income",
    "options_directional":  "Options Directional",
}

_DEMO_SYMBOLS = {
    "stock": ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "V", "UNH"],
    "crypto": ["BTC/USD", "ETH/USD", "SOL/USD", "AVAX/USD", "MATIC/USD"],
    "options": ["AAPL", "MSFT", "SPY", "NVDA", "AMZN", "QQQ", "GOOGL", "META", "TSLA", "JPM"],
}

_DEMO_SIDES = ["buy", "sell"]
_DEMO_STRATEGIES = ["momentum_breakout", "mean_reversion", "rsi_bands", "vwap_reversion", "factor_blend", "dca"]

_PORTFOLIO_DEFS = [
    {"asset_class": "stocks",  "name": "Stocks",  "emoji": "📈", "color_hex": "#A3E635",
     "bots": {"stock_swing": 1_666_700, "stock_day": 1_666_700, "stock_lt": 1_666_600}},
    {"asset_class": "crypto",  "name": "Crypto",  "emoji": "🪙", "color_hex": "#F59E0B",
     "bots": {"crypto_swing": 1_666_700, "crypto_day": 1_666_700, "crypto_lt": 1_666_600}},
    {"asset_class": "options", "name": "Options", "emoji": "⚡", "color_hex": "#8B5CF6",
     "bots": {"options_income": 2_500_000, "options_directional": 2_500_000}},
]


def _ensure_portfolios_for_user(db: Session, user_id: int) -> list:
    """Create missing StrategyPortfolio rows and bind BotAllocations. Returns all 3 portfolios."""
    from app.db.models.bots import StrategyPortfolio
    now = datetime.now(timezone.utc)
    portfolios = []
    for defn in _PORTFOLIO_DEFS:
        existing = (
            db.query(StrategyPortfolio)
            .filter(
                StrategyPortfolio.user_id == user_id,
                StrategyPortfolio.asset_class == defn["asset_class"],
            )
            .first()
        )
        if not existing:
            existing = StrategyPortfolio(
                user_id=user_id,
                name=defn["name"],
                asset_class=defn["asset_class"],
                starting_capital_cents=5_000_000,
                emoji=defn["emoji"],
                color_hex=defn["color_hex"],
                created_at=now,
            )
            db.add(existing)
            db.flush()

        # Bind allocations
        for bot_name, capital_cents in defn["bots"].items():
            profile = db.query(BotProfile).filter(BotProfile.name == bot_name).first()
            if not profile:
                continue
            alloc = (
                db.query(BotAllocation)
                .filter(
                    BotAllocation.user_id == user_id,
                    BotAllocation.profile_id == profile.id,
                )
                .first()
            )
            if alloc and alloc.portfolio_id is None:
                alloc.portfolio_id = existing.id
                alloc.capital_cents_within_portfolio = capital_cents
                alloc.updated_at = now

        portfolios.append(existing)
    db.commit()
    return portfolios


def _seeded_rng(profile_name: str) -> random.Random:
    """Return a deterministic RNG seeded on the profile name."""
    seed = int(hashlib.md5(profile_name.encode()).hexdigest()[:8], 16)
    return random.Random(seed)


def _demo_30d_return(profile_name: str) -> float:
    """Deterministic fake 30d return between +3% and +22%."""
    rng = _seeded_rng(profile_name)
    return round(rng.uniform(3.0, 22.0), 2)


def _demo_today_pnl(profile_name: str) -> float:
    """Deterministic small ± daily P&L (-$200 to +$200)."""
    rng = _seeded_rng(profile_name + "_today")
    return round(rng.uniform(-200.0, 200.0), 2)


def _demo_positions(profile_name: str, asset_class: str) -> list[dict]:
    """Return 0-3 fake open positions for demo users (not written to DB)."""
    rng = _seeded_rng(profile_name + "_pos")
    count = rng.randint(0, 3)
    symbols = _DEMO_SYMBOLS.get(asset_class, _DEMO_SYMBOLS["stock"])
    positions = []
    base_time = datetime.now(timezone.utc)
    for i in range(count):
        sym = rng.choice(symbols)
        entry = round(rng.uniform(50.0, 500.0), 2)
        change_pct = rng.uniform(-5.0, 12.0)
        current = round(entry * (1 + change_pct / 100), 2)
        qty = round(rng.uniform(1.0, 20.0), 4)
        opened_at = base_time - timedelta(days=rng.randint(1, 7))
        positions.append({
            "id": -(i + 1),  # negative IDs for demo rows
            "symbol": sym,
            "qty": qty,
            "avg_cost_cents": int(entry * 100),
            "avg_cost": entry,
            "current_price": current,
            "unrealized_pnl": round((current - entry) * qty, 2),
            "unrealized_pnl_pct": round(change_pct, 2),
            "opened_at": opened_at.isoformat(),
            "closed_at": None,
            "exit_reason": None,
            "is_paper": True,
            "is_demo": True,
        })
    return positions


def _demo_equity_curve(profile_name: str) -> list[dict]:
    """Return a 30-point fake equity curve for the backtest stub."""
    rng = _seeded_rng(profile_name + "_curve")
    equity = 10_000.0
    curve = []
    start = datetime.now(timezone.utc) - timedelta(days=30)
    for i in range(30):
        day = start + timedelta(days=i)
        change = rng.uniform(-0.8, 1.4)
        equity = round(equity * (1 + change / 100), 2)
        curve.append({"date": day.strftime("%Y-%m-%d"), "equity": equity})
    return curve


# ── Serializers ───────────────────────────────────────────────────────────────

def _profile_to_dict(p: BotProfile, allocation: Optional[BotAllocation] = None) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "description": p.description,
        "asset_class": p.asset_class,
        "config": p.config_json or {},
        "enabled": p.enabled,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "allocation": _allocation_to_dict(allocation) if allocation else None,
    }


def _allocation_to_dict(a: BotAllocation) -> dict:
    return {
        "id": a.id,
        "profile_id": a.profile_id,
        "capital_pct": a.capital_pct,
        "risk_profile": a.risk_profile,
        "paper_mode": a.paper_mode,
        "go_live_requested": a.go_live_requested,
        "enabled": a.enabled,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "updated_at": a.updated_at.isoformat() if a.updated_at else None,
    }


def _signal_to_dict(s: BotSignal) -> dict:
    return {
        "id": s.id,
        "ts": s.ts.isoformat() if s.ts else None,
        "symbol": s.symbol,
        "side": s.side,
        "confidence": s.confidence,
        "size_hint": s.size_hint,
        "reason": s.reason,
        "strategy": s.strategy,
    }


def _position_to_dict(p: BotPosition) -> dict:
    return {
        "id": p.id,
        "symbol": p.symbol,
        "qty": p.qty,
        "avg_cost_cents": p.avg_cost_cents,
        "avg_cost": round(p.avg_cost_cents / 100, 2),
        "opened_at": p.opened_at.isoformat() if p.opened_at else None,
        "closed_at": p.closed_at.isoformat() if p.closed_at else None,
        "exit_reason": p.exit_reason,
        "is_paper": p.is_paper,
    }


def _trade_to_dict(t: BotTrade) -> dict:
    return {
        "id": t.id,
        "symbol": t.symbol,
        "side": t.side,
        "qty": t.qty,
        "fill_price_cents": t.fill_price_cents,
        "fill_price": round(t.fill_price_cents / 100, 2),
        "fees_cents": t.fees_cents,
        "ts": t.ts.isoformat() if t.ts else None,
        "alpaca_order_id": t.alpaca_order_id,
        "is_paper": t.is_paper,
    }


# ── GET /api/bots ─────────────────────────────────────────────────────────────

@router.get("")
def list_bots(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """List all 8 BotProfiles with user's allocations and demo performance data."""
    profiles = db.query(BotProfile).filter(BotProfile.enabled.is_(True)).all()

    # Index user's allocations by profile_id for quick lookup
    user_allocations: dict[int, BotAllocation] = {}
    if profiles:
        profile_ids = [p.id for p in profiles]
        allocs = (
            db.query(BotAllocation)
            .filter(
                BotAllocation.user_id == current_user.id,
                BotAllocation.profile_id.in_(profile_ids),
            )
            .all()
        )
        user_allocations = {a.profile_id: a for a in allocs}

    from app.core.canonical import compute_bot_snapshot

    result = []
    for p in profiles:
        allocation = user_allocations.get(p.id)

        row = _profile_to_dict(p, allocation)
        row["display_name"] = _DISPLAY_NAMES.get(p.name, p.name.replace("_", " ").title())

        if allocation is not None:
            snap = compute_bot_snapshot(allocation, p, db)
            row["demo"] = False
            row["return_30d_pct"] = snap.return_30d_pct
            row["today_pnl_usd"] = round(snap.today_pnl_cents / 100, 2)
            row["open_positions"] = snap.open_positions
            row["open_positions_count"] = snap.open_positions_count
            row["portfolio_value_cents"] = snap.portfolio_value_cents
            row["all_time_return_pct"] = snap.all_time_return_pct
        else:
            row["demo"] = True
            row["return_30d_pct"] = _demo_30d_return(p.name)
            row["today_pnl_usd"] = _demo_today_pnl(p.name)
            row["open_positions"] = _demo_positions(p.name, p.asset_class)
            row["open_positions_count"] = len(row["open_positions"])
            row["portfolio_value_cents"] = None
            row["all_time_return_pct"] = None

        result.append(row)

    return {"bots": result}


# ── GET /api/bots/regime ─────────────────────────────────────────────────────

@router.get("/regime")
def get_regime(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return the latest RegimeSnapshot from the database."""
    snap = db.query(RegimeSnapshot).order_by(RegimeSnapshot.ts.desc()).first()
    if not snap:
        # Return safe defaults if no snapshot exists yet
        return {
            "vix_regime": "mid",
            "trend_regime": "chop",
            "vol_pctile": 50.0,
            "btc_dominance": 50.0,
            "btc_funding_rate": 0.0,
            "spy_price": None,
            "vix_value": None,
            "ts": None,
            "source": "defaults",
        }
    return {
        "id": snap.id,
        "ts": snap.ts.isoformat() if snap.ts else None,
        "vix_regime": snap.vix_regime,
        "trend_regime": snap.trend_regime,
        "vol_pctile": snap.vol_pctile,
        "btc_dominance": snap.btc_dominance,
        "btc_funding_rate": snap.btc_funding_rate,
        "spy_price": snap.spy_price,
        "vix_value": snap.vix_value,
        "source": "db",
    }


# ── POST /api/bots/pause-all ──────────────────────────────────────────────────

@router.post("/pause-all")
def pause_all_bots(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Pause all of the current user's BotAllocations."""
    allocs = (
        db.query(BotAllocation)
        .filter(
            BotAllocation.user_id == current_user.id,
            BotAllocation.enabled.is_(True),
        )
        .all()
    )
    count = 0
    now = datetime.now(timezone.utc)
    for a in allocs:
        a.enabled = False
        a.paused_reason = "user_pause"
        a.updated_at = now
        count += 1
    db.commit()
    return {"status": "paused", "allocations_paused": count}


# ── POST /api/bots/resume-all ─────────────────────────────────────────────────

@router.post("/resume-all")
def resume_all_bots(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Resume all of the current user's BotAllocations (clears paused_reason)."""
    allocs = (
        db.query(BotAllocation)
        .filter(
            BotAllocation.user_id == current_user.id,
            BotAllocation.enabled.is_(False),
        )
        .all()
    )
    count = 0
    now = datetime.now(timezone.utc)
    for a in allocs:
        a.enabled = True
        a.paused_reason = None
        a.updated_at = now
        count += 1
    db.commit()
    return {"status": "resumed", "allocations_resumed": count}


# ── POST /api/bots/activate-all ──────────────────────────────────────────────

@router.post("/activate-all")
def activate_all_bots(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Ensure every enabled BotProfile has an active allocation for this user.

    Creates missing allocations and re-enables any that were disabled.
    """
    profiles = db.query(BotProfile).filter(BotProfile.enabled.is_(True)).all()
    now = datetime.now(timezone.utc)
    activated = 0
    for p in profiles:
        existing = (
            db.query(BotAllocation)
            .filter(
                BotAllocation.user_id == current_user.id,
                BotAllocation.profile_id == p.id,
            )
            .first()
        )
        if existing:
            if not existing.enabled:
                existing.enabled = True
                existing.paused_reason = None
                existing.updated_at = now
                activated += 1
        else:
            db.add(BotAllocation(
                user_id=current_user.id,
                profile_id=p.id,
                capital_pct=10.0,
                risk_profile="standard",
                paper_mode=True,
                enabled=True,
                created_at=now,
                updated_at=now,
            ))
            activated += 1
    db.commit()
    _ensure_portfolios_for_user(db, current_user.id)
    return {"ok": True, "total_profiles": len(profiles), "activated": activated}


# ── GET /api/bots/portfolios ─────────────────────────────────────────────────

@router.get("/portfolios")
def get_portfolios(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return the 3 strategy portfolios with their bots and live P&L (canonical)."""
    from app.db.models.bots import StrategyPortfolio
    from app.core.canonical import compute_portfolio_snapshot, DISPLAY_NAMES

    try:
        _ensure_portfolios_for_user(db, current_user.id)
    except Exception as exc:
        logger.warning("_ensure_portfolios_for_user failed: %s", exc)

    try:
        portfolios_db = (
            db.query(StrategyPortfolio)
            .filter(StrategyPortfolio.user_id == current_user.id)
            .order_by(StrategyPortfolio.id)
            .all()
        )
    except Exception as exc:
        logger.error("get_portfolios query failed: %s", exc)
        return {"portfolios": []}

    profiles = db.query(BotProfile).filter(BotProfile.enabled.is_(True)).all()
    profile_map = {p.id: p for p in profiles}

    all_allocs = (
        db.query(BotAllocation)
        .filter(BotAllocation.user_id == current_user.id)
        .all()
    )

    result = []
    for port in portfolios_db:
        try:
            port_allocs = [a for a in all_allocs if a.portfolio_id == port.id]
            pairs = [(a, profile_map[a.profile_id]) for a in port_allocs if a.profile_id in profile_map]

            snap = compute_portfolio_snapshot(port, pairs, db)
            pnl_cents = snap.portfolio_value_cents - snap.starting_capital_cents

            bots = []
            for bot in snap.bots:
                alloc = next((a for a in port_allocs if a.id == bot.allocation_id), None)
                profile = next((p for _, p in pairs if p.name == bot.profile_name), None)

                row = _profile_to_dict(profile, alloc) if profile and alloc else {}
                row["name"] = bot.profile_name
                row["display_name"] = bot.display_name
                row["demo"] = False
                row["return_30d_pct"] = bot.return_30d_pct
                row["today_pnl_usd"] = round(bot.today_pnl_cents / 100, 2)
                row["open_positions"] = bot.open_positions
                row["open_positions_count"] = bot.open_positions_count
                row["portfolio_value_cents"] = bot.portfolio_value_cents
                row["all_time_return_pct"] = bot.all_time_return_pct
                row["capital_cents_within_portfolio"] = bot.capital_cents_within_portfolio
                row["capital_pct_within_portfolio"] = (
                    round(bot.capital_cents_within_portfolio / snap.starting_capital_cents * 100, 1)
                    if snap.starting_capital_cents else 0
                )
                bots.append(row)

            result.append({
                "id": port.id,
                "name": port.name,
                "asset_class": port.asset_class,
                "emoji": port.emoji,
                "color_hex": port.color_hex,
                "starting_capital_cents": snap.starting_capital_cents,
                "current_value_cents": snap.portfolio_value_cents,
                "pnl_cents": pnl_cents,
                "pnl_pct": round(snap.all_time_return_pct, 3),
                "today_pnl_cents": snap.today_pnl_cents,
                "today_pnl_pct": snap.today_pnl_pct,
                "return_30d_pct": snap.return_30d_pct,
                "realized_pnl_cents": snap.realized_pnl_cents,
                "unrealized_pnl_cents": snap.unrealized_pnl_cents,
                "open_positions_count": snap.open_positions_count,
                "watchlist_count": snap.watchlist_count,
                "bots_active": snap.bots_active,
                "bots_total": snap.bots_total,
                "enabled": port.enabled,
                "bots": bots,
            })
        except Exception as exc:
            logger.error("portfolio snapshot failed for %s: %s", getattr(port, "name", "?"), exc)

    return {"portfolios": result}


# ── GET /api/bots/portfolios/{portfolio_id}/activity ─────────────────────────

@router.get("/portfolios/{portfolio_id}/activity")
def get_portfolio_activity(
    portfolio_id: int,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Recent trades across all bots in a portfolio — proves every P&L dollar."""
    from app.db.models.bots import StrategyPortfolio

    port = db.query(StrategyPortfolio).filter(
        StrategyPortfolio.id == portfolio_id,
        StrategyPortfolio.user_id == current_user.id,
    ).first()
    if not port:
        raise HTTPException(404, "Portfolio not found")

    port_allocs = (
        db.query(BotAllocation)
        .filter(
            BotAllocation.user_id == current_user.id,
            BotAllocation.portfolio_id == portfolio_id,
        )
        .all()
    )
    alloc_ids = [a.id for a in port_allocs]
    if not alloc_ids:
        return {"trades": [], "total": 0}

    # Profile names for display
    profile_ids = list({a.profile_id for a in port_allocs})
    profiles = db.query(BotProfile).filter(BotProfile.id.in_(profile_ids)).all()
    profile_name_by_id = {p.id: p.name for p in profiles}
    alloc_profile = {a.id: profile_name_by_id.get(a.profile_id, "") for a in port_allocs}

    trades = (
        db.query(BotTrade)
        .filter(BotTrade.allocation_id.in_(alloc_ids))
        .order_by(BotTrade.ts.desc())
        .limit(limit)
        .all()
    )

    # For sell trades, look up the position to compute realized PnL
    position_ids = [t.position_id for t in trades if t.position_id and t.side == "sell"]
    position_map = {}
    if position_ids:
        pos_rows = db.query(BotPosition).filter(BotPosition.id.in_(position_ids)).all()
        position_map = {p.id: p for p in pos_rows}

    result = []
    for t in trades:
        bot_name = alloc_profile.get(t.allocation_id, "")
        from app.core.canonical import DISPLAY_NAMES
        display = DISPLAY_NAMES.get(bot_name, bot_name.replace("_", " ").title())
        fill_price = round(t.fill_price_cents / 100, 2)

        realized_pnl = None
        if t.side == "sell" and t.position_id and t.position_id in position_map:
            pos = position_map[t.position_id]
            realized_pnl = round((fill_price - pos.avg_cost_cents / 100) * t.qty, 2)

        result.append({
            "id": t.id,
            "ts": t.ts.isoformat() if t.ts else None,
            "bot_name": bot_name,
            "bot_display_name": display,
            "symbol": t.symbol,
            "side": t.side,
            "qty": t.qty,
            "fill_price": fill_price,
            "fill_price_cents": t.fill_price_cents,
            "realized_pnl": realized_pnl,
            "is_paper": t.is_paper,
        })

    return {"trades": result, "total": len(result)}


# ── POST /api/bots/portfolios/setup ──────────────────────────────────────────

@router.post("/portfolios/setup")
def setup_portfolios(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Idempotent: create the 3 strategy portfolios for the current user if missing."""
    from app.db.models.bots import StrategyPortfolio
    _ensure_portfolios_for_user(db, current_user.id)
    count = db.query(StrategyPortfolio).filter(
        StrategyPortfolio.user_id == current_user.id
    ).count()
    return {"ok": True, "portfolios": count}


# ── GET /api/bots/cross-bot-positions ────────────────────────────────────────

@router.get("/cross-bot-positions")
def get_cross_bot_positions(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Aggregate open BotPosition rows across all of the user's bot allocations."""
    # Get all allocations for this user with their profile names
    allocations = (
        db.query(BotAllocation)
        .filter(BotAllocation.user_id == current_user.id)
        .all()
    )
    alloc_ids = [a.id for a in allocations]
    if not alloc_ids:
        return []

    # Load profile names once
    profile_ids = list({a.profile_id for a in allocations})
    profiles = db.query(BotProfile).filter(BotProfile.id.in_(profile_ids)).all()
    profile_name_by_id = {p.id: p.name for p in profiles}
    alloc_profile_name = {a.id: profile_name_by_id.get(a.profile_id, str(a.profile_id)) for a in allocations}

    # Load all open positions across every bot
    open_positions = (
        db.query(BotPosition)
        .filter(
            BotPosition.allocation_id.in_(alloc_ids),
            BotPosition.closed_at.is_(None),
        )
        .all()
    )

    # Aggregate by symbol
    by_symbol: dict[str, dict] = {}
    for pos in open_positions:
        bot_name = alloc_profile_name.get(pos.allocation_id, str(pos.allocation_id))
        sym = pos.symbol
        if sym not in by_symbol:
            by_symbol[sym] = {"symbol": sym, "total_qty": 0.0, "bots_holding": [], "exposure_pct": 0.0, "pnl": 0.0}
        by_symbol[sym]["total_qty"] += pos.qty
        if bot_name not in by_symbol[sym]["bots_holding"]:
            by_symbol[sym]["bots_holding"].append(bot_name)

    return sorted(by_symbol.values(), key=lambda x: x["symbol"])


# ── GET /api/bots/cross-bot-watchlist ────────────────────────────────────────

@router.get("/cross-bot-watchlist")
def get_cross_bot_watchlist(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Aggregate BotWatchlist rows across all of the user's bot allocations."""
    allocations = (
        db.query(BotAllocation)
        .filter(BotAllocation.user_id == current_user.id)
        .all()
    )
    if not allocations:
        return []

    profile_ids = list({a.profile_id for a in allocations})
    profiles = db.query(BotProfile).filter(BotProfile.id.in_(profile_ids)).all()
    profile_name_by_id = {p.id: p.name for p in profiles}

    rows = (
        db.query(BotWatchlist)
        .filter(
            BotWatchlist.profile_id.in_(profile_ids),
            BotWatchlist.status.in_(["active", "watching", "pending_entry"]),
        )
        .order_by(BotWatchlist.score.desc())
        .all()
    )

    # Aggregate by symbol — track which bots are watching each
    by_symbol: dict[str, dict] = {}
    for row in rows:
        sym = row.symbol
        bot_name = profile_name_by_id.get(row.profile_id, str(row.profile_id))
        if sym not in by_symbol:
            by_symbol[sym] = {
                "symbol": sym,
                "bots_watching": [],
                "score": row.score or 0,
                "status": row.status,
                "reasons": row.reasons or [],
                "added_at": row.added_at.isoformat() if row.added_at else None,
            }
        else:
            # Keep highest score
            if (row.score or 0) > by_symbol[sym]["score"]:
                by_symbol[sym]["score"] = row.score or 0
                by_symbol[sym]["reasons"] = row.reasons or []
        if bot_name not in by_symbol[sym]["bots_watching"]:
            by_symbol[sym]["bots_watching"].append(bot_name)

    return sorted(by_symbol.values(), key=lambda x: -x["score"])


# ── GET /api/bots/{profile_name}/activity ────────────────────────────────────

@router.get("/{profile_name}/activity")
def get_bot_activity(
    profile_name: str,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return recent signals/fills for the activity tab of a bot profile."""
    profile = db.query(BotProfile).filter(BotProfile.name == profile_name).first()
    if not profile:
        raise HTTPException(404, f"Bot profile '{profile_name}' not found")

    allocation = (
        db.query(BotAllocation)
        .filter(
            BotAllocation.user_id == current_user.id,
            BotAllocation.profile_id == profile.id,
        )
        .first()
    )
    if not allocation:
        return {"activity": [], "demo": True}

    signals = (
        db.query(BotSignal)
        .filter(BotSignal.allocation_id == allocation.id)
        .order_by(BotSignal.ts.desc())
        .limit(limit)
        .all()
    )

    # Build a lookup: symbol → most recent trade to enrich signals with result
    recent_trades_by_symbol: dict[str, BotTrade] = {}
    if signals:
        symbols = list({s.symbol for s in signals})
        trades = (
            db.query(BotTrade)
            .filter(
                BotTrade.allocation_id == allocation.id,
                BotTrade.symbol.in_(symbols),
            )
            .order_by(BotTrade.ts.desc())
            .all()
        )
        for t in trades:
            if t.symbol not in recent_trades_by_symbol:
                recent_trades_by_symbol[t.symbol] = t

    activity = []
    for s in signals:
        trade = recent_trades_by_symbol.get(s.symbol)
        result = None
        if trade and trade.ts >= s.ts:
            result = {
                "fill_price": round(trade.fill_price_cents / 100, 2),
                "qty": trade.qty,
                "side": trade.side,
                "ts": trade.ts.isoformat() if trade.ts else None,
            }
        activity.append({
            "id": s.id,
            "ts": s.ts.isoformat() if s.ts else None,
            "symbol": s.symbol,
            "side": s.side,
            "confidence": s.confidence,
            "size_hint": s.size_hint,
            "reason": s.reason,
            "strategy": s.strategy,
            "result": result,
        })

    return {"activity": activity, "demo": False, "count": len(activity)}


# ── GET /api/bots/{profile_name}/strategy-weights ────────────────────────────

@router.get("/{profile_name}/strategy-weights")
def get_strategy_weights(
    profile_name: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return StrategyWeight rows for the given bot profile."""
    profile = db.query(BotProfile).filter(BotProfile.name == profile_name).first()
    if not profile:
        raise HTTPException(404, f"Bot profile '{profile_name}' not found")

    rows = (
        db.query(StrategyWeight)
        .filter(StrategyWeight.profile_id == profile.id)
        .order_by(StrategyWeight.strategy_name)
        .all()
    )
    return {
        "profile_name": profile_name,
        "weights": [
            {
                "id": r.id,
                "strategy_name": r.strategy_name,
                "current_weight": r.current_weight,
                "base_weight": r.base_weight,
                "wins": r.wins,
                "losses": r.losses,
                "win_rate": round(r.wins / max(r.wins + r.losses, 1), 3),
                "last_30_trades": r.last_30_trades or [],
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                "user_locked": r.user_locked,
            }
            for r in rows
        ],
        "count": len(rows),
    }


# ── PATCH /api/bots/{profile_name}/strategy-weights/{strategy} ───────────────

@router.patch("/{profile_name}/strategy-weights/{strategy}")
def update_strategy_weight(
    profile_name: str,
    strategy: str,
    data: dict = Body(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Lock or unlock a strategy weight for a bot profile.

    Body: {user_locked: bool}
    Only user_locked may be set via this endpoint; weight adjustment is
    handled by the Thompson sampling engine.
    """
    profile = db.query(BotProfile).filter(BotProfile.name == profile_name).first()
    if not profile:
        raise HTTPException(404, f"Bot profile '{profile_name}' not found")

    row = (
        db.query(StrategyWeight)
        .filter(
            StrategyWeight.profile_id == profile.id,
            StrategyWeight.strategy_name == strategy,
        )
        .first()
    )
    if not row:
        raise HTTPException(404, f"Strategy weight not found: {strategy}")

    if "user_locked" in data:
        user_locked = bool(data["user_locked"])
        row.user_locked = user_locked

    db.commit()
    db.refresh(row)
    return {
        "strategy_name": row.strategy_name,
        "user_locked": row.user_locked,
        "current_weight": row.current_weight,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


# ── POST /api/bots/{profile_name}/qa ─────────────────────────────────────────

@router.post("/{profile_name}/qa")
def ask_bot_question(
    profile_name: str,
    data: dict = Body(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Co-Pilot Q&A endpoint for a bot profile.

    Body: {question: str}
    Returns: {answer: str, citations: list, confidence: float}
    """
    profile = db.query(BotProfile).filter(BotProfile.name == profile_name).first()
    if not profile:
        raise HTTPException(404, f"Bot profile '{profile_name}' not found")

    question = str(data.get("question", "")).strip()
    if not question:
        raise HTTPException(400, "question is required")

    # Attempt to use expert-layer bot_qa module if available
    try:
        from strategy_lab.expert import bot_qa  # type: ignore[import]
        result = bot_qa.answer_question(
            question=question,
            profile_name=profile_name,
            profile_config=profile.config_json or {},
            db=db,
            user_id=current_user.id,
        )
        return {
            "answer": result.get("answer", ""),
            "citations": result.get("citations", []),
            "confidence": result.get("confidence", 0.0),
        }
    except ImportError:
        pass
    except Exception as exc:
        logger.warning(f"bot_qa.answer_question failed: {exc}")

    # Fallback: minimal rule-based responses
    q_lower = question.lower()
    if any(w in q_lower for w in ("sharpe", "performance", "return", "backtest")):
        answer = (
            f"The {profile_name} bot is running in paper mode. "
            "Check the /backtest endpoint for demo performance metrics including Sharpe, Sortino, and max drawdown."
        )
    elif any(w in q_lower for w in ("position", "holding", "open")):
        answer = (
            f"Use GET /api/bots/{profile_name}/positions to see current open positions, "
            "or visit the Positions tab in the Strategy Lab dashboard."
        )
    elif any(w in q_lower for w in ("strategy", "signal", "weight")):
        answer = (
            f"The {profile_name} bot uses multiple strategies with Thompson-sampled weights. "
            f"Use GET /api/bots/{profile_name}/strategy-weights to inspect per-strategy weights and win rates."
        )
    elif any(w in q_lower for w in ("stop", "pause", "halt")):
        answer = "Use POST /api/bots/pause-all to pause all bots, or update your allocation to enabled=false."
    else:
        answer = (
            f"I'm the Co-Pilot for the {profile_name} bot. You can ask about performance, "
            "positions, strategies, or risk settings. The full expert Q&A module (bot_qa.py) "
            "is not yet loaded — answers are currently rule-based."
        )

    return {"answer": answer, "citations": [], "confidence": 0.4}


# ── Simple 60-second in-memory cache ─────────────────────────────────────────

_cards_cache: dict = {}  # key: user_id, value: {data, ts}
_CARDS_CACHE_TTL = 60  # seconds


# ── GET /api/bots/cards ───────────────────────────────────────────────────────

@router.get("/cards")
def get_bot_cards(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Returns rich card payload for all 6 bot profiles.
    Cached 60s per user.
    """
    import time
    import math
    from datetime import date, timedelta

    user_id = current_user.id
    now = time.time()

    # Check cache
    cached = _cards_cache.get(user_id)
    if cached and (now - cached["ts"]) < _CARDS_CACHE_TTL:
        return cached["data"]

    profiles = db.query(BotProfile).order_by(BotProfile.id).all()
    result = []

    for profile in profiles:
        # Get user's allocation for this bot
        allocation = db.query(BotAllocation).filter(
            BotAllocation.profile_id == profile.id,
            BotAllocation.user_id == current_user.id
        ).first()

        # Status
        if allocation is None:
            status = "inactive"
        elif not allocation.enabled:
            status = "paused"
        elif allocation.paused_reason and "health" in (allocation.paused_reason or ""):
            status = "halted"
        else:
            status = "active"

        # Get last 30 days of BotDailyPnL
        today = date.today()
        thirty_days_ago = today - timedelta(days=30)
        seven_days_ago = today - timedelta(days=7)

        daily_pnl_rows = []
        if allocation:
            daily_pnl_rows = db.query(BotDailyPnL).filter(
                BotDailyPnL.allocation_id == allocation.id,
                BotDailyPnL.date >= thirty_days_ago
            ).order_by(BotDailyPnL.date).all()

        # today_pnl
        today_row = next((r for r in daily_pnl_rows if r.date == today), None)
        today_pnl_cents = (
            (today_row.realized_cents or 0) + (today_row.unrealized_cents or 0)
        ) if today_row else 0

        # capital base (use starting_capital_cents if set, else estimate from capital_pct)
        # $100k paper balance default
        PAPER_BALANCE = 100_000_00  # cents = $100,000
        capital_pct = allocation.capital_pct if allocation else 0
        capital_cents = int(PAPER_BALANCE * (capital_pct / 100)) if allocation else 0
        starting_capital = getattr(allocation, 'starting_capital_cents', None) or capital_cents

        # portfolio_value = capital + cumulative realized + today unrealized
        cumulative_realized = sum(
            (r.realized_cents or 0) for r in daily_pnl_rows
        )
        today_unrealized = (today_row.unrealized_cents or 0) if today_row else 0
        portfolio_value_cents = capital_cents + cumulative_realized + today_unrealized

        # today_pnl_pct
        yesterday_value = portfolio_value_cents - today_pnl_cents
        today_pnl_pct = (today_pnl_cents / yesterday_value) if yesterday_value else 0

        # 7d avg P&L
        rows_7d = [r for r in daily_pnl_rows if r.date >= seven_days_ago]
        if rows_7d:
            daily_pnl_avg_7d_cents = int(
                sum((r.realized_cents or 0) + (r.unrealized_cents or 0) for r in rows_7d) / len(rows_7d)
            )
        else:
            daily_pnl_avg_7d_cents = None  # show "—"

        # 30d avg P&L
        if len(daily_pnl_rows) >= 5:  # require at least 5 data points
            daily_pnl_avg_30d_cents = int(
                sum((r.realized_cents or 0) + (r.unrealized_cents or 0) for r in daily_pnl_rows) / len(daily_pnl_rows)
            )
        else:
            daily_pnl_avg_30d_cents = None

        # return_30d: use BotDailyPnL equity curve if available
        oldest_row = daily_pnl_rows[0] if daily_pnl_rows else None
        if oldest_row and getattr(oldest_row, 'portfolio_value_eod_cents', None):
            value_30d_ago = oldest_row.portfolio_value_eod_cents
            return_30d_pct = (portfolio_value_cents - value_30d_ago) / value_30d_ago if value_30d_ago else 0
        else:
            # fallback: use cumulative realized over 30d
            return_30d_pct = (cumulative_realized / capital_cents) if capital_cents else 0

        # all-time return
        return_all_time_pct = (
            (portfolio_value_cents - starting_capital) / starting_capital
        ) if starting_capital else 0

        # Sharpe 30d
        daily_returns = []
        if len(daily_pnl_rows) >= 2:
            for r in daily_pnl_rows:
                day_total = (r.realized_cents or 0) + (r.unrealized_cents or 0)
                if capital_cents:
                    daily_returns.append(day_total / capital_cents)

        sharpe_30d = None
        if len(daily_returns) >= 5:
            mean_r = sum(daily_returns) / len(daily_returns)
            variance = sum((r - mean_r) ** 2 for r in daily_returns) / len(daily_returns)
            std_r = math.sqrt(variance) if variance > 0 else 0
            if std_r > 0:
                sharpe_30d = round((mean_r / std_r) * math.sqrt(252), 2)

        # win_rate_30d from BotTrade
        trades_30d = []
        if allocation:
            trades_30d = db.query(BotTrade).filter(
                BotTrade.allocation_id == allocation.id,
                BotTrade.ts >= thirty_days_ago
            ).all()

        # A "win" = sell trade where fill_price > avg_cost of that position
        # Simplified: any trade tagged "sell" with positive realized PnL
        # For paper: count BotPosition rows closed in last 30 days
        closed_positions_30d = []
        if allocation:
            closed_positions_30d = db.query(BotPosition).filter(
                BotPosition.allocation_id == allocation.id,
                BotPosition.closed_at >= thirty_days_ago,
                BotPosition.closed_at.isnot(None)
            ).all()

        wins = 0
        losses = 0
        for pos in closed_positions_30d:
            # winning if position had positive PnL
            # approximate: we don't store PnL on BotPosition directly,
            # use exit_reason as proxy (stop_loss = loss, target = win)
            exit_r = pos.exit_reason or ""
            if "target" in exit_r or "profit" in exit_r:
                wins += 1
            elif "stop" in exit_r or "loss" in exit_r:
                losses += 1
            else:
                # time stop or manual — count as loss if we don't know
                losses += 1
        total_closed = wins + losses
        win_rate_pct = (wins / total_closed) if total_closed > 0 else None

        # open positions count
        open_positions_count = 0
        if allocation:
            open_positions_count = db.query(BotPosition).filter(
                BotPosition.allocation_id == allocation.id,
                BotPosition.closed_at.is_(None)
            ).count()

        # equity curve: 30 data points (one per session in last 30 days)
        equity_curve = []
        for r in daily_pnl_rows:
            eod_val = getattr(r, 'portfolio_value_eod_cents', None)
            if eod_val:
                equity_curve.append({"date": r.date.isoformat(), "value_cents": eod_val})
            else:
                # approximate from cumulative realized at that point
                equity_curve.append({"date": r.date.isoformat(), "value_cents": capital_cents})

        # top 3 watchlist
        watchlist_top3 = []
        if allocation:
            wl_rows = db.query(BotWatchlist).filter(
                BotWatchlist.profile_id == profile.id,
                BotWatchlist.status.in_(["watching", "pending_entry", "active"])
            ).order_by(BotWatchlist.score.desc()).limit(3).all()

            for wl in wl_rows:
                # top_reason: pull the highest-weight reason from reasons jsonb
                top_reason = ""
                if wl.reasons:
                    top_key = max(wl.reasons, key=lambda k: wl.reasons[k])
                    top_reason = f"{top_key.replace('_', ' ').title()}: {wl.reasons[top_key]:.2f}"[:32]
                watchlist_top3.append({
                    "rank": wl.rank or 0,
                    "symbol": wl.symbol,
                    "score": round(wl.score, 2),
                    "top_reason": top_reason or "—"
                })

        # helpers for display strings
        def fmt_cents(cents):
            if cents is None:
                return "—"
            sign = "+" if cents >= 0 else "-"
            return f"{sign}${abs(cents)/100:,.2f}"

        def fmt_pct(pct):
            if pct is None:
                return "—"
            sign = "+" if pct >= 0 else ""
            return f"{sign}{pct*100:.2f}%"

        def tone(val):
            if val is None:
                return "neutral"
            return "positive" if val >= 0 else "negative"

        card = {
            "profile": profile.name,
            "status": status,
            "description": profile.description or "",
            "asset_class": profile.asset_class,
            "cadence_display": (profile.config_json or {}).get("cadence", ""),
            "paused_reason": allocation.paused_reason if allocation else None,
            "metrics": {
                "portfolio_value": {
                    "value_cents": portfolio_value_cents,
                    "display": f"${portfolio_value_cents/100:,.2f}"
                },
                "today_pnl": {
                    "value_cents": today_pnl_cents,
                    "pct": today_pnl_pct,
                    "display": f"{fmt_cents(today_pnl_cents)} ({fmt_pct(today_pnl_pct)})",
                    "tone": tone(today_pnl_cents)
                },
                "daily_pnl_avg_7d": {
                    "value_cents": daily_pnl_avg_7d_cents,
                    "display": fmt_cents(daily_pnl_avg_7d_cents)
                },
                "daily_pnl_avg_30d": {
                    "value_cents": daily_pnl_avg_30d_cents,
                    "display": fmt_cents(daily_pnl_avg_30d_cents)
                },
                "return_30d": {
                    "pct": return_30d_pct,
                    "display": fmt_pct(return_30d_pct),
                    "tone": tone(return_30d_pct)
                },
                "return_all_time": {
                    "pct": return_all_time_pct,
                    "display": fmt_pct(return_all_time_pct),
                    "tone": tone(return_all_time_pct)
                },
                "sharpe_30d": {
                    "value": sharpe_30d,
                    "display": str(sharpe_30d) if sharpe_30d is not None else "—"
                },
                "win_rate_30d": {
                    "pct": win_rate_pct,
                    "wins": wins,
                    "losses": losses,
                    "display": f"{win_rate_pct*100:.0f}% ({wins}W / {losses}L)" if win_rate_pct is not None else "—"
                },
                "open_positions": {
                    "count": open_positions_count
                },
                "capital_allocated": {
                    "pct": capital_pct,
                    "display": f"{capital_pct}%"
                }
            },
            "equity_curve_30d": equity_curve,
            "watchlist_top_3": watchlist_top3,
            "user_card_config": allocation.card_config if allocation and allocation.card_config else {
                "visible_metrics": [
                    "portfolio_value", "today_pnl", "daily_pnl_avg_7d",
                    "return_30d", "return_all_time", "sharpe_30d",
                    "open_positions", "win_rate_30d", "capital_allocated"
                ],
                "show_equity_curve": True,
                "show_watchlist": True,
                "pnl_avg_window": "7d",
                "density": "standard"
            }
        }
        result.append(card)

    _cards_cache[user_id] = {"data": result, "ts": now}
    return result


# ── PATCH /api/bots/{profile_name}/card-config ────────────────────────────────

@router.patch("/{profile_name}/card-config")
def update_card_config(
    profile_name: str,
    data: dict = Body(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Save per-card customization to BotAllocation.card_config"""
    profile = db.query(BotProfile).filter(BotProfile.name == profile_name).first()
    if not profile:
        raise HTTPException(404)
    allocation = db.query(BotAllocation).filter(
        BotAllocation.profile_id == profile.id,
        BotAllocation.user_id == current_user.id
    ).first()
    if not allocation:
        raise HTTPException(404, "No allocation found")

    # Merge with existing config
    existing = allocation.card_config or {}
    existing.update(data)
    allocation.card_config = existing
    db.commit()

    # Invalidate cache
    _cards_cache.pop(current_user.id, None)

    return {"status": "saved", "card_config": existing}


# ── PATCH /api/bots/cards/bulk-config ────────────────────────────────────────

@router.patch("/cards/bulk-config")
def bulk_update_card_config(
    data: dict = Body(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Apply same card config to all user's allocations"""
    allocations = db.query(BotAllocation).filter(
        BotAllocation.user_id == current_user.id
    ).all()
    for alloc in allocations:
        existing = alloc.card_config or {}
        existing.update(data)
        alloc.card_config = existing
    db.commit()
    _cards_cache.pop(current_user.id, None)
    return {"status": "saved", "updated": len(allocations)}


# ── GET /api/bots/{profile_name} ─────────────────────────────────────────────

@router.get("/{profile_name}")
def get_bot(
    profile_name: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Single bot detail — profile config + user's allocation + recent signals + positions."""
    profile = db.query(BotProfile).filter(BotProfile.name == profile_name).first()
    if not profile:
        raise HTTPException(404, f"Bot profile '{profile_name}' not found")

    allocation = (
        db.query(BotAllocation)
        .filter(
            BotAllocation.user_id == current_user.id,
            BotAllocation.profile_id == profile.id,
        )
        .first()
    )

    recent_signals: list[dict] = []
    positions: list[dict] = []
    has_real_data = False

    if allocation:
        recent_signals = [
            _signal_to_dict(s)
            for s in db.query(BotSignal)
            .filter(BotSignal.allocation_id == allocation.id)
            .order_by(BotSignal.ts.desc())
            .limit(20)
            .all()
        ]
        positions = [
            _position_to_dict(p)
            for p in db.query(BotPosition)
            .filter(
                BotPosition.allocation_id == allocation.id,
                BotPosition.closed_at.is_(None),
            )
            .all()
        ]
        has_real_data = len(positions) > 0

    from app.core.canonical import compute_bot_snapshot

    row = _profile_to_dict(profile, allocation)
    row["recent_signals"] = recent_signals
    row["display_name"] = _DISPLAY_NAMES.get(profile.name, profile.name.replace("_", " ").title())

    if allocation is not None:
        snap = compute_bot_snapshot(allocation, profile, db)
        row["demo"] = False
        row["return_30d_pct"] = snap.return_30d_pct
        row["today_pnl_usd"] = round(snap.today_pnl_cents / 100, 2)
        row["open_positions"] = snap.open_positions if snap.open_positions else positions
        row["open_positions_count"] = snap.open_positions_count
        row["portfolio_value_cents"] = snap.portfolio_value_cents
        row["all_time_return_pct"] = snap.all_time_return_pct
        row["today_pnl_pct"] = snap.today_pnl_pct
        row["win_rate_pct"] = snap.sharpe_30d  # TODO: wire real win rate
        row["equity_curve"] = snap.equity_curve
    else:
        row["demo"] = True
        row["return_30d_pct"] = _demo_30d_return(profile.name)
        row["today_pnl_usd"] = _demo_today_pnl(profile.name)
        row["open_positions"] = _demo_positions(profile.name, profile.asset_class)
        row["open_positions_count"] = len(row["open_positions"])
        row["portfolio_value_cents"] = None
        row["all_time_return_pct"] = None

    return row


# ── POST /api/bots/allocate — flat endpoint for custom-bot wizard ─────────────

@router.post("/allocate")
def allocate_custom_bot(
    body: CustomBotAllocateBody,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Create or update a BotAllocation for a custom bot by name.
    Called by the Custom Bot Builder wizard after the user clicks Deploy.
    Creates a BotProfile stub if one doesn't exist yet.
    """
    now = datetime.now(timezone.utc)

    # Normalise profile name: lowercase, underscores
    profile_name = body.name.lower().replace(" ", "_").replace("-", "_")[:50]

    profile = db.query(BotProfile).filter(BotProfile.name == profile_name).first()
    if not profile:
        profile = BotProfile(
            name=profile_name,
            asset_class="stocks",
            config_json={
                "description": body.description,
                "risk_profile": body.riskProfile,
                "capital_pct": body.capitalPct,
                "custom": True,
            },
        )
        db.add(profile)
        db.flush()

    existing = (
        db.query(BotAllocation)
        .filter(
            BotAllocation.user_id == current_user.id,
            BotAllocation.profile_id == profile.id,
        )
        .first()
    )

    if existing:
        existing.capital_pct = body.capitalPct
        existing.risk_profile = body.riskProfile
        existing.updated_at = now
        db.commit()
        db.refresh(existing)
        return {"allocation_id": existing.id, "bot_name": profile_name, "created": False}
    else:
        alloc = BotAllocation(
            user_id=current_user.id,
            profile_id=profile.id,
            capital_pct=body.capitalPct,
            risk_profile=body.riskProfile,
            paper_mode=True,
            enabled=True,
            created_at=now,
            updated_at=now,
        )
        db.add(alloc)
        db.commit()
        db.refresh(alloc)
        return {"allocation_id": alloc.id, "bot_name": profile_name, "created": True}


# ── POST /api/bots/{profile_name}/allocate ────────────────────────────────────

@router.post("/{profile_name}/allocate")
def allocate_bot(
    profile_name: str,
    body: AllocateBody,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Create or update a BotAllocation for the current user."""
    # Paper mode gate
    if not body.paper_mode:
        if os.getenv("RIA_REGISTERED", "false").lower() != "true":
            raise HTTPException(403, "Live trading not available; RIA registration pending")

    profile = db.query(BotProfile).filter(BotProfile.name == profile_name).first()
    if not profile:
        raise HTTPException(404, f"Bot profile '{profile_name}' not found")

    existing = (
        db.query(BotAllocation)
        .filter(
            BotAllocation.user_id == current_user.id,
            BotAllocation.profile_id == profile.id,
        )
        .first()
    )

    now = datetime.now(timezone.utc)
    if existing:
        existing.capital_pct = body.capital_pct
        existing.risk_profile = body.risk_profile
        existing.paper_mode = body.paper_mode
        existing.enabled = body.enabled
        existing.updated_at = now
        db.commit()
        db.refresh(existing)
        return {"allocation": _allocation_to_dict(existing), "created": False}
    else:
        alloc = BotAllocation(
            user_id=current_user.id,
            profile_id=profile.id,
            capital_pct=body.capital_pct,
            risk_profile=body.risk_profile,
            paper_mode=body.paper_mode,
            enabled=body.enabled,
            created_at=now,
            updated_at=now,
        )
        db.add(alloc)
        db.commit()
        db.refresh(alloc)
        return {"allocation": _allocation_to_dict(alloc), "created": True}


# ── GET /api/bots/{profile_name}/backtest ─────────────────────────────────────

@router.get("/{profile_name}/backtest")
def get_backtest(
    profile_name: str,
    start: str = "2019-01-01",
    end: str = "2024-01-01",
    capital: float = 100_000,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Run (demo) backtest for a bot profile.

    Returns a full BacktestResult with equity curve, Sharpe, Sortino,
    Calmar, max drawdown, win rate, profit factor, Monte Carlo bounds,
    and beta-vs-SPY.  Currently deterministic demo data — full walk-forward
    implementation requires POLYGON_API_KEY.

    Query params:
        start: ISO date string for backtest start (default 2019-01-01).
        end: ISO date string for backtest end (default 2024-01-01).
        capital: Starting capital in USD (default 100000).
    """
    import dataclasses
    from pathlib import Path

    import yaml

    from strategy_lab.core.backtester import run_backtest

    profile = db.query(BotProfile).filter(BotProfile.name == profile_name).first()
    if not profile:
        raise HTTPException(404, f"Bot profile '{profile_name}' not found")

    # Load YAML profile config for stop/target percentages
    profiles_dir = (
        Path(__file__).parent.parent.parent.parent / "strategy_lab" / "profiles"
    )
    yaml_file = profiles_dir / f"{profile_name}.yaml"
    config: dict = {}
    if yaml_file.exists():
        try:
            config = yaml.safe_load(yaml_file.read_text()) or {}
        except Exception:
            config = {}

    result = run_backtest(profile_name, config, start, end, capital)
    return dataclasses.asdict(result)


# ── GET /api/bots/{profile_name}/positions ────────────────────────────────────

@router.get("/{profile_name}/positions")
def get_positions(
    profile_name: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return open positions for the user's allocation of this bot."""
    profile = db.query(BotProfile).filter(BotProfile.name == profile_name).first()
    if not profile:
        raise HTTPException(404, f"Bot profile '{profile_name}' not found")

    allocation = (
        db.query(BotAllocation)
        .filter(
            BotAllocation.user_id == current_user.id,
            BotAllocation.profile_id == profile.id,
        )
        .first()
    )
    if not allocation:
        return {"positions": _demo_positions(profile.name, profile.asset_class), "demo": True}

    positions = (
        db.query(BotPosition)
        .filter(
            BotPosition.allocation_id == allocation.id,
            BotPosition.closed_at.is_(None),
        )
        .all()
    )
    if not positions:
        return {"positions": _demo_positions(profile.name, profile.asset_class), "demo": True}

    return {"positions": [_position_to_dict(p) for p in positions], "demo": False}


# ── GET /api/bots/{profile_name}/trades ───────────────────────────────────────

@router.get("/{profile_name}/trades")
def get_trades(
    profile_name: str,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return recent trades for the user's bot allocation."""
    profile = db.query(BotProfile).filter(BotProfile.name == profile_name).first()
    if not profile:
        raise HTTPException(404, f"Bot profile '{profile_name}' not found")

    allocation = (
        db.query(BotAllocation)
        .filter(
            BotAllocation.user_id == current_user.id,
            BotAllocation.profile_id == profile.id,
        )
        .first()
    )
    if not allocation:
        return {"trades": [], "demo": True}

    trades = (
        db.query(BotTrade)
        .filter(BotTrade.allocation_id == allocation.id)
        .order_by(BotTrade.ts.desc())
        .limit(limit)
        .all()
    )
    return {"trades": [_trade_to_dict(t) for t in trades], "demo": False}


# ── GET /api/bots/{profile_name}/signals ──────────────────────────────────────

@router.get("/{profile_name}/signals")
def get_signals(
    profile_name: str,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return recent signals for the user's bot allocation."""
    profile = db.query(BotProfile).filter(BotProfile.name == profile_name).first()
    if not profile:
        raise HTTPException(404, f"Bot profile '{profile_name}' not found")

    allocation = (
        db.query(BotAllocation)
        .filter(
            BotAllocation.user_id == current_user.id,
            BotAllocation.profile_id == profile.id,
        )
        .first()
    )
    if not allocation:
        return {"signals": [], "demo": True}

    signals = (
        db.query(BotSignal)
        .filter(BotSignal.allocation_id == allocation.id)
        .order_by(BotSignal.ts.desc())
        .limit(limit)
        .all()
    )
    return {"signals": [_signal_to_dict(s) for s in signals], "demo": False}


# ── GET /api/bots/{profile_name}/watchlist ────────────────────────────────────

@router.get("/{profile_name}/watchlist")
def get_watchlist(
    profile_name: str,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return the BotWatchlist for a given profile, sorted by score desc."""
    profile = db.query(BotProfile).filter(BotProfile.name == profile_name).first()
    if not profile:
        raise HTTPException(404, f"Bot profile '{profile_name}' not found")

    rows = (
        db.query(BotWatchlist)
        .filter(
            BotWatchlist.profile_id == profile.id,
            BotWatchlist.status == "active",
        )
        .order_by(BotWatchlist.score.desc())
        .limit(limit)
        .all()
    )
    return {
        "profile_name": profile_name,
        "watchlist": [
            {
                "id": r.id,
                "symbol": r.symbol,
                "score": r.score,
                "rank": r.rank,
                "reasons": r.reasons,
                "status": r.status,
                "added_at": r.added_at.isoformat() if r.added_at else None,
                "last_evaluated_at": (
                    r.last_evaluated_at.isoformat() if r.last_evaluated_at else None
                ),
            }
            for r in rows
        ],
        "count": len(rows),
    }


# ── GET /api/bots/{profile_name}/health ───────────────────────────────────────

@router.get("/{profile_name}/health")
def get_health(
    profile_name: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return the latest BotHealth record for the user's allocation of this bot."""
    profile = db.query(BotProfile).filter(BotProfile.name == profile_name).first()
    if not profile:
        raise HTTPException(404, f"Bot profile '{profile_name}' not found")

    allocation = (
        db.query(BotAllocation)
        .filter(
            BotAllocation.user_id == current_user.id,
            BotAllocation.profile_id == profile.id,
        )
        .first()
    )
    if not allocation:
        return {"health": None, "message": "No allocation found for this profile"}

    health = (
        db.query(BotHealth)
        .filter(BotHealth.allocation_id == allocation.id)
        .order_by(BotHealth.date.desc())
        .first()
    )
    if not health:
        return {
            "allocation_id": allocation.id,
            "health": None,
            "message": "No health records yet",
        }
    return {
        "allocation_id": allocation.id,
        "health": {
            "id": health.id,
            "date": health.date.isoformat() if health.date else None,
            "live_sharpe_30d": health.live_sharpe_30d,
            "backtest_sharpe": health.backtest_sharpe,
            "divergence_sigma": health.divergence_sigma,
            "paused_by_health": health.paused_by_health,
            "strategies_disabled": health.strategies_disabled,
            "heartbeat_ok": health.heartbeat_ok,
            "notes": health.notes,
        },
    }


# ── POST /api/bots/waitlist/{profile_name} ────────────────────────────────────

@router.post("/waitlist/{profile_name}")
def join_waitlist(
    profile_name: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Add the current user to the GoLive waitlist for a bot profile."""
    profile = db.query(BotProfile).filter(BotProfile.name == profile_name).first()
    if not profile:
        raise HTTPException(404, f"Bot profile '{profile_name}' not found")

    existing = (
        db.query(GoLiveWaitlist)
        .filter(
            GoLiveWaitlist.user_id == current_user.id,
            GoLiveWaitlist.bot_profile_id == profile.id,
        )
        .first()
    )
    if existing:
        if existing.opted_out_at:
            # Re-join after opt-out
            existing.opted_out_at = None
            existing.joined_at = datetime.now(timezone.utc)
            db.commit()
            return {"status": "rejoined", "joined_at": existing.joined_at.isoformat()}
        return {"status": "already_joined", "joined_at": existing.joined_at.isoformat()}

    entry = GoLiveWaitlist(
        user_id=current_user.id,
        bot_profile_id=profile.id,
        joined_at=datetime.now(timezone.utc),
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return {"status": "joined", "joined_at": entry.joined_at.isoformat()}


# ── DELETE /api/bots/waitlist/{profile_name} ──────────────────────────────────

@router.delete("/waitlist/{profile_name}")
def leave_waitlist(
    profile_name: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Opt the current user out of the GoLive waitlist."""
    profile = db.query(BotProfile).filter(BotProfile.name == profile_name).first()
    if not profile:
        raise HTTPException(404, f"Bot profile '{profile_name}' not found")

    existing = (
        db.query(GoLiveWaitlist)
        .filter(
            GoLiveWaitlist.user_id == current_user.id,
            GoLiveWaitlist.bot_profile_id == profile.id,
            GoLiveWaitlist.opted_out_at.is_(None),
        )
        .first()
    )
    if not existing:
        raise HTTPException(404, "Not on waitlist for this bot profile")

    existing.opted_out_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "opted_out"}


# ── POST /api/bots/migrate-legacy ─────────────────────────────────────────────

@router.post("/migrate-legacy")
def migrate_legacy_positions(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    One-shot migration: copies open positions and candidates from the old
    strategy_trades table into stock_swing / crypto_swing BotPosition /
    BotSignal rows. Also seeds BotAllocations if they don't exist yet.
    Safe to call multiple times — skips symbols already migrated.
    """
    from app.db.models.strategy import StrategyTrade
    from app.db.models.watchlist import WatchlistItem, Watchlist

    now = datetime.now(timezone.utc)
    stats = {"positions_migrated": 0, "signals_migrated": 0, "already_existed": 0}

    # Map asset_class → bot profile name
    PROFILE_MAP = {
        "equity": "stock_swing",
        "stock": "stock_swing",
        "crypto": "crypto_swing",
    }

    for asset_class, bot_name in [("equity", "stock_swing"), ("crypto", "crypto_swing")]:
        profile = db.query(BotProfile).filter(BotProfile.name == bot_name).first()
        if not profile:
            continue

        # Get or create BotAllocation for this user + profile
        allocation = (
            db.query(BotAllocation)
            .filter(
                BotAllocation.user_id == current_user.id,
                BotAllocation.profile_id == profile.id,
            )
            .first()
        )
        if not allocation:
            allocation = BotAllocation(
                user_id=current_user.id,
                profile_id=profile.id,
                capital_pct=15.0,
                risk_profile="standard",
                paper_mode=True,
                go_live_requested=False,
                enabled=True,
                created_at=now,
                updated_at=now,
            )
            db.add(allocation)
            db.flush()  # get allocation.id

        # Existing migrated symbols (avoid dupes)
        existing_symbols = {
            p.symbol
            for p in db.query(BotPosition)
            .filter(BotPosition.allocation_id == allocation.id, BotPosition.closed_at.is_(None))
            .all()
        }
        existing_signal_symbols = {
            s.symbol
            for s in db.query(BotSignal)
            .filter(BotSignal.allocation_id == allocation.id)
            .all()
        }

        # ── Open positions ────────────────────────────────────────────────────
        open_trades = (
            db.query(StrategyTrade)
            .filter(
                StrategyTrade.status == "open",
                StrategyTrade.asset_class.in_([asset_class, "equity" if asset_class == "stock" else asset_class]),
            )
            .all()
        )
        for t in open_trades:
            if t.symbol in existing_symbols:
                stats["already_existed"] += 1
                continue
            avg_cost_cents = int(round(t.entry_price * 100))
            pos = BotPosition(
                allocation_id=allocation.id,
                symbol=t.symbol,
                qty=t.shares,
                avg_cost_cents=avg_cost_cents,
                opened_at=t.entry_date if t.entry_date else now,
                closed_at=None,
                exit_reason=None,
                is_paper=True,
            )
            db.add(pos)
            existing_symbols.add(t.symbol)
            stats["positions_migrated"] += 1

        # ── Candidates → BotSignal (buy) ──────────────────────────────────────
        candidates = (
            db.query(StrategyTrade)
            .filter(
                StrategyTrade.status == "candidate",
                StrategyTrade.asset_class.in_([asset_class, "equity" if asset_class == "stock" else asset_class]),
            )
            .all()
        )
        for c in candidates:
            if c.symbol in existing_signal_symbols:
                stats["already_existed"] += 1
                continue
            sig = BotSignal(
                allocation_id=allocation.id,
                ts=c.candidate_since if c.candidate_since else now,
                symbol=c.symbol,
                side="buy",
                confidence=0.7,
                size_hint=None,
                reason=f"Migrated from legacy strategy lab ({c.preset_key})",
                strategy=c.preset_key,
            )
            db.add(sig)
            existing_signal_symbols.add(c.symbol)
            stats["signals_migrated"] += 1

    db.commit()
    return {
        "status": "ok",
        "migrated": stats,
        "message": (
            f"Migrated {stats['positions_migrated']} positions and "
            f"{stats['signals_migrated']} watchlist signals into stock_swing / crypto_swing. "
            f"{stats['already_existed']} already existed and were skipped."
        ),
    }


# ── GET /api/bots/dashboard-health ───────────────────────────────────────────

@router.get("/dashboard-health")
def get_dashboard_health(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """System health summary: active vs paused allocations for the current user."""
    allocs = (
        db.query(BotAllocation)
        .filter(BotAllocation.user_id == current_user.id)
        .all()
    )

    active_ids = [a.profile_id for a in allocs if a.enabled]
    paused_ids = [a for a in allocs if not a.enabled]

    # Resolve paused bot names
    paused_bots: list[dict] = []
    if paused_ids:
        paused_profiles = (
            db.query(BotProfile)
            .filter(BotProfile.id.in_([a.profile_id for a in paused_ids]))
            .all()
        )
        profile_name_map = {p.id: p for p in paused_profiles}
        for a in paused_ids:
            p = profile_name_map.get(a.profile_id)
            if p:
                paused_bots.append({
                    "name": _DISPLAY_NAMES.get(p.name, p.name.replace("_", " ").title()),
                    "reason": a.paused_reason or "manually paused",
                })

    bots_total = len(allocs)
    bots_active = len(active_ids)
    bots_paused = len(paused_ids)

    if bots_paused > 0:
        status = "warn"
        message = f"{bots_paused} bot{'s' if bots_paused > 1 else ''} paused"
    elif bots_total == 0:
        status = "warn"
        message = "No bots allocated yet"
    else:
        status = "ok"
        message = "All systems normal"

    return {
        "status": status,
        "message": message,
        "bots_active": bots_active,
        "bots_paused": bots_paused,
        "bots_total": bots_total,
        "paused_bots": paused_bots,
    }


# ── GET /api/bots/signals/recent ─────────────────────────────────────────────

@router.get("/signals/recent")
def get_recent_signals(
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Cross-bot recent signals for the current user, ordered by ts DESC."""
    allocs = (
        db.query(BotAllocation)
        .filter(BotAllocation.user_id == current_user.id)
        .all()
    )
    if not allocs:
        return {"signals": []}

    alloc_ids = [a.id for a in allocs]

    # Build profile lookups
    profile_ids = list({a.profile_id for a in allocs})
    profiles = db.query(BotProfile).filter(BotProfile.id.in_(profile_ids)).all()
    profile_map = {p.id: p for p in profiles}
    alloc_profile: dict[int, BotProfile] = {
        a.id: profile_map[a.profile_id]
        for a in allocs
        if a.profile_id in profile_map
    }

    signals = (
        db.query(BotSignal)
        .filter(BotSignal.allocation_id.in_(alloc_ids))
        .order_by(BotSignal.ts.desc())
        .limit(max(1, min(limit, 100)))
        .all()
    )

    result = []
    for s in signals:
        profile = alloc_profile.get(s.allocation_id)
        if not profile:
            continue
        bot_name = profile.name
        display = _DISPLAY_NAMES.get(bot_name, bot_name.replace("_", " ").title())
        result.append({
            "ts": s.ts.isoformat() if s.ts else None,
            "bot_name": bot_name,
            "display_name": display,
            "symbol": s.symbol,
            "side": s.side,
            "confidence": s.confidence,
            "reason": s.reason or "",
            "strategy": s.strategy or "",
        })

    return {"signals": result}


# ── GET /api/bots/watchlist/movers ────────────────────────────────────────────

@router.get("/watchlist/movers")
def get_watchlist_movers(
    limit: int = 4,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Top movers from the user's bot watchlists, sorted by score DESC."""
    allocs = (
        db.query(BotAllocation)
        .filter(BotAllocation.user_id == current_user.id)
        .all()
    )
    if not allocs:
        return {"movers": []}

    profile_ids = list({a.profile_id for a in allocs})

    # Build a mapping from profile_id → portfolio asset_class
    from app.db.models.bots import StrategyPortfolio
    portfolio_map: dict[int, str] = {}
    port_allocs = [a for a in allocs if a.portfolio_id]
    if port_allocs:
        portfolio_ids = list({a.portfolio_id for a in port_allocs if a.portfolio_id})
        portfolios = (
            db.query(StrategyPortfolio)
            .filter(StrategyPortfolio.id.in_(portfolio_ids))
            .all()
        )
        port_id_to_name = {p.id: p.name for p in portfolios}
        for a in port_allocs:
            if a.portfolio_id and a.portfolio_id in port_id_to_name:
                portfolio_map[a.profile_id] = port_id_to_name[a.portfolio_id]

    wl_rows = (
        db.query(BotWatchlist)
        .filter(
            BotWatchlist.profile_id.in_(profile_ids),
            BotWatchlist.status.in_(["active", "watching", "pending_entry"]),
        )
        .order_by(BotWatchlist.score.desc())
        .all()
    )

    # Deduplicate by symbol, keep highest score
    seen: dict[str, dict] = {}
    for row in wl_rows:
        sym = row.symbol
        portfolio_name = portfolio_map.get(row.profile_id, "")
        if sym not in seen or (row.score or 0) > seen[sym]["score"]:
            seen[sym] = {
                "symbol": sym,
                "change_pct": 0.0,   # no live price data in paper mode
                "portfolio": portfolio_name,
                "status": row.status,
                "score": round(row.score or 0, 3),
            }

    movers = sorted(seen.values(), key=lambda x: -x["score"])[: max(1, min(limit, 20))]
    return {"movers": movers}


# ── GET /api/bots/catalysts ───────────────────────────────────────────────────

@router.get("/catalysts")
def get_catalysts(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return upcoming catalyst events for symbols on the user's watchlists."""
    allocs = (
        db.query(BotAllocation)
        .filter(BotAllocation.user_id == current_user.id)
        .all()
    )
    if not allocs:
        return []

    profile_ids = list({a.profile_id for a in allocs})
    wl_rows = (
        db.query(BotWatchlist)
        .filter(
            BotWatchlist.profile_id.in_(profile_ids),
            BotWatchlist.status.in_(["active", "watching", "pending_entry"]),
        )
        .order_by(BotWatchlist.score.desc())
        .limit(30)
        .all()
    )

    # Build lightweight catalyst stubs from watchlist — real earnings data would
    # come from a market-data feed; here we surface what we know from signals.
    now = datetime.now(timezone.utc)
    events: list[dict] = []
    seen_syms: set[str] = set()
    for row in wl_rows:
        sym = row.symbol
        if sym in seen_syms:
            continue
        seen_syms.add(sym)
        # Use last_evaluated_at as a proxy event date if available
        event_ts = row.last_evaluated_at or row.added_at or now
        events.append({
            "id": row.id,
            "event_type": "watchlist",
            "symbol": sym,
            "event_ts": event_ts.isoformat() if event_ts else now.isoformat(),
            "description": f"{sym} on watchlist (score {row.score:.2f})" if row.score else f"{sym} on watchlist",
        })

    return events


# ── GET /api/bots/pending-reviews ─────────────────────────────────────────────

@router.get("/pending-reviews")
def get_pending_reviews(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return borderline signals (confidence 0.5-0.7) pending user review."""
    allocs = (
        db.query(BotAllocation)
        .filter(BotAllocation.user_id == current_user.id)
        .all()
    )
    if not allocs:
        return []

    alloc_ids = [a.id for a in allocs]
    profile_ids = list({a.profile_id for a in allocs})
    profiles = db.query(BotProfile).filter(BotProfile.id.in_(profile_ids)).all()
    profile_map = {p.id: p for p in profiles}
    alloc_profile_name: dict[int, str] = {
        a.id: profile_map[a.profile_id].name
        for a in allocs
        if a.profile_id in profile_map
    }

    # Borderline signals: confidence in [0.5, 0.75)
    signals = (
        db.query(BotSignal)
        .filter(
            BotSignal.allocation_id.in_(alloc_ids),
            BotSignal.confidence >= 0.5,
            BotSignal.confidence < 0.75,
        )
        .order_by(BotSignal.ts.desc())
        .limit(10)
        .all()
    )

    return [
        {
            "id": s.id,
            "bot_name": alloc_profile_name.get(s.allocation_id, "unknown"),
            "symbol": s.symbol,
            "ts": s.ts.isoformat() if s.ts else None,
            "confidence": s.confidence,
            "side": s.side,
            "reason": s.reason or "",
        }
        for s in signals
    ]
