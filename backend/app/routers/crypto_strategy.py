from __future__ import annotations

"""
Crypto strategy API endpoints.

Mirrors strategy.py but filters all queries to asset_class = 'crypto'.
Uses the same _enrich_trade helper pattern with CoinGecko prices instead
of yfinance for crypto symbols.
"""

import asyncio
import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.strategy import DailyEquitySnapshot, DailyLog, StrategyTrade
from app.db.models.users import User
from app.db.session import get_db
from app.dependencies import get_current_user
from app.screener.crypto_filters import CRYPTO_PRESET_LABELS
from app.screener.crypto_runner import (
    CRYPTO_PORTFOLIO,
    MAX_HOLD_DAYS,
    _get_crypto_prices,
    _fetch_crypto_bars,
    run_crypto_automation,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/crypto-strategy", tags=["crypto-strategy"])


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _enrich_crypto_trade(t: StrategyTrade, prices: Dict[str, float]) -> Dict[str, Any]:
    current = (prices.get(t.symbol) or t.last_known_price) if t.status in ("open", "candidate") else t.exit_price
    ep = t.exit_price if t.status == "closed" else current
    pnl = ((ep - t.entry_price) * t.shares) if (ep and t.entry_price and t.entry_price > 0 and t.shares) else None
    pnl_pct = ((ep - t.entry_price) / t.entry_price * 100) if (ep and t.entry_price and t.entry_price > 0) else None
    days_held = 0
    if t.status == "candidate" and t.candidate_since:
        days_held = (date.today() - t.candidate_since.date()).days
    elif t.entry_price and t.entry_price > 0:
        end = t.exit_date or _now()
        start = t.entry_date or _now()
        days_held = (end - start).days

    return {
        "id":           t.id,
        "preset_key":   t.preset_key,
        "preset_label": CRYPTO_PRESET_LABELS.get(t.preset_key or "", t.preset_key or ""),
        "symbol":       t.symbol,
        "status":       t.status,
        "asset_class":  t.asset_class or "crypto",
        "exchange":     t.exchange or "binance",
        "candidate_since": t.candidate_since.isoformat() if t.candidate_since else None,
        "entry_trigger": t.entry_trigger,
        "entry_date":   t.entry_date.isoformat() if t.entry_price and t.entry_price > 0 else None,
        "entry_price":  t.entry_price if t.entry_price and t.entry_price > 0 else None,
        "shares":       t.shares if t.shares else None,
        "stop_price":   t.stop_price if t.stop_price and t.stop_price > 0 else None,
        "target_price": t.target_price if t.target_price and t.target_price > 0 else None,
        "atr":          t.atr,
        "risk_dollars": t.risk_dollars,
        "current_price": current,
        "exit_date":    t.exit_date.isoformat() if t.exit_date else None,
        "exit_price":   t.exit_price,
        "exit_reason":  t.exit_reason,
        "pnl":          round(pnl, 2) if pnl is not None else None,
        "pnl_pct":      round(pnl_pct, 2) if pnl_pct is not None else None,
        "days_held":    days_held,
        "last_known_price": t.last_known_price,
    }


async def _load_crypto_prices(symbols: List[str]) -> Dict[str, float]:
    """Fetch latest prices for crypto symbols via CCXT/Binance."""
    if not symbols:
        return {}
    loop = asyncio.get_running_loop()
    bars = await loop.run_in_executor(None, lambda: _fetch_crypto_bars(symbols, limit=5))
    return _get_crypto_prices(symbols, bars)


@router.get("/trades")
async def get_crypto_trades(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    trades = db.execute(
        select(StrategyTrade)
        .where(StrategyTrade.status.in_(["open", "closed"]))
        .where(StrategyTrade.user_id == current_user.id)
        .where(StrategyTrade.asset_class == "crypto")
        .order_by(StrategyTrade.entry_date.desc())
    ).scalars().all()

    open_syms = list({t.symbol for t in trades if t.status == "open"})
    prices = await _load_crypto_prices(open_syms)
    return {"trades": [_enrich_crypto_trade(t, prices) for t in trades]}


@router.get("/candidates")
async def get_crypto_candidates(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    candidates = db.execute(
        select(StrategyTrade)
        .where(StrategyTrade.status == "candidate")
        .where(StrategyTrade.user_id == current_user.id)
        .where(StrategyTrade.asset_class == "crypto")
        .order_by(StrategyTrade.candidate_since.desc())
    ).scalars().all()

    syms = list({t.symbol for t in candidates})
    prices = await _load_crypto_prices(syms)
    return {"candidates": [_enrich_crypto_trade(t, prices) for t in candidates]}


@router.get("/summary")
async def get_crypto_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    all_trades = db.execute(
        select(StrategyTrade)
        .where(StrategyTrade.user_id == current_user.id)
        .where(StrategyTrade.asset_class == "crypto")
    ).scalars().all()

    open_trades = [t for t in all_trades if t.status == "open"]
    open_syms = list({t.symbol for t in open_trades})
    prices = await _load_crypto_prices(open_syms)

    closed = [
        t for t in all_trades
        if t.status == "closed"
        and t.exit_reason not in ("expired",)
        and t.entry_price and t.entry_price > 0
        and t.exit_price
    ]
    candidates_count = sum(1 for t in all_trades if t.status == "candidate")
    open_count = len(open_trades)

    wins = [t for t in closed if t.exit_price > t.entry_price]
    losses = [t for t in closed if t.exit_price <= t.entry_price]
    realized_pnl = sum((t.exit_price - t.entry_price) * t.shares for t in closed)
    open_pnl = sum(
        ((prices.get(t.symbol) or t.last_known_price or t.entry_price) - t.entry_price) * t.shares
        for t in open_trades
        if t.entry_price and t.entry_price > 0 and t.shares
    )

    avg_win = (sum((t.exit_price - t.entry_price) / t.entry_price * 100 for t in wins) / len(wins)) if wins else 0
    avg_loss = (sum((t.exit_price - t.entry_price) / t.entry_price * 100 for t in losses) / len(losses)) if losses else 0
    expectancy = (
        (len(wins) / len(closed) * avg_win) + (len(losses) / len(closed) * avg_loss)
        if closed else 0
    )

    preset_stats: Dict[str, Any] = {}
    for t in closed:
        pk = t.preset_key or "unknown"
        if pk not in preset_stats:
            preset_stats[pk] = {
                "label": CRYPTO_PRESET_LABELS.get(pk, pk),
                "trades": 0, "wins": 0, "losses": 0, "total_pnl": 0.0,
            }
        s = preset_stats[pk]
        s["trades"] += 1
        pct = (t.exit_price - t.entry_price) / t.entry_price * 100
        s["total_pnl"] += (t.exit_price - t.entry_price) * t.shares
        if pct > 0: s["wins"] += 1
        else: s["losses"] += 1

    preset_list = [
        {
            "preset_key": pk,
            "preset_label": s["label"],
            "trades": s["trades"],
            "wins": s["wins"],
            "losses": s["losses"],
            "win_rate": round(s["wins"] / s["trades"] * 100, 1) if s["trades"] else 0,
            "total_pnl": round(s["total_pnl"], 2),
        }
        for pk, s in preset_stats.items()
    ]

    return {
        "overall": {
            "total_closed": len(closed),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(closed) * 100, 1) if closed else 0,
            "total_pnl": round(realized_pnl, 2),
            "open_pnl": round(open_pnl, 2),
            "portfolio_value": round(CRYPTO_PORTFOLIO + realized_pnl + open_pnl, 2),
            "open_positions": open_count,
            "candidates": candidates_count,
            "expectancy": round(expectancy, 2),
        },
        "by_preset": sorted(preset_list, key=lambda x: -x["total_pnl"]),
    }


@router.get("/log")
async def get_crypto_log(
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    entries = db.execute(
        select(DailyLog)
        .where(DailyLog.user_id == current_user.id)
        .where(DailyLog.preset_key.in_(list(CRYPTO_PRESET_LABELS.keys())))
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
async def get_crypto_equity(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    snaps = db.execute(
        select(DailyEquitySnapshot)
        .where(DailyEquitySnapshot.user_id == current_user.id)
        .where(DailyEquitySnapshot.asset_class == "crypto")
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
            }
            for s in snaps
        ],
        "baseline": CRYPTO_PORTFOLIO,
    }


# ---------------------------------------------------------------------------
# In-process scan status registry (persists for the lifetime of the worker)
# ---------------------------------------------------------------------------

import uuid as _uuid

_SCAN_STATUS: dict[str, dict] = {}


async def _run_crypto_wrapper(user_id: int, scan_id: str) -> None:
    _SCAN_STATUS[scan_id] = {"status": "running", "started_at": _now().isoformat(), "result": None, "error": None}
    try:
        logger.info(f"[crypto] Background run-now starting for user {user_id} scan={scan_id}")
        result = await run_crypto_automation(user_id=user_id)
        logger.info(f"[crypto] Background run-now complete for user {user_id}: {result}")
        _SCAN_STATUS[scan_id].update({"status": "complete", "result": result})
    except Exception as e:
        logger.error(f"[crypto] Background run-now failed for user {user_id}: {e}", exc_info=True)
        _SCAN_STATUS[scan_id].update({"status": "failed", "error": str(e)})


@router.post("/run-now")
async def run_crypto_now(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
):
    """Kick off crypto automation as a background task and return a scan_id for polling."""
    scan_id = str(_uuid.uuid4())
    background_tasks.add_task(_run_crypto_wrapper, current_user.id, scan_id)
    return {"ok": True, "scan_id": scan_id, "message": "Crypto scan started"}


@router.get("/scan/{scan_id}")
async def get_scan_status(
    scan_id: str,
    current_user: User = Depends(get_current_user),
):
    """Poll scan status by scan_id returned from /run-now."""
    entry = _SCAN_STATUS.get(scan_id)
    if not entry:
        return {"status": "unknown", "scan_id": scan_id}
    return {"scan_id": scan_id, **entry}


@router.get("/debug")
async def get_crypto_debug(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Diagnostic endpoint — returns live system state for debugging zero-result issues.

    Returns:
      - coin_universe: list of CCXT symbols the scanner iterates over
      - coin_universe_count: number of coins
      - last_scan_ids: last 5 scan IDs and their statuses
      - db_counts: raw counts from strategy_trades and strategy_daily_log for this user
      - ccxt_available: whether ccxt is installed and importable
      - data_sample: quick bar-fetch test for BTC/USDT (1 bar)
    """
    from app.screener.crypto_filters import CRYPTO_UNIVERSE as _UNI

    # Check CCXT availability
    ccxt_available = False
    ccxt_version = None
    try:
        import ccxt as _ccxt
        ccxt_available = True
        ccxt_version = _ccxt.__version__
    except ImportError:
        pass

    # Quick connectivity test — fetch 5 bars for BTC only
    loop = asyncio.get_running_loop()
    data_sample: dict = {}
    try:
        sample_bars = await asyncio.wait_for(
            loop.run_in_executor(None, lambda: _fetch_crypto_bars(["BTC/USDT"], limit=5)),
            timeout=30.0,
        )
        btc_df = sample_bars.get("BTC/USDT")
        if btc_df is not None and not btc_df.empty:
            data_sample = {
                "ok": True,
                "symbol": "BTC/USDT",
                "rows": len(btc_df),
                "latest_close": float(btc_df["close"].iloc[-1]),
                "columns": btc_df.columns.tolist(),
            }
        else:
            data_sample = {"ok": False, "reason": "empty dataframe returned"}
    except asyncio.TimeoutError:
        data_sample = {"ok": False, "reason": "timeout (30s) fetching BTC/USDT"}
    except Exception as e:
        data_sample = {"ok": False, "reason": str(e)}

    # DB counts
    from sqlalchemy import func as sqlfunc
    from app.db.models.strategy import StrategyTrade, DailyLog
    trade_counts = {}
    for status in ("candidate", "open", "closed"):
        trade_counts[status] = db.execute(
            select(sqlfunc.count(StrategyTrade.id))
            .where(StrategyTrade.user_id == current_user.id)
            .where(StrategyTrade.asset_class == "crypto")
            .where(StrategyTrade.status == status)
        ).scalar() or 0
    log_count = db.execute(
        select(sqlfunc.count(DailyLog.id))
        .where(DailyLog.user_id == current_user.id)
        .where(DailyLog.preset_key.in_(list(CRYPTO_PRESET_LABELS.keys())))
    ).scalar() or 0

    # Last scan statuses (most recent 5)
    last_scans = [
        {"scan_id": sid, **info}
        for sid, info in list(_SCAN_STATUS.items())[-5:]
    ]

    return {
        "coin_universe_count": len(_UNI),
        "coin_universe": _UNI,
        "ccxt_available": ccxt_available,
        "ccxt_version": ccxt_version,
        "data_sample": data_sample,
        "db_counts": {
            "user_id": current_user.id,
            "asset_class": "crypto",
            **trade_counts,
            "log_entries": log_count,
        },
        "last_scans": last_scans,
    }


@router.get("/quiz-status")
async def get_quiz_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return list of strategy_keys the current user has completed the comprehension quiz for."""
    from app.db.models.strategy import StrategyQuizCompletion
    rows = db.execute(
        select(StrategyQuizCompletion)
        .where(StrategyQuizCompletion.user_id == current_user.id)
    ).scalars().all()
    return {"completed": [r.strategy_key for r in rows]}


@router.post("/quiz-complete/{strategy_key}")
async def complete_quiz(
    strategy_key: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark a strategy's comprehension quiz as completed for this user."""
    from app.db.models.strategy import StrategyQuizCompletion
    existing = db.execute(
        select(StrategyQuizCompletion)
        .where(StrategyQuizCompletion.user_id == current_user.id)
        .where(StrategyQuizCompletion.strategy_key == strategy_key)
    ).scalar_one_or_none()
    if not existing:
        db.add(StrategyQuizCompletion(user_id=current_user.id, strategy_key=strategy_key))
        db.commit()
    return {"ok": True, "strategy_key": strategy_key}


@router.post("/toggle/{strategy_key}")
async def toggle_strategy(
    strategy_key: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Flip is_active on a strategy definition (kill switch)."""
    from app.db.models.strategy_definition import StrategyDefinition
    defn = db.execute(
        select(StrategyDefinition).where(StrategyDefinition.strategy_key == strategy_key)
    ).scalar_one_or_none()
    if not defn:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Strategy not found")
    defn.is_active = not defn.is_active
    db.commit()
    return {"ok": True, "strategy_key": strategy_key, "is_active": defn.is_active}


@router.get("/definitions")
async def get_strategy_definitions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.strategy_registry import get_all_definitions
    return {"definitions": get_all_definitions(db)}
