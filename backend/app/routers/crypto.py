from __future__ import annotations

import asyncio
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import yfinance as yf
from fastapi import APIRouter, Depends

from app.dependencies import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/crypto", tags=["crypto"])

COINS = [
    {"symbol": "BTC-USD", "name": "Bitcoin",   "slug": "BTC"},
    {"symbol": "ETH-USD", "name": "Ethereum",  "slug": "ETH"},
    {"symbol": "SOL-USD", "name": "Solana",     "slug": "SOL"},
    {"symbol": "BNB-USD", "name": "BNB",        "slug": "BNB"},
    {"symbol": "XRP-USD", "name": "XRP",        "slug": "XRP"},
    {"symbol": "ADA-USD", "name": "Cardano",    "slug": "ADA"},
    {"symbol": "AVAX-USD","name": "Avalanche",  "slug": "AVAX"},
    {"symbol": "DOGE-USD","name": "Dogecoin",   "slug": "DOGE"},
    {"symbol": "LINK-USD","name": "Chainlink",  "slug": "LINK"},
    {"symbol": "DOT-USD", "name": "Polkadot",   "slug": "DOT"},
    {"symbol": "MATIC-USD","name":"Polygon",    "slug": "MATIC"},
    {"symbol": "UNI-USD", "name": "Uniswap",    "slug": "UNI"},
    {"symbol": "ATOM-USD","name": "Cosmos",     "slug": "ATOM"},
    {"symbol": "LTC-USD", "name": "Litecoin",   "slug": "LTC"},
    {"symbol": "SHIB-USD","name": "Shiba Inu",  "slug": "SHIB"},
    {"symbol": "TRX-USD", "name": "TRON",       "slug": "TRX"},
]

_cache: dict = {"data": None, "ts": 0.0}
_cache_lock = threading.Lock()
CACHE_TTL = 60.0  # 1-minute cache for prices


def _fetch_coin(symbol: str) -> Optional[dict]:
    try:
        t = yf.Ticker(symbol)
        hist = t.history(period="2d", interval="1d")
        if hist.empty:
            return None
        last = float(hist["Close"].iloc[-1])
        prev = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else last
        change_pct = ((last - prev) / prev * 100) if prev else 0.0
        volume = float(hist["Volume"].iloc[-1]) if "Volume" in hist.columns else 0.0
        info = {}
        try:
            info = t.info or {}
        except Exception:
            pass
        market_cap = info.get("marketCap") or 0
        return {
            "symbol": symbol,
            "last": round(last, 8),
            "prev_close": round(prev, 8),
            "change_pct": round(change_pct, 2),
            "volume": round(volume, 2),
            "market_cap": market_cap,
        }
    except Exception as e:
        logger.warning(f"Crypto quote failed {symbol}: {e}")
        return None


async def _fetch_all_coins() -> list[dict]:
    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=8) as ex:
        tasks = [loop.run_in_executor(ex, _fetch_coin, c["symbol"]) for c in COINS]
        raw = await asyncio.gather(*tasks, return_exceptions=True)

    results = []
    for coin, r in zip(COINS, raw):
        if isinstance(r, dict):
            results.append({**coin, **r})
        else:
            results.append({**coin, "last": None, "prev_close": None, "change_pct": None, "volume": 0, "market_cap": 0})
    return results


@router.get("/market")
async def get_market(_user=Depends(get_current_user)):
    """Top coins with prices, 24h change, volume. 1-minute cache."""
    with _cache_lock:
        if _cache["data"] and time.time() - _cache["ts"] < CACHE_TTL:
            return {"coins": _cache["data"], "cached": True}

    coins = await _fetch_all_coins()
    with _cache_lock:
        _cache["data"] = coins
        _cache["ts"] = time.time()
    return {"coins": coins, "cached": False}


@router.get("/quote/{symbol}")
async def get_coin_quote(symbol: str, _user=Depends(get_current_user)):
    """Single coin price. Symbol format: BTC-USD"""
    sym = symbol.upper()
    if not sym.endswith("-USD"):
        sym = f"{sym}-USD"
    result = await asyncio.to_thread(_fetch_coin, sym)
    if not result:
        return {"symbol": sym, "last": None, "error": "price unavailable"}
    return result
