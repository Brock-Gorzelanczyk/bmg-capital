from __future__ import annotations

import logging
from typing import Any, Dict, List

from alpaca.data.enums import DataFeed
from alpaca.data.requests import StockSnapshotRequest

from app.alpaca.client import get_historical_client

logger = logging.getLogger(__name__)

INDEX_SYMBOLS: List[str] = ["SPY", "QQQ", "DIA", "IWM"]


async def get_market_overview() -> List[Dict[str, Any]]:
    """Return price/change data for the four major index ETFs."""
    try:
        client = get_historical_client()
        req = StockSnapshotRequest(symbol_or_symbols=INDEX_SYMBOLS, feed=DataFeed.IEX)
        snapshots = client.get_stock_snapshot(req)
        result: List[Dict[str, Any]] = []
        for symbol in INDEX_SYMBOLS:
            if symbol in snapshots:
                snap = snapshots[symbol]
                daily = snap.daily_bar
                prev = snap.previous_daily_bar
                price = float(daily.close) if daily else 0.0
                prev_close = float(prev.close) if prev else price
                change = price - prev_close
                change_pct = (change / prev_close * 100) if prev_close else 0.0

                # Sanity check: index ETF prices have known realistic ranges.
                # SPY trades ~$400–$700, so anything below $200 or above $1200 is stale/bad data.
                PRICE_FLOOR: dict = {"SPY": 200, "QQQ": 150, "DIA": 200, "IWM": 100}
                floor = PRICE_FLOOR.get(symbol, 1)
                if price < floor:
                    logger.warning(
                        "Sanity check failed for %s: price %.2f is below floor %.0f — returning null",
                        symbol, price, floor,
                    )
                    price = None  # type: ignore[assignment]
                    change = None  # type: ignore[assignment]
                    change_pct = None  # type: ignore[assignment]

                result.append(
                    {
                        "symbol": symbol,
                        "price": price,
                        "change": change,
                        "change_pct": change_pct,
                        "volume": float(daily.volume) if daily else 0.0,
                    }
                )
        return result
    except Exception as e:
        logger.error(f"Market overview error: {e}", exc_info=True)
        return []
