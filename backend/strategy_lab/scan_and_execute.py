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
from datetime import datetime, timedelta, timezone
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
            lookback_period = profile.get("scan_lookback_period", "1y")
            raw = _fetch_bars_sync(symbols, period=lookback_period)
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

    symbols_missing_bars = [s for s in symbols if s not in bars]
    logger.warning(
        "[scan:%s] bars=%d/%d strategies=%d signals=%d errors=%d missing=%s",
        profile_name, len(bars), len(symbols), strategies_executed, len(results), len(errors),
        symbols_missing_bars[:5] if symbols_missing_bars else "none",
    )

    # ── 7. Persist + execute per allocation ───────────────────────────────────
    threshold = float(profile.get("confidence_threshold", 0.5))
    default_size = float(profile.get("position_size_pct", 5.0))
    cooldown_min = float(profile.get("cooldown_minutes", 0))
    position_cap = int(profile.get("position_cap", 999))

    logger.error(
        "[cooldown-runtime-check] %s cooldown_minutes=%.0f position_cap=%d position_size_pct=%.4f",
        profile_name, cooldown_min, position_cap, default_size,
    )

    # ── Pre-deduplicate: keep one signal per (symbol, side) — highest confidence ─
    # Multiple strategies can fire the same (symbol, side) in one scan.
    # Without dedup, 5 strategies × SOL/buy = 5 signals; only 1 should reach the DB.
    seen_pairs: dict[tuple, dict] = {}
    for r in results:
        if r["confidence"] < threshold:
            continue
        key = (r["symbol"], r["side"])
        if key not in seen_pairs or r["confidence"] > seen_pairs[key]["confidence"]:
            seen_pairs[key] = r
    deduped = list(seen_pairs.values())

    logger.warning(
        "[scan:%s] pre-dedup=%d post-dedup=%d (unique symbol/side pairs)",
        profile_name, len(results), len(deduped),
    )

    from strategy_lab.core.audit import log_signal
    from strategy_lab.core.signals import Signal
    from app.db.models.bots import BotPosition as _BotPos, BotSignal as _BSig

    for alloc in allocations:
        alloc_persisted = 0
        alloc_executed = 0

        # ── Cooldown: compare naive utcnow() vs naive ts column ───────────────
        # datetime.utcnow() → naive UTC; ts column stores naive UTC (tz stripped at insert).
        on_cooldown: set = set()
        if cooldown_min > 0 and deduped:
            _cutoff = datetime.utcnow() - timedelta(minutes=cooldown_min)
            _recent = db.query(_BSig.symbol, _BSig.side).filter(
                _BSig.allocation_id == alloc.id,
                _BSig.ts >= _cutoff,
            ).all()
            on_cooldown = {(row.symbol, row.side) for row in _recent}
            logger.warning(
                "[cooldown] %s alloc=%d cutoff=%s found=%d on_cooldown=%s",
                profile_name, alloc.id, _cutoff.strftime("%H:%M:%S"),
                len(_recent), [f"{s}/{d}" for s, d in list(on_cooldown)[:5]],
            )

        # ── Position cap: slots-remaining approach ────────────────────────────
        alloc_open = (
            db.query(_BotPos)
            .filter(_BotPos.allocation_id == alloc.id, _BotPos.closed_at.is_(None))
            .count()
        )
        slots_remaining = max(0, position_cap - alloc_open)
        if slots_remaining == 0:
            logger.warning(
                "[position-cap] %s alloc=%d full: %d/%d positions open",
                profile_name, alloc.id, alloc_open, position_cap,
            )

        # Sort buy signals by confidence desc so highest-conviction trades fill slots first
        buy_signals = sorted(
            [r for r in deduped if r["side"] == "buy"],
            key=lambda r: -r["confidence"],
        )
        sell_signals = [r for r in deduped if r["side"] in ("sell", "short", "cover")]
        ordered_results = buy_signals + sell_signals

        # ── Per-signal: persist then execute ─────────────────────────────────
        for r in ordered_results:
            _cd_key = (r["symbol"], r["side"])
            _is_blocked = _cd_key in on_cooldown
            logger.error(
                "[cooldown-check] %s symbol=%s side=%s on_cooldown=%s cooldown_set_size=%d",
                profile_name, r["symbol"], r["side"], _is_blocked, len(on_cooldown),
            )
            if _is_blocked:
                logger.error(
                    "[cooldown-blocked] %s %s %s — fired within last %.0fmin, skipping",
                    profile_name, r["symbol"], r["side"], cooldown_min,
                )
                continue

            # Mark as in-flight immediately — prevents re-entry in the same scan
            # even if persist later fails (unconditional, outside the try-block)
            on_cooldown.add(_cd_key)

            # Persist
            signal_id: Optional[int] = None
            if persist:
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
                        if not _stop_info.get("stop_price") or not _stop_info.get("target_price"):
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
                        size_hint=min(1.0, max(0.0, default_size / 100.0)),
                        reason=str(r.get("reasons", "")),
                        strategy=r["strategy"],
                        ts=datetime.utcnow(),  # naive UTC — matches datetime.utcnow() cutoff in cooldown query
                    )
                    signal_id = log_signal(
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

            # Execute — buys consume a slot; sells/covers don't open new positions
            is_buy = r["side"] == "buy"
            if is_buy and slots_remaining <= 0:
                logger.warning(
                    "[position-cap] %s %s skipped: no slots left (%d/%d open)",
                    profile_name, r["symbol"], alloc_open, position_cap,
                )
                continue
            if execute and r["side"] in ("buy", "sell"):
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
                    if is_buy:
                        slots_remaining -= 1
                        alloc_open += 1
                    # Mark signal as executed — Discord worker requires executed_at IS NOT NULL
                    if signal_id is not None:
                        _sig_row = db.get(_BSig, signal_id)
                        if _sig_row is not None:
                            _sig_row.executed_at = datetime.now(timezone.utc)
                            db.commit()
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
        "symbols_missing_bars": [s for s in symbols if s not in bars],
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
