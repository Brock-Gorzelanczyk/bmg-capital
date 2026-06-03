"""
Strategy Lab — six-bot automated paper trading framework router.

GET  /api/bots                          — list all 6 BotProfiles + user's allocations
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

from fastapi import APIRouter, Depends, HTTPException
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
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bots", tags=["bots"])


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class AllocateBody(BaseModel):
    capital_pct: float = 10.0
    risk_profile: str = "standard"
    paper_mode: bool = True
    enabled: bool = True


# ── Demo data helpers ─────────────────────────────────────────────────────────

_DEMO_SYMBOLS = {
    "stock": ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "V", "UNH"],
    "crypto": ["BTC/USD", "ETH/USD", "SOL/USD", "AVAX/USD", "MATIC/USD"],
}

_DEMO_SIDES = ["buy", "sell"]
_DEMO_STRATEGIES = ["momentum_breakout", "mean_reversion", "rsi_bands", "vwap_reversion", "factor_blend", "dca"]


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
    for _ in range(count):
        sym = rng.choice(symbols)
        entry = round(rng.uniform(50.0, 500.0), 2)
        change_pct = rng.uniform(-5.0, 12.0)
        current = round(entry * (1 + change_pct / 100), 2)
        qty = round(rng.uniform(1.0, 20.0), 4)
        positions.append({
            "symbol": sym,
            "qty": qty,
            "avg_cost": entry,
            "current_price": current,
            "unrealized_pnl": round((current - entry) * qty, 2),
            "unrealized_pnl_pct": round(change_pct, 2),
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
    """List all 6 BotProfiles with user's allocations and demo performance data."""
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

    result = []
    for p in profiles:
        allocation = user_allocations.get(p.id)
        has_real_data = allocation is not None and db.query(BotPosition).filter(
            BotPosition.allocation_id == allocation.id
        ).count() > 0

        row = _profile_to_dict(p, allocation)

        # Inject demo data when no real positions exist
        if not has_real_data:
            row["demo"] = True
            row["return_30d_pct"] = _demo_30d_return(p.name)
            row["today_pnl_usd"] = _demo_today_pnl(p.name)
            row["open_positions"] = _demo_positions(p.name, p.asset_class)
        else:
            row["demo"] = False
            row["return_30d_pct"] = None  # computed from real data in future
            row["today_pnl_usd"] = None
            row["open_positions"] = []

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

    row = _profile_to_dict(profile, allocation)
    row["recent_signals"] = recent_signals

    if not has_real_data:
        row["demo"] = True
        row["return_30d_pct"] = _demo_30d_return(profile.name)
        row["today_pnl_usd"] = _demo_today_pnl(profile.name)
        row["open_positions"] = _demo_positions(profile.name, profile.asset_class)
    else:
        row["demo"] = False
        row["return_30d_pct"] = None
        row["today_pnl_usd"] = None
        row["open_positions"] = positions

    return row


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
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Stub backtest — returns a deterministic demo equity curve and key metrics."""
    profile = db.query(BotProfile).filter(BotProfile.name == profile_name).first()
    if not profile:
        raise HTTPException(404, f"Bot profile '{profile_name}' not found")

    rng = _seeded_rng(profile_name + "_bt")
    equity_curve = _demo_equity_curve(profile_name)
    start_equity = equity_curve[0]["equity"]
    end_equity = equity_curve[-1]["equity"]
    total_return_pct = round((end_equity - start_equity) / start_equity * 100, 2)

    return {
        "profile_name": profile_name,
        "period_days": 30,
        "start_equity": start_equity,
        "end_equity": end_equity,
        "total_return_pct": total_return_pct,
        "sharpe_ratio": round(rng.uniform(0.6, 2.2), 2),
        "max_drawdown_pct": round(rng.uniform(-3.0, -12.0), 2),
        "win_rate_pct": round(rng.uniform(48.0, 65.0), 1),
        "total_trades": rng.randint(15, 80),
        "equity_curve": equity_curve,
        "stub": True,
        "note": "Demo backtest data. Live backtesting engine coming soon.",
    }


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
