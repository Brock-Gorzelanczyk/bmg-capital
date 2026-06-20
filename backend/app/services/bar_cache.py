from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

# In-memory cache: key → (data, expires_at_epoch)
_cache: Dict[str, Tuple[List[Any], float]] = {}

# Hard cap on total entries — prevents quant scalper (1-min cadence, 20+ symbols)
# from growing the dict without bound. When full, expired entries are evicted first;
# if still at capacity, oldest-by-expiry entries are dropped.
_MAX_CACHE_SIZE = 200


def _make_key(symbol: str, timeframe: str, start: str, end: str) -> str:
    return f"{symbol}_{timeframe}_{start}_{end}"


def get_cached(symbol: str, timeframe: str, start: str, end: str) -> Optional[List[Any]]:
    """Return cached bar data if present and not expired, otherwise None."""
    key = _make_key(symbol, timeframe, start, end)
    if key in _cache:
        data, exp = _cache[key]
        if time.time() < exp:
            return data
        del _cache[key]
    return None


def set_cache(
    symbol: str,
    timeframe: str,
    start: str,
    end: str,
    data: List[Any],
    ttl_seconds: int = 300,
) -> None:
    """Store bar data in the in-memory cache with a TTL."""
    key = _make_key(symbol, timeframe, start, end)
    if len(_cache) >= _MAX_CACHE_SIZE and key not in _cache:
        # Evict expired first
        now = time.time()
        expired = [k for k, (_, exp) in _cache.items() if now >= exp]
        for k in expired:
            del _cache[k]
        # If still at cap, drop the soonest-to-expire entries
        if len(_cache) >= _MAX_CACHE_SIZE:
            overflow = len(_cache) - _MAX_CACHE_SIZE + 1
            oldest = sorted(_cache, key=lambda k: _cache[k][1])[:overflow]
            for k in oldest:
                del _cache[k]
    _cache[key] = (data, time.time() + ttl_seconds)


def clear_cache() -> None:
    """Evict all cached entries (useful for testing)."""
    _cache.clear()


def evict_expired() -> int:
    """Remove all expired entries. Returns the number of entries removed."""
    now = time.time()
    expired = [k for k, (_, exp) in _cache.items() if now >= exp]
    for k in expired:
        del _cache[k]
    return len(expired)
