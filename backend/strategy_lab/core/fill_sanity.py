"""
Fill-price sanity check — applied at every BotTrade creation site.

Returns (ok, live_price, source).  ok=False → caller must reject the fill
and log SANITY_FAIL.  Threshold: >20% deviation from live ticker.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

_MAX_DEVIATION = 0.20  # 20%


def check_fill(
    symbol: str,
    fill_price: float,
    context: str = "unknown",
    max_deviation: float = _MAX_DEVIATION,
) -> tuple[bool, float, str]:
    """
    Compare fill_price against the live ticker for symbol.

    Returns:
        (ok, live_price, source)
        ok=True  → price is sane, proceed with the trade
        ok=False → deviation exceeds threshold, reject the trade
        live_price=0.0 when the live fetch failed (ok=True in that case —
        we don't block on unavailable data, we just can't validate)
    """
    if fill_price <= 0:
        logger.error("SANITY_FAIL [%s] %s fill_price=%.4f is non-positive", context, symbol, fill_price)
        return False, 0.0, "invalid"

    try:
        from app.services.live_prices import fetch_live_prices
        price_map = fetch_live_prices([symbol])
        live_price = float(price_map.get(symbol) or 0)
    except Exception as exc:
        logger.warning("SANITY_CHECK [%s] %s live fetch failed (%s) — allowing fill", context, symbol, exc)
        return True, 0.0, "unavailable"

    if live_price <= 0:
        logger.warning("SANITY_CHECK [%s] %s live price unavailable — allowing fill", context, symbol)
        return True, 0.0, "unavailable"

    source = "kraken" if "/" in symbol else "alpaca"
    deviation = abs(fill_price - live_price) / live_price

    if deviation > max_deviation:
        logger.error(
            "SANITY_FAIL [%s] %s fill_price=%.4f deviates %.1f%% from live %s=%.4f — REJECTING",
            context, symbol, fill_price, deviation * 100, source, live_price,
        )
        return False, live_price, source

    return True, live_price, source
