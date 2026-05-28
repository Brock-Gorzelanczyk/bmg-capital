from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

import yfinance as yf
from fastapi import APIRouter, Depends

from app.dependencies import get_current_user
from app.services import coingecko as cg

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/crypto", tags=["crypto"])


@router.get("/market")
async def get_market(_user=Depends(get_current_user)):
    """Top 100 coins with sparklines and 1h/24h/7d% from CoinGecko. 5-minute cache."""
    loop = asyncio.get_running_loop()
    coins = await loop.run_in_executor(None, lambda: cg.get_top_coins(100))
    return {"coins": coins}


@router.get("/overview")
async def get_overview(_user=Depends(get_current_user)):
    """Market overview: total cap, BTC dominance, Fear & Greed index."""
    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=2) as ex:
        gm_fut = loop.run_in_executor(ex, cg.get_global_market)
        fg_fut = loop.run_in_executor(ex, cg.get_fear_greed)
        gm, fg = await asyncio.gather(gm_fut, fg_fut)
    return {**gm, "fear_greed": fg}


@router.get("/trending")
async def get_trending(_user=Depends(get_current_user)):
    """Trending coins from CoinGecko."""
    loop = asyncio.get_running_loop()
    coins = await loop.run_in_executor(None, cg.get_trending)
    return {"coins": coins}


@router.post("/refresh")
async def refresh_market(_user=Depends(get_current_user)):
    """Evict CoinGecko caches so the next fetch gets fresh data."""
    cg.invalidate_all()
    return {"ok": True}


@router.get("/quote/{symbol}")
async def get_coin_quote(symbol: str, _user=Depends(get_current_user)):
    """Single coin real-time price via yfinance. Symbol format: BTC-USD"""
    sym = symbol.upper()
    if not sym.endswith("-USD"):
        sym = f"{sym}-USD"

    def _fetch():
        try:
            t = yf.Ticker(sym)
            hist = t.history(period="2d", interval="1d")
            if hist.empty:
                return None
            last = float(hist["Close"].iloc[-1])
            prev = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else last
            change_pct = ((last - prev) / prev * 100) if prev else 0.0
            return {
                "symbol": sym,
                "last": round(last, 8),
                "prev_close": round(prev, 8),
                "change_pct": round(change_pct, 2),
            }
        except Exception as e:
            logger.warning(f"Crypto quote failed {sym}: {e}")
            return None

    result = await asyncio.to_thread(_fetch)
    if not result:
        return {"symbol": sym, "last": None, "error": "price unavailable"}
    return result
