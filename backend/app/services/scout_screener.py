"""
Scout screener service — runs a strategy across an entire universe of symbols.
Parallel evaluation with ThreadPoolExecutor. 5-minute server-side cache.
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import yfinance as yf

logger = logging.getLogger(__name__)

# ── Bar fetch ─────────────────────────────────────────────────────────────────

def _fetch_bars(ticker: str, period: str = "1y") -> list[dict]:
    """Fetch daily OHLCV bars via yfinance Ticker.history().

    Same pattern as scout.py._fetch_bars_for_ticker — uses Ticker.history()
    instead of yf.download() to avoid MultiIndex DataFrame issues in
    yfinance >= 0.2. Returns [] on any failure so callers can skip silently.
    """
    try:
        hist = yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=True)
        if hist is None or hist.empty:
            return []
        hist.columns = [str(c).lower() for c in hist.columns]
        needed = ["open", "high", "low", "close", "volume"]
        if any(c not in hist.columns for c in needed):
            logger.debug("[screener] unexpected columns for %s: %s", ticker, list(hist.columns))
            return []
        hist = hist[needed].dropna()
        return [
            {
                "c": float(row["close"]),
                "o": float(row["open"]),
                "h": float(row["high"]),
                "l": float(row["low"]),
                "v": float(row.get("volume", 0) or 0),
                "ts": idx.isoformat() if hasattr(idx, "isoformat") else str(idx),
            }
            for idx, row in hist.iterrows()
        ]
    except Exception as exc:
        logger.debug("[screener] bar fetch failed for %s: %s", ticker, exc)
        return []


# ── Bar cache (in-process, 5-minute TTL) ─────────────────────────────────────

_BAR_CACHE: dict[str, tuple[float, list[dict]]] = {}
_BAR_CACHE_TTL: int = 300  # seconds


def _get_cached_bars(ticker: str) -> list[dict]:
    """Return cached bars or fetch fresh. Returns [] on failure."""
    entry = _BAR_CACHE.get(ticker)
    if entry and time.time() - entry[0] < _BAR_CACHE_TTL:
        return entry[1]
    bars = _fetch_bars(ticker)
    if bars:
        _BAR_CACHE[ticker] = (time.time(), bars)
    return bars


# ── Screen result cache (in-process, 5-minute TTL) ───────────────────────────

_SCREEN_CACHE: dict[str, tuple[float, dict]] = {}
_SCREEN_CACHE_TTL: int = 300  # seconds


def _screen_cache_get(key: str) -> dict | None:
    """Return a cached screen result, or None if missing / expired."""
    entry = _SCREEN_CACHE.get(key)
    if entry and time.time() - entry[0] < _SCREEN_CACHE_TTL:
        return entry[1]
    return None


def _screen_cache_set(key: str, value: dict) -> None:
    """Store a screen result with the current timestamp."""
    _SCREEN_CACHE[key] = (time.time(), value)


# ── Core screener ─────────────────────────────────────────────────────────────

def run_screen(
    strategy_id: str,
    universe: str = "sp500_plus_top_crypto",
    limit: int = 25,
    watchlist_symbols: list[str] | None = None,
) -> dict[str, Any]:
    """Screen the universe for tickers matching the strategy's entry conditions.

    Symbols are evaluated in parallel (20 workers). Results are ranked by
    confidence descending and capped at *limit*. The full response is cached
    for 5 minutes so repeated calls for the same (strategy, universe) pair
    are served instantly.

    Returns
    -------
    {
        "strategy_id": str,
        "universe": str,
        "scanned_count": int,
        "match_count": int,
        "cached": bool,
        "results": [
            {
                "rank": int,
                "symbol": str,
                "asset_class": str,       # "equity" | "crypto"
                "direction": str,          # "LONG" | "SHORT"
                "confidence": float,
                "setup_quality": float,
                "current_price": float | None,
                "key_metrics": dict,
                "summary": str,
            },
            ...
        ]
    }
    """
    from app.services.scout_universe import get_asset_class, get_universe_symbols
    from app.services.strategy_adapters import evaluate_ticker

    cache_key = f"{strategy_id}:{universe}"
    cached = _screen_cache_get(cache_key)
    if cached:
        cached["cached"] = True
        return cached

    symbols: list[str] = get_universe_symbols(universe, watchlist_symbols)

    matches: list[dict] = []

    def _eval_symbol(sym: str) -> dict | None:
        bars = _get_cached_bars(sym)
        if not bars:
            return None
        result = evaluate_ticker(strategy_id, bars)
        if not result.get("fires"):
            return None
        current_price: float | None = bars[-1]["c"] if bars else None
        return {
            "symbol": sym,
            "asset_class": get_asset_class(sym),
            "direction": result.get("direction", "LONG"),
            "confidence": round(float(result.get("confidence", 0)), 4),
            "setup_quality": round(float(result.get("setup_quality", 0)), 4),
            "current_price": round(current_price, 4) if current_price is not None else None,
            "key_metrics": result.get("key_metrics", {}),
            "summary": result.get("summary", ""),
        }

    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(_eval_symbol, sym): sym for sym in symbols}
        for future in futures:
            try:
                r = future.result(timeout=10)
                if r:
                    matches.append(r)
            except Exception as exc:
                logger.debug("[screener] symbol eval error: %s", exc)

    # Sort by confidence descending
    matches.sort(key=lambda x: -x["confidence"])

    # Assign ranks to the top-N
    for i, m in enumerate(matches[:limit], 1):
        m["rank"] = i

    response: dict[str, Any] = {
        "strategy_id": strategy_id,
        "universe": universe,
        "scanned_count": len(symbols),
        "match_count": len(matches),
        "cached": False,
        "results": matches[:limit],
    }
    _screen_cache_set(cache_key, response)
    return response
