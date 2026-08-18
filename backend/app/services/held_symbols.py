"""Enumerate symbols the fund currently holds.

Used by:
  - app/alpaca/stream.py — restrict WS subscription to held stocks
    (was: unbounded MAX_SYMBOLS=30 slots filled by callers; now:
    only subscribe to symbols we actually hold).
  - anywhere else that wants "just the tickers we care about right now".

Broker (Alpaca) is master. We prefer alpaca_account_cache.get_alpaca_positions
which is TTL-cached, so this is cheap to call.
"""
from __future__ import annotations

import logging
from typing import List

logger = logging.getLogger(__name__)


def get_held_stock_symbols() -> List[str]:
    """Return stock symbols currently held in Alpaca (excludes options/crypto).

    Empty list on any failure — callers must handle gracefully (e.g., no
    WS subscription is safer than a stale/hung one).
    """
    try:
        from app.services.alpaca_account_cache import get_alpaca_positions
        positions = get_alpaca_positions()
        if not positions:
            return []
        syms: list[str] = []
        for p in positions:
            sym = p.get("symbol", "")
            if not sym:
                continue
            # Options have OCC format like AAPL240119C00150000 (14+ chars)
            # Crypto pairs contain '/'. Stocks are 1-5 char alpha.
            if "/" in sym:
                continue
            if len(sym) > 6:
                continue  # likely option
            syms.append(sym)
        return sorted(set(syms))
    except Exception as exc:
        logger.warning("[held_symbols] fetch failed: %s", exc)
        return []
