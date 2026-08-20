from __future__ import annotations

import asyncio
import gc
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import yfinance as yf

from app.alpaca.assets import get_universe
from app.screener.filters import apply_filters, build_filters

logger = logging.getLogger(__name__)

# ── In-memory bar cache (1-hour TTL) ─────────────────────────────────────────
# 2026-08-20 (task #77 followup): keep TTL at 1h but add explicit dereferences
# in cache-refresh + fetch loop. fb61b408 fixed scan_and_execute's local `raw`;
# this file's module-level cache also needs an explicit clear-before-replace
# so the old DataFrames drop refcount to 0 immediately, not just when GC feels
# like it. Combined with per-chunk `raw = None` in _fetch_bars_sync, closes
# the +25MB/run leak that PM Claude's 2026-08-20 audit still flagged as P2.
_bar_cache: Optional[Dict[str, pd.DataFrame]] = None
_bar_cache_ts: float = 0.0
_BAR_CACHE_TTL = 3600  # seconds
_cache_lock = asyncio.Lock()


def _cache_is_fresh() -> bool:
    return _bar_cache is not None and (time.time() - _bar_cache_ts) < _BAR_CACHE_TTL


def _fetch_bars_sync(symbols: List[str], period: str = "1y", interval: str = "1d") -> Dict[str, pd.DataFrame]:
    """Batch download OHLCV bars via yfinance.

    interval: yfinance interval string ("1d", "1h", "30m", "15m", "5m", etc.)
    period: lookback window ("1d", "5d", "60d", "1y", etc.)
    """
    result: Dict[str, pd.DataFrame] = {}
    batch_size = 100  # larger batches = fewer round trips

    for i in range(0, len(symbols), batch_size):
        chunk = symbols[i : i + batch_size]
        raw = None
        try:
            raw = yf.download(
                tickers=chunk,
                period=period,
                interval=interval,
                auto_adjust=True,
                group_by="ticker",
                threads=True,
                progress=False,
                prepost=False,  # exclude pre/post market bars (critical for intraday strategies)
            )
            if raw is None or raw.empty:
                continue

            single = len(chunk) == 1
            for sym in chunk:
                try:
                    df = raw.copy() if single else raw[sym].copy()
                    df.columns = [str(c).lower() for c in df.columns]
                    df = df[["open", "high", "low", "close", "volume"]].dropna()
                    if len(df) > 1:
                        result[sym] = df
                    df = None
                except Exception:
                    continue
        except Exception as e:
            logger.error(f"yfinance batch fetch error at {chunk[0]}: {e}")
        finally:
            # 2026-08-20 leak fix: sever chunk-scope refs to raw MultiIndex
            # frame before next iteration. Combined with fb61b408, closes
            # the yfinance-buffer leak that survived the scan_and_execute fix.
            raw = None

        # Brief pause between chunks — not needed with threads=True but be polite
        if i + batch_size < len(symbols):
            time.sleep(0.5)

    return result


async def _get_cached_bars() -> Dict[str, pd.DataFrame]:
    """Return cached bars, refreshing if stale. Thread-safe via asyncio lock."""
    global _bar_cache, _bar_cache_ts
    async with _cache_lock:
        if _cache_is_fresh():
            logger.info("Screener: serving bars from cache")
            return _bar_cache  # type: ignore[return-value]
        logger.info("Screener: downloading bars (cache miss or expired)")
        # Explicit clear-before-replace: without this, Python's GC decides
        # when to release the old ~30-50MB cache. On a 512MB container that
        # matters. Clearing the dict first drops the DataFrame refcounts to
        # 0 immediately, then we rebind to the fresh cache and gc.collect
        # to reclaim the space before scans start hitting the new cache.
        if _bar_cache is not None:
            try:
                for _s in list(_bar_cache.keys()):
                    _bar_cache[_s] = None
                _bar_cache.clear()
            except Exception:
                pass
            _bar_cache = None
            gc.collect()
        universe = get_universe()
        loop = asyncio.get_running_loop()
        bars = await loop.run_in_executor(None, lambda: _fetch_bars_sync(universe))
        _bar_cache = bars
        _bar_cache_ts = time.time()
        logger.info(f"Screener: cached {len(bars)} symbols")
        return bars


async def fetch_bars_batch(symbols: List[str], period: str = "1y") -> Dict[str, pd.DataFrame]:
    """Async wrapper around the synchronous yfinance batch fetch (no caching)."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: _fetch_bars_sync(symbols, period))


async def get_cached_bars() -> Dict[str, pd.DataFrame]:
    """Public accessor for the bar cache (fetches if stale)."""
    return await _get_cached_bars()


def get_cache_info() -> Dict[str, Any]:
    """Return metadata about the current bar cache."""
    universe = get_universe()
    return {
        "universe_count": len(universe),
        "data_as_of": _bar_cache_ts if _bar_cache is not None else None,
    }


def run_screen_sync(filter_configs: List[dict], all_bars: Dict[str, pd.DataFrame]) -> List[Dict[str, Any]]:
    """Apply filters to pre-fetched bars. Used by daily automation to avoid re-downloading."""
    filters = build_filters(filter_configs)
    matching: List[Dict[str, Any]] = []
    for symbol, df in all_bars.items():
        if len(df) < 2:
            continue
        try:
            passes = apply_filters(df, filters)
            if passes:
                change_pct = float((df["close"].iloc[-1] / df["close"].iloc[-2] - 1) * 100)
                change_5d = float((df["close"].iloc[-1] / df["close"].iloc[-6] - 1) * 100) if len(df) >= 6 else change_pct
                avg_vol = float(df["volume"].iloc[-21:-1].mean()) if len(df) >= 22 else float(df["volume"].mean())
                rel_volume = round(float(df["volume"].iloc[-1] / avg_vol), 2) if avg_vol > 0 else 1.0
                matching.append({
                    "symbol": symbol,
                    "price": float(df["close"].iloc[-1]),
                    "change_pct": change_pct,
                    "change_5d": change_5d,
                    "volume": float(df["volume"].iloc[-1]),
                    "rel_volume": rel_volume,
                })
        except Exception as e:
            logger.debug(f"Filter error for {symbol}: {e}")
    return sorted(matching, key=lambda x: abs(x["change_pct"]), reverse=True)


async def run_screen(filter_configs: List[dict]) -> List[Dict[str, Any]]:
    """Run a screen using cached bars (downloaded once per hour)."""
    all_bars = await _get_cached_bars()
    return run_screen_sync(filter_configs, all_bars)
