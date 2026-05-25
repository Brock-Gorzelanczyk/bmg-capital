from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone, date
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

import yfinance as yf
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.strategy import DailyEquitySnapshot, DailyLog, StrategyTrade
from app.db.models.users import User
from app.db.session import get_db
from app.dependencies import get_current_user
from app.screener.daily_runner import (
    PAPER_PORTFOLIO,
    PRESET_LABELS,
    _check_regime_sync,
    _fetch_bars_sync,
    _get_prices_sync,
    _get_prev_closes_sync,
    run_daily_automation,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/strategy", tags=["strategy"])

# Simple in-memory TTL caches
_price_cache: Dict[FrozenSet[str], Tuple[Dict[str, float], float]] = {}
_regime_cache: Tuple[Any, float] | None = None
_PRICE_TTL = 60.0   # seconds
_REGIME_TTL = 300.0  # seconds


def _get_prices_cached(symbols: List[str]) -> Dict[str, float]:
    if not symbols:
        return {}
    key = frozenset(symbols)
    entry = _price_cache.get(key)
    if entry and time.monotonic() - entry[1] < _PRICE_TTL:
        return entry[0]
    prices = _get_prices_sync(symbols)
    _price_cache[key] = (prices, time.monotonic())
    return prices


async def _get_regime_cached() -> Any:
    global _regime_cache
    if _regime_cache and time.monotonic() - _regime_cache[1] < _REGIME_TTL:
        return _regime_cache[0]
    loop = asyncio.get_running_loop()
    regime = await loop.run_in_executor(None, _check_regime_sync)
    _regime_cache = (regime, time.monotonic())
    return regime


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _enrich_trade(t: StrategyTrade, prices: Dict[str, float], prev_closes: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    current = (prices.get(t.symbol) or t.last_known_price) if t.status in ("open", "candidate") else t.exit_price
    ep = t.exit_price if t.status == "closed" else current
    pnl = ((ep - t.entry_price) * t.shares) if (ep and t.entry_price and t.entry_price > 0 and t.shares) else None
    pnl_pct = ((ep - t.entry_price) / t.entry_price * 100) if (ep and t.entry_price and t.entry_price > 0) else None
    prev_close = (prev_closes or {}).get(t.symbol) if t.status == "open" else None
    day_pnl = round((current - prev_close) * t.shares, 2) if (current and prev_close and t.shares and t.status == "open") else None
    days_held = 0
    if t.status == "candidate" and t.candidate_since:
        days_held = (date.today() - t.candidate_since.date()).days
    elif t.entry_price and t.entry_price > 0:
        end = t.exit_date or _now()
        start = t.entry_date or _now()
        days_held = (end - start).days

    return {
        "id": t.id,
        "preset_key": t.preset_key,
        "preset_label": PRESET_LABELS.get(t.preset_key, t.preset_key),
        "symbol": t.symbol,
        "status": t.status,
        "candidate_since": t.candidate_since.isoformat() if t.candidate_since else None,
        "entry_trigger": t.entry_trigger,
        "entry_date": t.entry_date.isoformat() if t.entry_price and t.entry_price > 0 else None,
        "entry_price": t.entry_price if t.entry_price and t.entry_price > 0 else None,
        "shares": t.shares if t.shares else None,
        "stop_price": t.stop_price if t.stop_price and t.stop_price > 0 else None,
        "target_price": t.target_price if t.target_price and t.target_price > 0 else None,
        "atr": t.atr,
        "risk_dollars": t.risk_dollars,
        "current_price": current,
        "exit_date": t.exit_date.isoformat() if t.exit_date else None,
        "exit_price": t.exit_price,
        "exit_reason": t.exit_reason,
        "pnl": round(pnl, 2) if pnl is not None else None,
        "pnl_pct": round(pnl_pct, 2) if pnl_pct is not None else None,
        "day_pnl": day_pnl,
        "days_held": days_held,
    }


def _settle_open_trades(trades: List[StrategyTrade], prices: Dict[str, float], db: Session) -> None:
    """Apply stop/target/time exits to open positions (read-time settlement)."""
    now = _now()
    today = date.today()
    dirty = False
    for t in trades:
        if t.status != "open" or not t.entry_price or t.entry_price <= 0:
            continue
        current = prices.get(t.symbol)
        if current:
            # Persist the last seen live price so weekend/closed-market views stay accurate
            if t.last_known_price != current:
                t.last_known_price = current
                dirty = True
            days_held = (today - t.entry_date.date()).days if t.entry_date else 0
            reason = None
            if current <= t.stop_price:
                reason = "stop"
            elif current >= t.target_price:
                reason = "target"
            elif days_held >= 30:
                reason = "time"
            if reason:
                t.status = "closed"
                t.exit_price = current
                t.exit_date = now
                t.exit_reason = reason
                dirty = True
            db.add(t)
    if dirty:
        db.commit()


@router.get("/trades")
async def get_trades(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    trades = db.execute(
        select(StrategyTrade)
        .where(StrategyTrade.status.in_(["open", "closed"]))
        .where(StrategyTrade.user_id == current_user.id)
        .order_by(StrategyTrade.entry_date.desc())
    ).scalars().all()

    open_syms = [t.symbol for t in trades if t.status == "open"]
    loop = asyncio.get_running_loop()
    prices = await loop.run_in_executor(None, lambda: _get_prices_cached(open_syms))

    _settle_open_trades([t for t in trades if t.status == "open"], prices, db)

    enriched = [_enrich_trade(t, prices) for t in trades]
    return {"trades": enriched}


@router.get("/candidates")
async def get_candidates(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    candidates = db.execute(
        select(StrategyTrade)
        .where(StrategyTrade.status == "candidate")
        .where(StrategyTrade.user_id == current_user.id)
        .order_by(StrategyTrade.candidate_since.desc())
    ).scalars().all()

    syms = [t.symbol for t in candidates]
    loop = asyncio.get_running_loop()
    prices = await loop.run_in_executor(None, lambda: _get_prices_cached(syms))

    return {"candidates": [_enrich_trade(t, prices) for t in candidates]}


@router.get("/summary")
async def get_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    all_trades = db.execute(
        select(StrategyTrade).where(StrategyTrade.user_id == current_user.id)
    ).scalars().all()

    open_trades = [t for t in all_trades if t.status == "open"]
    open_syms = [t.symbol for t in open_trades]

    loop = asyncio.get_running_loop()
    prices = await loop.run_in_executor(None, lambda: _get_prices_cached(open_syms))
    prev_closes = await loop.run_in_executor(None, lambda: _get_prev_closes_sync(open_syms))
    _settle_open_trades(open_trades, prices, db)

    closed = [
        t for t in all_trades
        if t.status == "closed"
        and t.exit_reason not in ("expired",)
        and t.entry_price and t.entry_price > 0
        and t.exit_price
    ]
    candidates_count = sum(1 for t in all_trades if t.status == "candidate")
    open_count = sum(1 for t in all_trades if t.status == "open")

    wins = [t for t in closed if t.exit_price > t.entry_price]
    losses = [t for t in closed if t.exit_price <= t.entry_price]
    realized_pnl = sum((t.exit_price - t.entry_price) * t.shares for t in closed)
    open_pnl = sum(
        ((prices.get(t.symbol) or t.last_known_price or t.entry_price) - t.entry_price) * t.shares
        for t in open_trades
        if t.entry_price and t.entry_price > 0 and t.shares
    )
    day_pnl = sum(
        ((prices.get(t.symbol) or t.last_known_price or 0) - prev_closes[t.symbol]) * t.shares
        for t in open_trades
        if t.entry_price and t.entry_price > 0 and t.shares and t.symbol in prev_closes
        and (prices.get(t.symbol) or t.last_known_price)
    )

    avg_win = (sum((t.exit_price - t.entry_price) / t.entry_price * 100 for t in wins) / len(wins)) if wins else 0
    avg_loss = (sum((t.exit_price - t.entry_price) / t.entry_price * 100 for t in losses) / len(losses)) if losses else 0
    expectancy = (
        (len(wins) / len(closed) * avg_win) + (len(losses) / len(closed) * avg_loss)
        if closed else 0
    )

    # Closed P&L history for max drawdown
    pnl_series = []
    running = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in sorted(closed, key=lambda x: x.exit_date or _now()):
        running += (t.exit_price - t.entry_price) * t.shares
        peak = max(peak, running)
        dd = (peak - running) / PAPER_PORTFOLIO * 100 if peak > 0 else 0
        max_dd = max(max_dd, dd)

    # Per-preset stats
    preset_stats: Dict[str, Any] = {}
    for t in closed:
        pk = t.preset_key
        if pk not in preset_stats:
            preset_stats[pk] = {
                "label": PRESET_LABELS.get(pk, pk),
                "trades": 0, "wins": 0, "losses": 0,
                "total_gain": 0.0, "total_loss": 0.0, "total_pnl": 0.0,
            }
        s = preset_stats[pk]
        s["trades"] += 1
        pct = (t.exit_price - t.entry_price) / t.entry_price * 100
        s["total_pnl"] += (t.exit_price - t.entry_price) * t.shares
        if pct > 0:
            s["wins"] += 1
            s["total_gain"] += pct
        else:
            s["losses"] += 1
            s["total_loss"] += pct

    best_preset = max(preset_stats.items(), key=lambda x: x[1]["total_pnl"])[1]["label"] if preset_stats else None

    preset_list = []
    for pk, s in preset_stats.items():
        wr = round(s["wins"] / s["trades"] * 100, 1) if s["trades"] else 0
        preset_list.append({
            "preset_key": pk,
            "preset_label": s["label"],
            "trades": s["trades"],
            "wins": s["wins"],
            "losses": s["losses"],
            "win_rate": wr,
            "avg_win_pct": round(s["total_gain"] / s["wins"], 2) if s["wins"] else 0,
            "avg_loss_pct": round(s["total_loss"] / s["losses"], 2) if s["losses"] else 0,
            "total_pnl": round(s["total_pnl"], 2),
        })

    return {
        "overall": {
            "total_closed": len(closed),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(closed) * 100, 1) if closed else 0,
            "total_pnl": round(realized_pnl, 2),
            "open_pnl": round(open_pnl, 2),
            "day_pnl": round(day_pnl, 2),
            "portfolio_value": round(PAPER_PORTFOLIO + realized_pnl + open_pnl, 2),
            "open_positions": open_count,
            "candidates": candidates_count,
            "best_preset": best_preset,
            "expectancy": round(expectancy, 2),
            "max_drawdown_pct": round(max_dd, 2),
        },
        "by_preset": sorted(preset_list, key=lambda x: -x["total_pnl"]),
    }


@router.get("/log")
async def get_log(
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    entries = db.execute(
        select(DailyLog)
        .where(DailyLog.user_id == current_user.id)
        .order_by(DailyLog.logged_at.desc())
        .limit(limit)
    ).scalars().all()
    return {
        "log": [
            {
                "id": e.id,
                "logged_at": e.logged_at.isoformat(),
                "log_date": e.log_date.isoformat(),
                "event_type": e.event_type,
                "symbol": e.symbol,
                "preset_key": e.preset_key,
                "preset_label": e.preset_label,
                "price": e.price,
                "pnl_pct": e.pnl_pct,
                "notes": e.notes,
                "trade_id": e.trade_id,
            }
            for e in entries
        ]
    }


@router.get("/equity")
async def get_equity(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    snaps = db.execute(
        select(DailyEquitySnapshot)
        .where(DailyEquitySnapshot.user_id == current_user.id)
        .order_by(DailyEquitySnapshot.snapshot_date.asc())
    ).scalars().all()
    return {
        "equity": [
            {
                "date": s.snapshot_date.isoformat(),
                "portfolio_value": s.portfolio_value,
                "realized_pnl": s.realized_pnl,
                "open_pnl": s.open_pnl,
                "open_positions": s.open_positions,
                "candidates": s.candidates,
                "new_entries": s.new_entries,
                "exits_today": s.exits_today,
            }
            for s in snaps
        ],
        "baseline": PAPER_PORTFOLIO,
    }


@router.get("/pnl-calendar")
async def get_pnl_calendar(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return day-by-day P&L data for the calendar view."""
    snaps = db.execute(
        select(DailyEquitySnapshot)
        .where(DailyEquitySnapshot.user_id == current_user.id)
        .order_by(DailyEquitySnapshot.snapshot_date.asc())
    ).scalars().all()

    # Build day_pnl as equity change vs previous TRADING day (skip weekends)
    days = []
    last_trading_value = PAPER_PORTFOLIO
    for s in snaps:
        # isoweekday: 6=Saturday, 7=Sunday — skip non-trading days
        if s.snapshot_date.isoweekday() >= 6:
            continue
        day_pnl = round(s.portfolio_value - last_trading_value, 2)
        day_pnl_pct = round(day_pnl / last_trading_value * 100, 2) if last_trading_value else 0.0
        last_trading_value = s.portfolio_value
        days.append({
            "date": s.snapshot_date.isoformat(),
            "day_pnl": day_pnl,
            "day_pnl_pct": day_pnl_pct,
            "portfolio_value": round(s.portfolio_value, 2),
            "new_entries": s.new_entries,
            "exits_today": s.exits_today,
            "open_positions": s.open_positions,
        })

    # Attach DailyLog trade events per date
    all_logs = db.execute(
        select(DailyLog)
        .where(
            DailyLog.user_id == current_user.id,
            DailyLog.event_type.in_(["entry", "exit", "auto_entry", "auto_exit"]),
        )
        .order_by(DailyLog.log_date.asc(), DailyLog.logged_at.asc())
    ).scalars().all()

    logs_by_date: dict = {}
    for log in all_logs:
        key = log.log_date.isoformat() if hasattr(log.log_date, "isoformat") else str(log.log_date)
        logs_by_date.setdefault(key, []).append({
            "event_type": log.event_type,
            "symbol": log.symbol,
            "preset_label": log.preset_label,
            "price": log.price,
            "pnl_pct": log.pnl_pct,
            "notes": log.notes,
        })

    for d in days:
        d["trades"] = logs_by_date.get(d["date"], [])

    return {"days": days}


@router.get("/regime")
async def get_regime():
    regime = await _get_regime_cached()
    return {"regime": regime}


@router.get("/monitor-status")
async def get_monitor_status():
    """
    Return 24/7 monitor status: last scan time, signals, and current market phase.
    Market status is derived live from the current ET time.
    """
    from app.screener.scheduler import get_monitor_status
    return get_monitor_status()


async def _run_daily_wrapper(user_id: int):
    try:
        logger.info(f"Background run-now starting for user {user_id}...")
        await run_daily_automation(user_id=user_id)
        logger.info(f"Background run-now complete for user {user_id}.")
    except Exception as e:
        logger.error(f"run_daily_automation failed for user {user_id}: {e}", exc_info=True)


@router.post("/run-now")
async def run_now(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    background_tasks.add_task(_run_daily_wrapper, current_user.id)
    return {"ok": True, "message": "Daily run started — check /log in ~2 minutes for results"}


@router.delete("/trades/{trade_id}")
async def close_trade(
    trade_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    trade = db.get(StrategyTrade, trade_id)
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    if trade.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your trade")
    if trade.status == "closed":
        raise HTTPException(status_code=400, detail="Trade already closed")

    loop = asyncio.get_running_loop()
    prices = await loop.run_in_executor(None, lambda: _get_prices_sync([trade.symbol]))
    current = prices.get(trade.symbol, trade.entry_price or 0)

    trade.status = "closed"
    trade.exit_price = current if current > 0 else None
    trade.exit_date = _now()
    trade.exit_reason = "manual"
    db.commit()
    return {"ok": True}
