from __future__ import annotations

import asyncio
import logging
import time

from fastapi import APIRouter

from app.services.market_overview import get_market_overview
from app.services.sector import get_sector_performance

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/market", tags=["market"])


@router.get("/overview")
async def market_overview():
    """Return price and daily change for the major index ETFs."""
    return {"indices": await get_market_overview()}


@router.get("/sectors")
async def sector_performance():
    """Return daily performance for each SPDR sector ETF."""
    return {"sectors": await get_sector_performance()}


# ── S&P 500 snapshot ──────────────────────────────────────────────────────────

# Top ~100 S&P 500 by market cap — enough for a great-looking ticker tape
_SP500_TAPE_SYMBOLS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "JPM", "LLY",
    "UNH", "V",    "XOM",  "MA",   "COST",  "HD",   "PG",   "JNJ",  "ABBV", "NFLX",
    "BAC",  "CRM",  "KO",   "ORCL", "CVX",  "AMD",  "MRK",  "WMT",  "PEP",  "CSCO",
    "ADBE", "TMO",  "ABT",  "ACN",  "LIN",  "MCD",  "TXN",  "NOW",  "DIS",  "IBM",
    "DHR",  "AMGN", "PM",   "GE",   "CAT",  "INTU", "AXP",  "SPGI", "BKNG", "ISRG",
    "VRTX", "RTX",  "PLD",  "GS",   "MS",   "BLK",  "SYK",  "T",    "GILD", "MDLZ",
    "ADI",  "MMC",  "LRCX", "DE",   "TJX",  "BSX",  "ELV",  "ZTS",  "ADP",  "REGN",
    "PANW", "MO",   "CB",   "KLAC", "CME",  "CL",   "C",    "SO",   "PH",   "BA",
    "SCHW", "APH",  "PGR",  "HUM",  "WFC",  "AMAT", "SNPS", "CDNS", "EOG",  "SHW",
    "GD",   "USB",  "ITW",  "MCK",  "NOC",  "COF",  "ANET", "MSI",  "PYPL", "UBER",
]

_snapshot_cache: dict = {"data": [], "ts": 0.0}
_CACHE_TTL = 300  # 5 minutes


async def _fetch_snapshot_data() -> list:
    now = time.monotonic()
    if now - _snapshot_cache["ts"] < _CACHE_TTL and _snapshot_cache["data"]:
        return _snapshot_cache["data"]

    try:
        import yfinance as yf

        loop = asyncio.get_event_loop()

        def _sync_fetch() -> list:
            syms = " ".join(_SP500_TAPE_SYMBOLS)
            data = yf.download(
                syms,
                period="5d",
                interval="1d",
                progress=False,
                auto_adjust=True,
                threads=True,
            )
            results = []
            if data.empty:
                return results

            # yfinance returns multi-level columns when >1 ticker
            if hasattr(data.columns, "levels"):
                close = data["Close"]
            else:
                close = data[["Close"]].rename(columns={"Close": _SP500_TAPE_SYMBOLS[0]})

            for sym in _SP500_TAPE_SYMBOLS:
                try:
                    if sym not in close.columns:
                        continue
                    series = close[sym].dropna()
                    if len(series) < 1:
                        continue
                    price = float(series.iloc[-1])
                    prev = float(series.iloc[-2]) if len(series) >= 2 else price
                    change = price - prev
                    pct = (change / prev * 100) if prev else 0.0
                    results.append({
                        "symbol": sym,
                        "price": round(price, 2),
                        "prevClose": round(prev, 2),
                        "changePct": round(pct, 2),
                        "changeAbs": round(change, 2),
                    })
                except Exception:
                    pass
            return results

        results = await loop.run_in_executor(None, _sync_fetch)
        if results:
            _snapshot_cache["data"] = results
            _snapshot_cache["ts"] = now
        return results

    except Exception as exc:
        logger.warning("sp500 snapshot fetch failed: %s", exc)
        return _snapshot_cache.get("data", [])


@router.get("/sp500-snapshot")
async def sp500_snapshot():
    """Return price + daily change for top S&P 500 tickers. Cached 5 min."""
    tickers = await _fetch_snapshot_data()
    return {"tickers": tickers, "count": len(tickers)}
