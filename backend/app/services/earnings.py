from __future__ import annotations

import asyncio
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timezone, datetime, timedelta
from typing import Any, Dict, List, Optional

import yfinance as yf

logger = logging.getLogger(__name__)

_cache_lock = threading.Lock()
_cache: Dict[str, Any] = {}
_CACHE_TTL = 6 * 3600  # 6 hours

# Keep list short enough that fetching finishes in <10s (3 workers × ~60 stocks)
MAJOR_STOCKS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK-B",
    "JPM", "BAC", "GS", "MS", "C", "V", "MA", "AXP",
    "JNJ", "UNH", "PFE", "MRK", "ABBV", "LLY", "AMGN", "GILD",
    "WMT", "COST", "HD", "MCD", "SBUX", "NKE", "KO", "PEP", "PG",
    "HON", "CAT", "BA", "GE", "RTX", "LMT", "UPS", "FDX",
    "ADBE", "CRM", "ORCL", "CSCO", "IBM", "INTC", "AMD", "QCOM", "AVGO", "TXN",
    "NOW", "SNOW", "DDOG", "NET", "CRWD", "PANW", "PLTR", "NFLX",
    "XOM", "CVX", "COP", "SLB",
    "T", "VZ", "CMCSA", "DIS",
    "PYPL", "SQ", "COIN", "UBER", "ABNB", "SHOP",
]

# Deduplicate while preserving order
_seen: set = set()
MAJOR_STOCKS = [s for s in MAJOR_STOCKS if not (s in _seen or _seen.add(s))]  # type: ignore[func-returns-value]

_FETCH_TIMEOUT = 8  # seconds per symbol before we give up


def _fetch_one(symbol: str, from_date: datetime, to_date: datetime) -> Optional[Dict[str, Any]]:
    try:
        t = yf.Ticker(symbol)
        cal = t.calendar
        if not cal:
            return None
        earnings_dates = cal.get("Earnings Date") or []
        if not earnings_dates:
            return None
        for ed in earnings_dates:
            if hasattr(ed, "year"):
                if from_date.date() <= ed <= to_date.date():
                    return {
                        "symbol": symbol,
                        "date": ed.strftime("%Y-%m-%d"),
                        "eps_estimate": cal.get("Earnings Average"),
                        "eps_actual": None,
                        "revenue_estimate": cal.get("Revenue Average"),
                        "revenue_actual": None,
                        "time": None,
                    }
    except Exception as exc:
        logger.debug("earnings fetch failed for %s: %s", symbol, exc)
    return None


async def get_earnings_calendar(days_ahead: int = 14) -> List[Dict[str, Any]]:
    cache_key = str(days_ahead)
    with _cache_lock:
        cached = _cache.get(cache_key)
        if cached and (time.time() - cached["ts"]) < _CACHE_TTL:
            return cached["data"]

    now = datetime.now(timezone.utc)
    end = now + timedelta(days=days_ahead)

    loop = asyncio.get_running_loop()
    # 6 workers keeps resource usage modest; each request has an 8s timeout via asyncio.wait_for
    with ThreadPoolExecutor(max_workers=6, thread_name_prefix="earnings") as executor:
        async def _bounded(sym: str) -> Optional[Dict[str, Any]]:
            try:
                return await asyncio.wait_for(
                    loop.run_in_executor(executor, _fetch_one, sym, now, end),
                    timeout=_FETCH_TIMEOUT,
                )
            except asyncio.TimeoutError:
                logger.debug("earnings timeout for %s", sym)
                return None

        results = await asyncio.gather(*[_bounded(s) for s in MAJOR_STOCKS], return_exceptions=True)

    data = [r for r in results if isinstance(r, dict)]
    data.sort(key=lambda x: x["date"])

    with _cache_lock:
        _cache[cache_key] = {"ts": time.time(), "data": data}

    return data
