"""
Unified scan-and-execute loop.

Shared between the scheduled bot runner (_run_and_log in bot_scheduler.py)
and the admin /bots/{name}/scan-now-verbose endpoint.

The verbose endpoint proved this pipeline works (41 trades observed).
The scheduler now calls this same function, ensuring identical behavior.
"""
from __future__ import annotations

import logging
import traceback as _tb
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def scan_and_execute(
    profile_name: str,
    db,
    *,
    persist: bool = True,
    execute: bool = True,
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Run one full scan cycle for the named bot profile.

    Args:
        profile_name: Bot profile key (e.g. "crypto_quant_aggressive")
        db:           SQLAlchemy Session — caller is responsible for lifecycle
        persist:      Write signals to bot_signals table
        execute:      Write trades to bot_trades / bot_positions tables
        user_id:      Filter to one user's allocations (admin endpoint context).
                      None = all enabled paper allocations (scheduler context).

    Returns:
        Dict with keys: bot, symbols_scanned, symbols_with_bars,
        strategies_executed, signals_generated, results, errors,
        signals_persisted, trades_executed, persist_errors, execute_errors.
    """
    from strategy_lab.seeds import load_profile
    from strategy_lab.runner import _load_strategy_module, _execute_signal
    from app.db.models.bots import BotProfile as _BP, BotAllocation as _BA

    results: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    signals_persisted = 0
    persist_errors: List[Dict[str, Any]] = []
    trades_executed = 0
    execute_errors: List[Dict[str, Any]] = []

    # ── 1. Load profile YAML ──────────────────────────────────────────────────
    profile = load_profile(profile_name)
    if not profile:
        logger.warning("[scan:%s] profile YAML not found", profile_name)
        return _empty_result(profile_name, f"Profile '{profile_name}' not found")

    # ── 2. Verify bot is enabled in DB ────────────────────────────────────────
    bp = db.query(_BP).filter(_BP.name == profile_name).first()
    if not bp or not bp.enabled:
        logger.warning("[scan:%s] profile disabled or missing in DB", profile_name)
        return _empty_result(profile_name, "profile disabled or not found in DB")

    # ── 3. Find allocations ───────────────────────────────────────────────────
    alloc_q = db.query(_BA).filter(_BA.profile_id == bp.id)
    if user_id is not None:
        alloc_q = alloc_q.filter(_BA.user_id == user_id)
    else:
        alloc_q = alloc_q.filter(_BA.enabled.is_(True), _BA.paper_mode.is_(True))
    allocations = alloc_q.all()

    if not allocations:
        logger.warning("[scan:%s] no allocations (user_id=%s)", profile_name, user_id)
        return _empty_result(profile_name, f"No allocations found (user_id={user_id})")

    # ── 4. Fetch OHLCV bars ───────────────────────────────────────────────────
    asset_class = profile.get("asset_class", "stock")
    universe = profile.get("universe", {})
    symbols: List[str] = (
        universe.get("symbols", []) if isinstance(universe, dict) else list(universe or [])
    )
    timeframe = profile.get("scan_timeframe", "1h")
    limit = int(profile.get("scan_lookback_bars", 200))

    bars: Dict[str, list] = {}
    bar_error: str = ""
    try:
        if asset_class in ("crypto", "crypto_intraday", "quant"):
            from app.screener.crypto_runner import _fetch_crypto_bars
            raw = _fetch_crypto_bars(symbols, timeframe=timeframe, limit=limit)
        else:
            from app.screener.runner import _fetch_bars_sync
            raw = _fetch_bars_sync(symbols, period="60d")
        for sym, df in raw.items():
            if df is None or df.empty:
                continue
            bars[sym] = [
                {
                    "c": float(r["close"]),
                    "o": float(r["open"]),
                    "h": float(r["high"]),
                    "l": float(r["low"]),
                    "v": float(r.get("volume", 0) or 0),
                    "ts": r.name.isoformat() if hasattr(r.name, "isoformat") else str(r.name),
                }
                for _, r in df.iterrows()
            ]
    except Exception as exc:
        bar_error = str(exc)
        logger.warning("[scan:%s] bar fetch failed: %s", profile_name, exc)

    # ── 5. Detect market regime (graceful — may not exist yet) ────────────────
    regime: Dict[str, Any] = {}
    try:
        from strategy_lab.core.regime_detector import detect_regime
        regime = detect_regime(profile_name, profile) or {}
    except Exception:
        pass

    # ── 6. Run each strategy module ───────────────────────────────────────────
    strategy_names: List[str] = profile.get("strategies", [])
    strategies_executed = 0

    for strat_name in strategy_names:
        mod = _load_strategy_module(strat_name)
        if mod is None:
            errors.append({"symbol": "*", "strategy": strat_name, "error": "module not found in registry"})
            logger.warning("[scan:%s] strategy '%s' not in registry — skipping", profile_name, strat_name)
            continue
        if not hasattr(mod, "generate_signals"):
            errors.append({"symbol": "*", "strategy": strat_name, "error": "no generate_signals()"})
            continue
        try:
            sigs = mod.generate_signals(bars, profile, regime) or []
            strategies_executed += 1
            for sig in sigs:
                results.append({
                    "symbol": sig.symbol,
                    "strategy": strat_name,
                    "confidence": round(sig.confidence, 4),
                    "side": sig.side,
                    "reasons": {"reason": sig.reason},
                    "size_hint": float(getattr(sig, "size_hint", 0.1) or 0.1),
                })
        except Exception as exc:
            logger.error("[scan:%s] EXCEPTION in strategy %s: %s", profile_name, strat_name, exc, exc_info=True)
            errors.append({"symbol": "*", "strategy": strat_name, "error": str(exc)})

    logger.warning(
        "[scan:%s] bars=%d/%d strategies=%d signals=%d errors=%d",
        profile_name, len(bars), len(symbols), strategies_executed, len(results), len(errors),
    )

    # ── 7. Persist + execute per allocation ───────────────────────────────────
    threshold = float(profile.get("confidence_threshold", 0.5))
    default_size = float(profile.get("position_size_pct", 5.0))

    from strategy_lab.core.audit import log_signal
    from strategy_lab.core.signals import Signal

    for alloc in allocations:
        alloc_persisted = 0
        alloc_executed = 0

        if persist and results:
            for r in results:
                if r["confidence"] < threshold:
                    continue
                try:
                    _ep: Optional[float] = None
                    _sym_bars = bars.get(r["symbol"], [])
                    if _sym_bars:
                        _last = _sym_bars[-1]
                        _ep = float(_last.get("c") or _last.get("close") or 0) or None

                    _stop_info: dict = {}
                    if _ep and _ep > 0:
                        try:
                            from strategy_lab.core.expert.smart_stops import compute_stop
                            _stop_info = compute_stop(r["symbol"], r["side"], _ep, _sym_bars) or {}
                        except Exception:
                            pass
                        if not _stop_info.get("stop_price"):
                            _sl = float(profile.get("stop_loss_pct", 7.0)) / 100
                            _tp = float(profile.get("take_profit_pct", 15.0)) / 100
                            if r["side"] in ("buy", "cover"):
                                _stop_info = {
                                    "stop_price": round(_ep * (1 - _sl), 6),
                                    "target_price": round(_ep * (1 + _tp), 6),
                                }
                            else:
                                _stop_info = {
                                    "stop_price": round(_ep * (1 + _sl), 6),
                                    "target_price": round(_ep * (1 - _tp), 6),
                                }

                    sig = Signal(
                        symbol=r["symbol"],
                        side=r["side"],
                        confidence=r["confidence"],
                        size_hint=float(r.get("size_hint", 0.1)),
                        reason=str(r.get("reasons", "")),
                        strategy=r["strategy"],
                        ts=datetime.now(timezone.utc),
                    )
                    log_signal(
                        db, alloc.id, sig,
                        entry_price=_ep,
                        stop_price=_stop_info.get("stop_price"),
                        target_price=_stop_info.get("target_price"),
                    )
                    alloc_persisted += 1
                    signals_persisted += 1
                except Exception as _pe:
                    persist_errors.append({
                        "symbol": r["symbol"],
                        "strategy": r["strategy"],
                        "error": str(_pe),
                        "traceback": _tb.format_exc(),
                    })
                    logger.error("[scan:%s] persist FAILED %s/%s: %s",
                                 profile_name, r["symbol"], r["strategy"], _pe, exc_info=True)

        if execute and results:
            # Per-bot position cap — count open positions for THIS allocation only
            from app.db.models.bots import BotPosition as _BotPos
            position_cap = int(profile.get("position_cap", 999))
            alloc_open = (
                db.query(_BotPos)
                .filter(_BotPos.allocation_id == alloc.id, _BotPos.closed_at.is_(None))
                .count()
            )
            if alloc_open >= position_cap:
                logger.warning(
                    "[guardrail] %s alloc=%d blocked: open_positions=%d >= position_cap=%d",
                    profile_name, alloc.id, alloc_open, position_cap,
                )
            else:
                for r in results:
                    if r["confidence"] < threshold:
                        continue
                    if r["side"] not in ("buy", "sell"):
                        continue
                    try:
                        sig2 = Signal(
                            symbol=r["symbol"],
                            side=r["side"],
                            confidence=r["confidence"],
                            size_hint=float(r.get("size_hint", 0.1)),
                            reason=str(r.get("reasons", "")),
                            strategy=r["strategy"],
                            ts=datetime.now(timezone.utc),
                        )
                        _execute_signal(
                            db=db,
                            alloc=alloc,
                            sig=sig2,
                            final_size_pct=default_size,
                            profile=profile,
                            profile_name=profile_name,
                            bars=bars,
                        )
                        alloc_executed += 1
                        trades_executed += 1
                    except Exception as _ee:
                        execute_errors.append({
                            "symbol": r["symbol"],
                            "strategy": r["strategy"],
                            "error": str(_ee),
                            "traceback": _tb.format_exc(),
                        })
                        logger.error("[scan:%s] execute FAILED %s %s: %s",
                                     profile_name, r["side"], r["symbol"], _ee, exc_info=True)

        logger.warning(
            "[scheduled] %s alloc=%d persisted=%d executed=%d",
            profile_name, alloc.id, alloc_persisted, alloc_executed,
        )

    return {
        "bot": profile_name,
        "symbols_scanned": len(symbols),
        "symbols_with_bars": len(bars),
        "strategies_executed": strategies_executed,
        "results": results,
        "signals_generated": len(results),
        "errors": errors,
        "signals_persisted": signals_persisted,
        "trades_executed": trades_executed,
        "persist_errors": persist_errors,
        "execute_errors": execute_errors,
        **({"bar_fetch_error": bar_error} if bar_error else {}),
    }


def _empty_result(profile_name: str, error: str) -> Dict[str, Any]:
    return {
        "bot": profile_name,
        "error": error,
        "symbols_scanned": 0,
        "symbols_with_bars": 0,
        "strategies_executed": 0,
        "results": [],
        "signals_generated": 0,
        "errors": [],
        "signals_persisted": 0,
        "trades_executed": 0,
        "persist_errors": [],
        "execute_errors": [],
    }
