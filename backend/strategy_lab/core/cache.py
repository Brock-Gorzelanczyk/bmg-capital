"""
Redis cache for market data bars.
15-minute TTL for all cached bars.
Day bots during active hours: bypass cache (always fresh).
Falls back to no-cache if REDIS_URL not set.
"""
from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)

_redis_client = None


def get_redis():
    """Return a connected Redis client, or None if unavailable / not configured."""
    global _redis_client
    if _redis_client is None:
        redis_url = os.getenv("REDIS_URL")
        if redis_url:
            try:
                import redis

                client = redis.from_url(redis_url, decode_responses=True)
                client.ping()
                _redis_client = client
                logger.info("[cache] Redis connected: %s", redis_url.split("@")[-1])
            except Exception as e:
                logger.warning("[cache] Redis unavailable: %s. Running without cache.", e)
                _redis_client = None
    return _redis_client


def get_cached_bars(symbol: str, timeframe: str, bot_name: str) -> list | None:
    """
    Return cached bars or None.
    Day bots bypass cache entirely during 9:30–16:00 ET Mon–Fri.
    """
    if _is_day_bot_active_hours(bot_name):
        return None

    r = get_redis()
    if r is None:
        return None

    key = f"bars:{symbol}:{timeframe}"
    try:
        data = r.get(key)
        if data:
            logger.debug("[cache] HIT %s", key)
            return json.loads(data)
        logger.debug("[cache] MISS %s", key)
        return None
    except Exception as exc:
        logger.debug("[cache] Get failed for %s: %s", key, exc)
        return None


def set_cached_bars(
    symbol: str, timeframe: str, bars: list, bot_name: str, ttl: int = 900
) -> None:
    """
    Cache bars for ttl seconds (default 15 min).
    Skips caching for active day bots.
    """
    if _is_day_bot_active_hours(bot_name):
        return

    r = get_redis()
    if r is None:
        return

    key = f"bars:{symbol}:{timeframe}"
    try:
        r.setex(key, ttl, json.dumps(bars))
        logger.debug("[cache] SET %s (ttl=%ds)", key, ttl)
    except Exception as exc:
        logger.debug("[cache] Set failed for %s: %s", key, exc)


def invalidate_bars(symbol: str, timeframe: str) -> None:
    """Explicitly invalidate a cached bar key (e.g. after forced refresh)."""
    r = get_redis()
    if r is None:
        return
    key = f"bars:{symbol}:{timeframe}"
    try:
        r.delete(key)
        logger.debug("[cache] INVALIDATED %s", key)
    except Exception as exc:
        logger.debug("[cache] Delete failed for %s: %s", key, exc)


def _is_day_bot_active_hours(bot_name: str) -> bool:
    """Return True if this is a day bot and it's currently within 9:30–16:00 ET on a weekday."""
    if "day" not in bot_name:
        return False
    try:
        import pytz
        from datetime import datetime

        et = pytz.timezone("America/New_York")
        now = datetime.now(et)
        if now.weekday() >= 5:
            return False
        # 9:30 AM = hour 9 minute 30 — check hour + minute
        in_session = (now.hour == 9 and now.minute >= 30) or (10 <= now.hour < 16)
        return in_session
    except Exception:
        return False
