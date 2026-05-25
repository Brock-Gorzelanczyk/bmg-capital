from __future__ import annotations

import asyncio
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import yfinance as yf

logger = logging.getLogger(__name__)

_cache_lock = threading.Lock()
_cache: Dict[str, Any] = {}
_CACHE_TTL = 6 * 3600  # 6 hours

MAJOR_STOCKS = [
    # Mega-cap tech
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "NVDA", "META", "TSLA",
    # Finance
    "JPM", "BAC", "GS", "MS", "C", "WFC", "BLK", "V", "MA", "AXP", "PYPL",
    # Healthcare / pharma
    "JNJ", "UNH", "PFE", "MRK", "ABBV", "LLY", "BMY", "AMGN", "GILD", "CVS",
    "TMO", "DHR", "ABT", "VRTX", "REGN", "ZTS", "BIIB",
    # Consumer staples / discretionary
    "WMT", "COST", "HD", "MCD", "SBUX", "NKE", "KO", "PEP", "PG", "MDLZ",
    "LOW", "TGT", "AMZN", "BKNG", "MAR",
    # Industrials / defense
    "HON", "CAT", "DE", "BA", "GE", "RTX", "LMT", "NOC", "UPS", "FDX",
    "CSX", "UNP", "NSC",
    # Tech / semiconductors
    "ADBE", "CRM", "ORCL", "CSCO", "IBM", "INTC", "AMD", "QCOM", "AVGO",
    "TXN", "MU", "LRCX", "KLAC", "AMAT", "MRVL", "MCHP",
    # Software / cloud
    "NOW", "SNOW", "DDOG", "NET", "CRWD", "PANW", "ZS", "OKTA", "PLTR",
    "SHOP", "UBER", "ABNB", "NFLX", "SPOT",
    # Energy
    "XOM", "CVX", "COP", "SLB", "OXY", "PSX", "MPC", "HAL", "EOG",
    # Telecom / media
    "T", "VZ", "CMCSA", "DIS", "PARA",
    # Financial tech / fintech
    "SQ", "COIN", "HOOD", "SOFI", "AFRM",
    # Auto
    "F", "GM", "TSLA", "RIVN",
    # Misc large cap
    "LIN", "NEE", "ACN", "MSCI", "SPGI", "ICE", "CME", "BRK-B",
]

# Deduplicate while preserving order
_seen: set = set()
MAJOR_STOCKS = [s for s in MAJOR_STOCKS if not (s in _seen or _seen.add(s))]  # type: ignore[func-returns-value]


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
            if hasattr(ed, "year"):  # datetime.date or datetime.datetime
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

    now = datetime.utcnow()
    end = now + timedelta(days=days_ahead)

    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=25) as executor:
        futures = [
            loop.run_in_executor(executor, _fetch_one, sym, now, end)
            for sym in MAJOR_STOCKS
        ]
        results = await asyncio.gather(*futures, return_exceptions=True)

    data = [r for r in results if isinstance(r, dict)]
    data.sort(key=lambda x: x["date"])

    with _cache_lock:
        _cache[cache_key] = {"ts": time.time(), "data": data}

    return data
