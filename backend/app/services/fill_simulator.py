from __future__ import annotations
import asyncio
import logging
import random
from typing import Optional, Tuple
import yfinance as yf

logger = logging.getLogger(__name__)

# Simulated bid-ask spread as fraction of price
SPREAD_PCT = 0.0005  # 0.05% spread
# Additional random slippage for market orders
SLIPPAGE_BASE = 0.0001  # 0.01% base
SLIPPAGE_RANDOM = 0.0002  # up to 0.02% random


async def get_quote(symbol: str) -> Optional[dict]:
    """Get bid, ask, last price for a symbol."""
    def _fetch():
        try:
            t = yf.Ticker(symbol)
            info = t.info
            last = (info.get("currentPrice") or info.get("regularMarketPrice")
                    or info.get("ask") or info.get("bid"))
            hist = t.history(period="2d")
            if not last:
                if not hist.empty:
                    last = float(hist["Close"].iloc[-1])
            if not last:
                return None
            last = float(last)
            half_spread = last * SPREAD_PCT / 2
            bid = round(last - half_spread, 2)
            ask = round(last + half_spread, 2)
            prev_close = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else last
            return {"bid": bid, "ask": ask, "last": last, "prev_close": prev_close}
        except Exception as e:
            logger.error(f"Quote fetch error {symbol}: {e}", exc_info=True)
            return None
    return await asyncio.to_thread(_fetch)


def simulate_fill(side: str, quote: dict, order_type: str) -> Tuple[float, float]:
    """
    Returns (fill_price, slippage_dollars).
    Market orders fill at ask (buy) or bid (sell) plus random slippage.
    """
    if side == "buy":
        base = quote["ask"]
    else:
        base = quote["bid"]

    if order_type == "market":
        slippage_pct = SLIPPAGE_BASE + random.uniform(0, SLIPPAGE_RANDOM)
        if side == "buy":
            fill_price = round(base * (1 + slippage_pct), 2)
        else:
            fill_price = round(base * (1 - slippage_pct), 2)
        slippage = abs(fill_price - base)
    else:
        # Limit/stop fills exactly at the limit price (conservative)
        fill_price = base
        slippage = 0.0

    return fill_price, slippage
