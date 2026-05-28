from __future__ import annotations

"""
Binance perpetual futures free-tier wrappers.

All endpoints are public (no API key required).
  - /fapi/v1/fundingRate         — 8-hour funding rates
  - /futures/data/openInterestHist — historical open interest

30-minute TTL per symbol with threading.Lock.
Falls back to stale data on error.
"""

import logging
import threading
import time

import requests

logger = logging.getLogger(__name__)

_CACHE_TTL = 1800  # 30 minutes

_lock = threading.Lock()
_funding_cache: dict = {}
_funding_ts:    dict = {}
_oi_cache:      dict = {}
_oi_ts:         dict = {}

FAPI_BASE = "https://fapi.binance.com"


def ccxt_to_futures(sym: str) -> str:
    """BTC/USDT → BTCUSDT (Binance futures symbol format)."""
    return sym.replace("/", "")


def _stale(ts: float) -> bool:
    return time.time() - ts > _CACHE_TTL


def get_funding_rate(symbol: str, limit: int = 8) -> dict:
    """
    Recent 8-hour perpetual funding rates for a Binance futures symbol.

    Returns:
        latest      float    — most recent funding rate
        recent      list[float] — last `limit` rates, newest first
        annualized  float    — latest rate annualized (rate × 3 × 365 × 100 = %)
        ok          bool
    """
    with _lock:
        if symbol in _funding_cache and not _stale(_funding_ts.get(symbol, 0)):
            return _funding_cache[symbol]
        try:
            resp = requests.get(
                f"{FAPI_BASE}/fapi/v1/fundingRate",
                params={"symbol": symbol, "limit": limit},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, list) or not data:
                raise ValueError(f"Empty funding rate response for {symbol}")
            rates = [float(r["fundingRate"]) for r in reversed(data)]  # newest first
            latest = rates[0]
            result = {
                "latest": latest,
                "recent": rates,
                "annualized": latest * 3 * 365 * 100,
                "ok": True,
            }
            _funding_cache[symbol] = result
            _funding_ts[symbol] = time.time()
            logger.debug(f"Funding {symbol}: {latest:.4%} ({result['annualized']:.1f}% ann)")
            return result
        except Exception as e:
            logger.warning(f"Funding rate fetch failed for {symbol}: {e}")
            if symbol in _funding_cache:
                return _funding_cache[symbol]
            return {"latest": 0.0, "recent": [], "annualized": 0.0, "ok": False}


def get_oi_history(symbol: str, period: str = "1d", limit: int = 14) -> dict:
    """
    Open interest history from Binance futures.

    Returns:
        current     float   — latest OI in USD
        prev        float   — OI at start of window
        change_pct  float   — % change over the window
        direction   str     — "rising" | "falling" | "neutral"
        ok          bool
    """
    key = f"{symbol}_{period}"
    with _lock:
        if key in _oi_cache and not _stale(_oi_ts.get(key, 0)):
            return _oi_cache[key]
        try:
            resp = requests.get(
                f"{FAPI_BASE}/futures/data/openInterestHist",
                params={"symbol": symbol, "period": period, "limit": limit},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, list) or len(data) < 2:
                raise ValueError(f"Insufficient OI history for {symbol}")
            current    = float(data[-1]["sumOpenInterestValue"])
            prev       = float(data[0]["sumOpenInterestValue"])
            change_pct = (current - prev) / prev * 100 if prev > 0 else 0.0
            direction  = "rising" if change_pct > 3 else ("falling" if change_pct < -3 else "neutral")
            result = {
                "current": current,
                "prev": prev,
                "change_pct": change_pct,
                "direction": direction,
                "ok": True,
            }
            _oi_cache[key] = result
            _oi_ts[key] = time.time()
            logger.debug(f"OI {symbol} ({period}): {change_pct:+.1f}% ({direction})")
            return result
        except Exception as e:
            logger.warning(f"OI history fetch failed for {symbol}: {e}")
            if key in _oi_cache:
                return _oi_cache[key]
            return {"current": 0.0, "prev": 0.0, "change_pct": 0.0, "direction": "neutral", "ok": False}


def prefetch_derivatives(symbols: list[str]) -> None:
    """Pre-warm funding and OI caches for a list of CCXT symbols before the screen loop."""
    for sym in symbols:
        fsym = ccxt_to_futures(sym)
        try:
            get_funding_rate(fsym)
        except Exception:
            pass
        try:
            get_oi_history(fsym)
        except Exception:
            pass
