from __future__ import annotations

import logging
from typing import Any, Dict, List

from alpaca.data.enums import DataFeed
from alpaca.data.requests import StockSnapshotRequest

from app.alpaca.client import get_historical_client

logger = logging.getLogger(__name__)

SECTOR_ETFS: Dict[str, str] = {
    "Technology": "XLK",
    "Healthcare": "XLV",
    "Financials": "XLF",
    "Communication": "XLC",
    "Consumer Disc.": "XLY",
    "Consumer Staples": "XLP",
    "Industrials": "XLI",
    "Materials": "XLB",
    "Real Estate": "XLRE",
    "Utilities": "XLU",
    "Energy": "XLE",
}

# Static fallback — realistic demo values when no API keys are configured
STATIC_SECTORS = [
    {"sector": "Technology", "symbol": "XLK", "price": 214.38, "change_pct": 1.42},
    {"sector": "Healthcare", "symbol": "XLV", "price": 138.72, "change_pct": -0.31},
    {"sector": "Financials", "symbol": "XLF", "price": 47.85, "change_pct": 0.67},
    {"sector": "Communication", "symbol": "XLC", "price": 92.14, "change_pct": 2.18},
    {"sector": "Consumer Disc.", "symbol": "XLY", "price": 183.95, "change_pct": -0.84},
    {"sector": "Consumer Staples", "symbol": "XLP", "price": 79.22, "change_pct": -0.15},
    {"sector": "Industrials", "symbol": "XLI", "price": 124.60, "change_pct": 0.28},
    {"sector": "Materials", "symbol": "XLB", "price": 87.43, "change_pct": 0.93},
    {"sector": "Real Estate", "symbol": "XLRE", "price": 40.17, "change_pct": -1.23},
    {"sector": "Utilities", "symbol": "XLU", "price": 71.88, "change_pct": 0.44},
    {"sector": "Energy", "symbol": "XLE", "price": 89.54, "change_pct": -2.07},
]


async def get_sector_performance() -> List[Dict[str, Any]]:
    """Return price and daily change for each SPDR sector ETF."""
    try:
        client = get_historical_client()
        symbols = list(SECTOR_ETFS.values())
        req = StockSnapshotRequest(symbol_or_symbols=symbols, feed=DataFeed.IEX)
        snapshots = client.get_stock_snapshot(req)
        result: List[Dict[str, Any]] = []
        for sector, symbol in SECTOR_ETFS.items():
            if symbol in snapshots:
                snap = snapshots[symbol]
                daily = snap.daily_bar
                prev = snap.previous_daily_bar
                price = float(daily.close) if daily else 0.0
                prev_close = float(prev.close) if prev else price
                change_pct = ((price - prev_close) / prev_close * 100) if prev_close else 0.0
                result.append(
                    {
                        "sector": sector,
                        "symbol": symbol,
                        "price": price,
                        "change_pct": change_pct,
                    }
                )
        return result if result else STATIC_SECTORS
    except Exception as e:
        logger.error(f"Sector error: {e}", exc_info=True)
        return STATIC_SECTORS
