"""Strategy Scout API — per-ticker strategy evaluation and personal setup alerts.

Feature-flagged: set ENABLE_STRATEGY_SCOUT=true in Railway to activate.

Endpoints:
  POST /api/scout/evaluate        — evaluate one (strategy, ticker) pair
  POST /api/scout/scan-ticker     — run all catalog strategies on a ticker
  GET  /api/scout/setups          — list user's active setups
  POST /api/scout/setups          — create a setup
  DELETE /api/scout/setups/{id}   — remove a setup
  GET  /api/scout/signals         — user's fired scout signals
  GET  /api/scout/catalog         — list all available strategies
"""
from __future__ import annotations

import importlib
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies import get_current_user
from strategy_lab.scout_catalog import SCOUT_CATALOG, list_catalog

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/scout", tags=["scout"])

# ── Feature flag guard ─────────────────────────────────────────────────────────

def _scout_enabled() -> None:
    if not os.getenv("ENABLE_STRATEGY_SCOUT", "true").strip().lower() == "true":
        raise HTTPException(status_code=404, detail="Strategy Scout not enabled")


# ── Simple in-process TTL cache for scan-ticker results ───────────────────────

_SCAN_CACHE: dict[str, tuple[float, Any]] = {}
_SCAN_CACHE_TTL = 60  # seconds


def _cache_get(key: str) -> Any | None:
    entry = _SCAN_CACHE.get(key)
    if entry and time.time() - entry[0] < _SCAN_CACHE_TTL:
        return entry[1]
    return None


def _cache_set(key: str, value: Any) -> None:
    _SCAN_CACHE[key] = (time.time(), value)


# ── Bar fetching ──────────────────────────────────────────────────────────────

def _fetch_bars_for_ticker(ticker: str, period: str = "1y") -> list[dict]:
    """Fetch daily OHLCV bars for a single ticker, return as list of bar dicts."""
    from app.screener.runner import _fetch_bars_sync
    try:
        raw = _fetch_bars_sync([ticker], period=period)
        df = raw.get(ticker)
        if df is None or df.empty:
            return []
        return [
            {
                "c": float(row["close"]),
                "o": float(row["open"]),
                "h": float(row["high"]),
                "l": float(row["low"]),
                "v": float(row.get("volume", 0) or 0),
                "ts": row.name.isoformat() if hasattr(row.name, "isoformat") else str(row.name),
            }
            for _, row in df.iterrows()
        ]
    except Exception as exc:
        logger.warning("[scout] bar fetch failed for %s: %s", ticker, exc)
        return []


# ── Strategy runner ───────────────────────────────────────────────────────────

def _run_strategy(strategy_id: str, ticker: str, bars: list[dict]) -> dict | None:
    """Run one strategy against (ticker, bars), return result dict or None."""
    meta = SCOUT_CATALOG.get(strategy_id)
    if not meta:
        return None
    if len(bars) < meta.get("min_bars", 1):
        return None

    try:
        mod = importlib.import_module(meta["module"])
    except ImportError as exc:
        logger.debug("[scout] cannot import %s: %s", meta["module"], exc)
        return None

    signals = []
    try:
        if hasattr(mod, "generate_signals"):
            signals = mod.generate_signals({ticker: bars}, {}, {}) or []
        elif hasattr(mod, "generate_signal"):
            closes = [b["c"] for b in bars]
            sig = mod.generate_signal(ticker, closes)
            if sig:
                signals = [sig]
    except Exception as exc:
        logger.debug("[scout] %s strategy raised: %s", strategy_id, exc)
        return None

    # Pick the signal for our ticker (skip holds)
    sig = next(
        (s for s in signals if s.symbol == ticker and s.side != "hold"),
        next((s for s in signals if s.symbol == ticker), None),
    )
    if not sig:
        return None

    conf = float(sig.confidence or 0)
    side = sig.side or "neutral"
    threshold = meta["confidence_threshold"]

    # Setup quality 0-100
    if side == "hold":
        quality = max(0, int(conf * 40))
    else:
        quality = min(100, int(conf * 100))

    # Entry / stop / target heuristics from bar data
    last_close = bars[-1]["c"] if bars else None
    entry = last_close
    stop = None
    target = None
    if last_close:
        is_buy = side in ("buy", "cover")
        stop = round(last_close * (0.93 if is_buy else 1.07), 4)
        target = round(last_close * (1.15 if is_buy else 0.85), 4)

    return {
        "strategy_id": strategy_id,
        "display_name": meta["display_name"],
        "category": meta["category"],
        "setup_quality": quality,
        "confidence": round(conf, 4),
        "side": side,
        "threshold": threshold,
        "armed": conf >= threshold and side != "hold",
        "entry": entry,
        "stop": stop,
        "target": target,
        "reason": getattr(sig, "reason", "") or "",
        "indicators": {},
    }


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/catalog")
def get_catalog(_: None = Depends(_scout_enabled)):
    return {"strategies": list_catalog()}


@router.post("/evaluate")
def evaluate_setup(
    body: dict = Body(...),
    _: None = Depends(_scout_enabled),
    current_user=Depends(get_current_user),
):
    strategy_id = (body.get("strategy_id") or "").strip()
    ticker = (body.get("ticker") or "").strip().upper()

    if not strategy_id or strategy_id not in SCOUT_CATALOG:
        raise HTTPException(status_code=422, detail="Unknown strategy_id")
    if not ticker:
        raise HTTPException(status_code=422, detail="ticker is required")

    bars = _fetch_bars_for_ticker(ticker)
    if not bars:
        raise HTTPException(status_code=422, detail=f"No bar data found for {ticker}")

    result = _run_strategy(strategy_id, ticker, bars)
    if result is None:
        meta = SCOUT_CATALOG[strategy_id]
        return {
            "strategy_id": strategy_id,
            "display_name": meta["display_name"],
            "category": meta["category"],
            "setup_quality": 0,
            "confidence": 0.0,
            "side": "neutral",
            "threshold": meta["confidence_threshold"],
            "armed": False,
            "entry": bars[-1]["c"] if bars else None,
            "stop": None,
            "target": None,
            "reason": f"Insufficient data or no signal ({len(bars)} bars, need {meta['min_bars']})",
            "indicators": {},
        }
    return result


@router.post("/scan-ticker")
def scan_ticker(
    body: dict = Body(...),
    _: None = Depends(_scout_enabled),
    current_user=Depends(get_current_user),
):
    ticker = (body.get("ticker") or "").strip().upper()
    if not ticker:
        raise HTTPException(status_code=422, detail="ticker is required")

    cached = _cache_get(ticker)
    if cached is not None:
        return cached

    bars = _fetch_bars_for_ticker(ticker)
    if not bars:
        raise HTTPException(status_code=422, detail=f"No bar data found for {ticker}")

    results = []
    for strategy_id in SCOUT_CATALOG:
        r = _run_strategy(strategy_id, ticker, bars)
        if r:
            results.append(r)

    results.sort(key=lambda x: (-x["setup_quality"], -x["confidence"]))
    top10 = results[:10]

    response = {"ticker": ticker, "bar_count": len(bars), "results": top10}
    _cache_set(ticker, response)
    return response


@router.get("/setups")
def get_setups(
    _: None = Depends(_scout_enabled),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.db.models.scout import UserScoutSetup
    rows = (
        db.query(UserScoutSetup)
        .filter(
            UserScoutSetup.user_id == current_user.id,
            UserScoutSetup.status != "deleted",
        )
        .order_by(UserScoutSetup.created_at.desc())
        .all()
    )
    return {
        "setups": [
            {
                "id": r.id,
                "ticker": r.ticker,
                "strategy_id": r.strategy_id,
                "display_name": SCOUT_CATALOG.get(r.strategy_id, {}).get("display_name", r.strategy_id),
                "category": SCOUT_CATALOG.get(r.strategy_id, {}).get("category", ""),
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "last_scanned_at": r.last_scanned_at.isoformat() if r.last_scanned_at else None,
                "last_confidence": r.last_confidence,
                "fired_at": r.fired_at.isoformat() if r.fired_at else None,
            }
            for r in rows
        ]
    }


@router.post("/setups")
def create_setup(
    body: dict = Body(...),
    _: None = Depends(_scout_enabled),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.db.models.scout import UserScoutSetup
    from sqlalchemy.exc import IntegrityError

    ticker = (body.get("ticker") or "").strip().upper()
    strategy_id = (body.get("strategy_id") or "").strip()

    if not ticker:
        raise HTTPException(status_code=422, detail="ticker is required")
    if not strategy_id or strategy_id not in SCOUT_CATALOG:
        raise HTTPException(status_code=422, detail="Unknown strategy_id")

    # Check per-user cap (max 25 active setups)
    active_count = (
        db.query(UserScoutSetup)
        .filter(UserScoutSetup.user_id == current_user.id, UserScoutSetup.status == "active")
        .count()
    )
    if active_count >= 25:
        raise HTTPException(status_code=422, detail="Maximum 25 active setups per user")

    setup = UserScoutSetup(
        user_id=current_user.id,
        ticker=ticker,
        strategy_id=strategy_id,
        status="active",
    )
    db.add(setup)
    try:
        db.commit()
        db.refresh(setup)
    except IntegrityError:
        db.rollback()
        # Already exists — re-activate if paused/fired
        existing = (
            db.query(UserScoutSetup)
            .filter(
                UserScoutSetup.user_id == current_user.id,
                UserScoutSetup.ticker == ticker,
                UserScoutSetup.strategy_id == strategy_id,
            )
            .first()
        )
        if existing and existing.status != "active":
            existing.status = "active"
            existing.fired_at = None
            db.commit()
            setup = existing
        elif existing:
            return {
                "id": existing.id,
                "ticker": existing.ticker,
                "strategy_id": existing.strategy_id,
                "status": existing.status,
                "already_exists": True,
            }

    return {
        "id": setup.id,
        "ticker": setup.ticker,
        "strategy_id": setup.strategy_id,
        "status": setup.status,
        "already_exists": False,
    }


@router.delete("/setups/{setup_id}")
def delete_setup(
    setup_id: int,
    _: None = Depends(_scout_enabled),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.db.models.scout import UserScoutSetup
    setup = db.get(UserScoutSetup, setup_id)
    if not setup or setup.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Setup not found")
    setup.status = "deleted"
    db.commit()
    return {"ok": True}


@router.get("/signals")
def get_signals(
    _: None = Depends(_scout_enabled),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.db.models.scout import UserScoutSignal
    rows = (
        db.query(UserScoutSignal)
        .filter(UserScoutSignal.user_id == current_user.id)
        .order_by(UserScoutSignal.created_at.desc())
        .limit(50)
        .all()
    )
    return {
        "signals": [
            {
                "id": r.id,
                "setup_id": r.setup_id,
                "ticker": r.ticker,
                "strategy_id": r.strategy_id,
                "display_name": SCOUT_CATALOG.get(r.strategy_id, {}).get("display_name", r.strategy_id),
                "side": r.side,
                "confidence": r.confidence,
                "entry_price": r.entry_price,
                "stop_price": r.stop_price,
                "target_price": r.target_price,
                "reason": r.reason,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }
