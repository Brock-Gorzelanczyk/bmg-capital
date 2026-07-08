"""Per-strategy diagnostic for silent options strategies.

GET /api/admin/options-diagnostic

Runs each of the 10 credit / spread option strategies against a fixed
options-liquid universe with fresh bars + current regime, and reports
per-strategy signal generation + per-symbol drop reasons.

Purpose: when 10 credit strategies produce 0 signals despite the VIX
gate returning multiplier=1.0 (contango, short-vol OK), we need to
know which internal filter is killing them. This endpoint traces:
  - generate_signals() output count
  - per-symbol call of _entry_conditions where exposed
  - regime snapshot used

Answer to the question: "which filter is silencing X credit strategies?"
"""
from __future__ import annotations

import importlib
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.db.models.users import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin-options-diagnostic"])


# 10 currently-silent credit / spread strategies (per 2026-07-07 audit)
_SILENT_STRATEGIES = [
    "wheel_strategy",
    "covered_call_30d",
    "cash_secured_put",
    "pmcc_diagonal",
    "iron_condor_45dte",
    "jade_lizard",
    "neutral_calendar_spread",
    "bull_put_credit_spread",
    "bear_call_credit_spread",
    "bull_call_debit_spread",
]

# Options-liquid universe — the strategies filter on IV, trend, RSI etc,
# so we want liquid names with real option volume where filters won't
# false-fail on data quality.
_TEST_UNIVERSE = [
    "SPY", "QQQ", "IWM",
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
    "JPM", "V", "MA", "UNH", "JNJ",
]


def _fetch_yf_closes(symbol: str, days: int = 90) -> Optional[List[float]]:
    """Fetch last N days of daily closes via yfinance. None on failure."""
    try:
        import yfinance as yf  # type: ignore
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days + 30)  # buffer for weekends/holidays
        hist = yf.Ticker(symbol).history(start=start, end=end, interval="1d")
        if hist is None or hist.empty:
            return None
        return [float(c) for c in hist["Close"].tolist()]
    except Exception as exc:
        logger.warning("[options-diag] yfinance fetch %s failed: %s", symbol, exc)
        return None


def _closes_to_bars(closes: List[float]) -> List[Dict[str, float]]:
    """Convert flat closes list to strategy-expected bar dicts."""
    return [{"c": c, "o": c, "h": c, "l": c, "v": 0} for c in closes]


def _trace_symbol(strategy_mod, symbol: str, closes: List[float], regime: dict) -> dict:
    """Attempt to call the strategy's _entry_conditions and return outcome.

    Handles two _entry_conditions signature variants across the strategy files:
      (symbol, closes, regime)                  — most strategies
      (symbol, closes, volumes, regime)          — bull_call_debit_spread

    Falls back to generate_signal() when _entry_conditions is not exposed or
    signature detection fails.
    """
    if hasattr(strategy_mod, "_entry_conditions"):
        # Try 3-arg signature first (most common)
        try:
            result = strategy_mod._entry_conditions(symbol, closes, regime)
            if isinstance(result, tuple) and len(result) == 3:
                enter, conf, reason = result
                return {
                    "would_enter": bool(enter),
                    "confidence": float(conf) if enter else 0.0,
                    "reason": reason if reason else None,
                }
        except TypeError:
            # Fall through to 4-arg attempt
            pass
        except Exception as exc:
            return {"would_enter": False, "reason": f"3-arg exception: {type(exc).__name__}: {exc}"}
        # Try 4-arg (with volumes)
        try:
            fake_volumes = [1000.0] * len(closes)
            result = strategy_mod._entry_conditions(symbol, closes, fake_volumes, regime)
            if isinstance(result, tuple) and len(result) == 3:
                enter, conf, reason = result
                return {
                    "would_enter": bool(enter),
                    "confidence": float(conf) if enter else 0.0,
                    "reason": reason if reason else None,
                    "trace_method": "4-arg with fake volumes",
                }
        except Exception as exc:
            return {"would_enter": False, "reason": f"4-arg exception: {type(exc).__name__}: {exc}"}

    # Fallback: try generate_signal
    if hasattr(strategy_mod, "generate_signal"):
        try:
            sig = strategy_mod.generate_signal(symbol, closes, regime=regime)
            if sig is None:
                return {"would_enter": False, "confidence": 0.0, "reason": None,
                        "trace_method": "generate_signal (returned None)"}
            return {"would_enter": True, "confidence": float(getattr(sig, "confidence", 0.0)),
                    "reason": getattr(sig, "reason", None), "trace_method": "generate_signal"}
        except Exception as exc:
            return {"would_enter": False, "reason": f"generate_signal exception: {type(exc).__name__}: {exc}"}
    return {"would_enter": False, "reason": "no _entry_conditions or generate_signal exposed"}


def _diagnose_strategy(name: str, bar_bundles: dict, regime: dict) -> dict:
    """Run one strategy against the universe, return signal count + first-N traces."""
    t0 = time.monotonic()
    try:
        mod = importlib.import_module(f"strategy_lab.strategies.{name}")
    except Exception as exc:
        return {
            "strategy": name,
            "import_ok": False,
            "error": f"import failed: {exc}",
        }

    # 1. Bulk call: generate_signals
    signals_out: List[dict] = []
    generate_error: Optional[str] = None
    try:
        signals = mod.generate_signals(bar_bundles, {}, regime)
        for s in signals[:10]:
            signals_out.append({
                "symbol": getattr(s, "symbol", None),
                "side": getattr(s, "side", None),
                "confidence": float(getattr(s, "confidence", 0.0)),
                "strategy": getattr(s, "strategy", None),
            })
    except Exception as exc:
        generate_error = f"{type(exc).__name__}: {exc}"

    # 2. Per-symbol trace — reveals WHY 0 signals if that's the case
    per_symbol: List[dict] = []
    for sym, bars in bar_bundles.items():
        closes = [b["c"] for b in bars]
        if len(closes) < 22:
            per_symbol.append({"symbol": sym, "would_enter": False,
                               "reason": f"only {len(closes)} closes < 22"})
            continue
        trace = _trace_symbol(mod, sym, closes, regime)
        trace["symbol"] = sym
        per_symbol.append(trace)

    elapsed_ms = int((time.monotonic() - t0) * 1000)

    # 3. Summarize drop reasons
    drop_reasons: Dict[str, int] = {}
    would_enter_count = 0
    for t in per_symbol:
        if t.get("would_enter"):
            would_enter_count += 1
        else:
            key = str(t.get("reason") or "no_reason_extracted")[:80]
            drop_reasons[key] = drop_reasons.get(key, 0) + 1

    return {
        "strategy": name,
        "import_ok": True,
        "elapsed_ms": elapsed_ms,
        "generate_signals_count": len(signals_out) if signals_out else 0,
        "generate_signals_sample": signals_out[:3],
        "generate_error": generate_error,
        "per_symbol_would_enter": would_enter_count,
        "per_symbol_drop_reasons_top": dict(sorted(
            drop_reasons.items(), key=lambda kv: -kv[1]
        )[:5]),
        "per_symbol_trace_sample": per_symbol[:5],
    }


@router.get("/options-diagnostic")
def options_diagnostic(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    universe: Optional[str] = None,  # comma-sep override
    strategies: Optional[str] = None,  # comma-sep override
) -> Dict[str, Any]:
    """Trace why credit-strategy options bots produce 0 signals.

    Returns per-strategy: signal count, first-3 signals if any, and
    per-symbol would_enter + drop_reason across the universe. If a
    strategy imports cleanly but produces 0 signals AND all per-symbol
    traces come back with the same drop_reason, that reason is the
    culprit.
    """
    if not getattr(current_user, "is_admin", False) and getattr(current_user, "role", "") != "admin":
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Admin only")

    # Universe
    uni = [s.strip().upper() for s in (universe.split(",") if universe else _TEST_UNIVERSE) if s.strip()]

    # Strategies
    strats = [s.strip() for s in (strategies.split(",") if strategies else _SILENT_STRATEGIES) if s.strip()]

    # Regime (real, live)
    try:
        from strategy_lab.core.regime_detector import get_regime
        regime = get_regime(db) or {}
    except Exception as exc:
        logger.exception("[options-diag] regime fetch failed")
        regime = {"error": str(exc)}

    # Also read live VIX/VIX3M multiplier for context
    try:
        from strategy_lab.core.vix_regime import get_vix_regime_multiplier
        vix_mult = get_vix_regime_multiplier()
    except Exception:
        vix_mult = None

    # Fetch bars
    bar_bundles: Dict[str, List[Dict[str, float]]] = {}
    bar_status: Dict[str, str] = {}
    for sym in uni:
        closes = _fetch_yf_closes(sym, days=90)
        if closes and len(closes) >= 22:
            bar_bundles[sym] = _closes_to_bars(closes)
            bar_status[sym] = f"ok ({len(closes)} closes)"
        else:
            bar_status[sym] = f"insufficient ({len(closes) if closes else 0} closes)"

    # Run each strategy
    results = []
    for name in strats:
        results.append(_diagnose_strategy(name, bar_bundles, regime))

    # Summary — how many strategies would enter on any symbol?
    active_strats = sum(1 for r in results if r.get("per_symbol_would_enter", 0) > 0)

    return {
        "universe": uni,
        "universe_bar_status": bar_status,
        "regime": regime,
        "vix_mult": vix_mult,
        "strategies_tested": len(strats),
        "strategies_with_any_signal": active_strats,
        "results": results,
    }
