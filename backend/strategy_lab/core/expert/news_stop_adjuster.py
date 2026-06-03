"""
Tighten stops on news events that affect held positions.

News severity:
  'major': tighten stop to -0.5% from current, block new entries 60min
  'normal': tighten stop by 50% of current ATR distance
  'minor': no change

Uses NewsEvent table. Recalculate on every bar if news exists in last 60min.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

_MAJOR_STOP_PCT = 0.5      # stop at 0.5% from current price for major news
_BLOCK_MINUTES = 60        # block new entries for N minutes after major news
_NORMAL_ATR_TIGHTEN = 0.5  # reduce ATR distance by 50% for normal news


def _get_recent_news(symbol: str, db, minutes: int = 60) -> list:
    """Fetch NewsEvent rows for this symbol within the last `minutes` minutes."""
    try:
        from app.db.models.bots import NewsEvent  # may not exist yet
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        return (
            db.query(NewsEvent)
            .filter(
                NewsEvent.symbol == symbol,
                NewsEvent.published_at >= cutoff,
            )
            .order_by(NewsEvent.published_at.desc())
            .all()
        )
    except Exception as exc:
        logger.debug("[news_stop:%s] Could not query NewsEvent: %s", symbol, exc)
        return []


def _get_highest_severity(news_rows: list) -> str | None:
    """Return the highest severity from a list of news rows."""
    severity_rank = {"major": 3, "normal": 2, "minor": 1}
    best = None
    best_rank = 0
    for row in news_rows:
        sev = getattr(row, "severity", "minor") or "minor"
        rank = severity_rank.get(sev.lower(), 1)
        if rank > best_rank:
            best = sev.lower()
            best_rank = rank
    return best


def adjust_stop_for_news(
    symbol: str,
    current_stop_price: float,
    current_price: float,
    allocation_id: int,
    db,
) -> float:
    """Returns adjusted stop price."""
    if current_price <= 0:
        return current_stop_price

    recent_news = _get_recent_news(symbol, db, minutes=60)
    if not recent_news:
        return current_stop_price

    severity = _get_highest_severity(recent_news)
    if severity is None or severity == "minor":
        return current_stop_price

    if severity == "major":
        # Tighten stop to -0.5% from current price
        new_stop = current_price * (1.0 - _MAJOR_STOP_PCT / 100.0)
        # Only tighten, never loosen
        if new_stop > current_stop_price:
            logger.info(
                "[news_stop:%s] Major news: tightening stop from %.4f to %.4f (%.2f%% from current)",
                symbol, current_stop_price, new_stop, _MAJOR_STOP_PCT,
            )
            return round(new_stop, 4)
        return current_stop_price

    if severity == "normal":
        # Tighten by reducing the ATR distance by 50%
        current_distance = current_price - current_stop_price
        if current_distance > 0:
            tightened_distance = current_distance * (1.0 - _NORMAL_ATR_TIGHTEN)
            new_stop = current_price - tightened_distance
            if new_stop > current_stop_price:
                logger.info(
                    "[news_stop:%s] Normal news: tightening stop from %.4f to %.4f",
                    symbol, current_stop_price, new_stop,
                )
                return round(new_stop, 4)
        return current_stop_price

    return current_stop_price


def should_block_new_entries(symbol: str, db) -> bool:
    """True if major news in last 60min for this symbol."""
    recent_news = _get_recent_news(symbol, db, minutes=_BLOCK_MINUTES)
    if not recent_news:
        return False
    severity = _get_highest_severity(recent_news)
    if severity == "major":
        logger.info("[news_stop:%s] Blocking new entries due to major news in last %dmin", symbol, _BLOCK_MINUTES)
        return True
    return False
