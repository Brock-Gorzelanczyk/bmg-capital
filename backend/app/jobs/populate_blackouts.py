"""Populates trading_blackouts table daily at 5 AM ET.

Pulls earnings calendar from FMP if the MCP/HTTP client is available;
falls back gracefully if FMP is unavailable.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

_MACRO_EVENTS = {"FOMC", "CPI", "NFP", "PCE", "GDP"}

# Blackout window parameters
_EARNINGS_BEFORE_H = 12  # hours before event date
_EARNINGS_AFTER_H = 24   # hours after event date
_MACRO_BEFORE_H = 2
_MACRO_AFTER_H = 4


def _upsert_blackout(db, symbol, btype, event_date, start, end, source):
    from sqlalchemy import text
    db.execute(text(
        "INSERT OR REPLACE INTO trading_blackouts "
        "(symbol, blackout_type, event_date, blackout_start, blackout_end, source) "
        "VALUES (:sym, :bt, :ed, :bs, :be, :src)"
    ), {"sym": symbol, "bt": btype, "ed": event_date, "bs": start, "be": end, "src": source})


def _fetch_fmp_earnings(today, seven_days) -> list[dict]:
    """Try to pull earnings calendar from FMP API.  Returns [] on failure."""
    try:
        import os
        import requests
        api_key = os.getenv("FMP_API_KEY", "")
        if not api_key:
            return []
        url = (
            f"https://financialmodelingprep.com/api/v3/earning_calendar"
            f"?from={today.isoformat()}&to={seven_days.isoformat()}&apikey={api_key}"
        )
        resp = requests.get(url, timeout=15)
        if resp.ok:
            return resp.json() or []
    except Exception as exc:
        logger.warning("[populate_blackouts] FMP earnings fetch failed: %s", exc)
    return []


def _fetch_fmp_macro(today, thirty_days) -> list[dict]:
    """Try to pull high-impact macro calendar from FMP.  Returns [] on failure."""
    try:
        import os
        import requests
        api_key = os.getenv("FMP_API_KEY", "")
        if not api_key:
            return []
        url = (
            f"https://financialmodelingprep.com/api/v3/economic_calendar"
            f"?from={today.isoformat()}&to={thirty_days.isoformat()}&apikey={api_key}"
        )
        resp = requests.get(url, timeout=15)
        if resp.ok:
            return resp.json() or []
    except Exception as exc:
        logger.warning("[populate_blackouts] FMP macro fetch failed: %s", exc)
    return []


def run() -> dict:
    db = SessionLocal()
    earnings_inserted = 0
    macro_inserted = 0

    try:
        now = datetime.now(timezone.utc)
        today = now.date()
        seven_days = today + timedelta(days=7)
        thirty_days = today + timedelta(days=30)

        # Earnings blackouts
        events = _fetch_fmp_earnings(today, seven_days)
        for event in events:
            symbol = event.get("symbol")
            date_str = event.get("date") or event.get("reportDate")
            if not symbol or not date_str:
                continue
            try:
                from datetime import date as _date
                event_date = _date.fromisoformat(date_str[:10])
                event_dt = datetime(event_date.year, event_date.month, event_date.day)
                start = event_dt - timedelta(hours=_EARNINGS_BEFORE_H)
                end = event_dt + timedelta(hours=_EARNINGS_AFTER_H)
                _upsert_blackout(db, symbol, "earnings", event_date, start, end, "fmp")
                earnings_inserted += 1
            except Exception as exc:
                logger.warning("[populate_blackouts] earnings row failed: %s", exc)

        # Macro blackouts (portfolio-wide — NULL symbol)
        macro_events = _fetch_fmp_macro(today, thirty_days)
        for event in macro_events:
            event_name = (event.get("event") or "").upper()
            if not any(k in event_name for k in _MACRO_EVENTS):
                continue
            impact = (event.get("impact") or "").lower()
            if impact not in ("high", "3"):
                continue
            date_str = event.get("date") or ""
            if not date_str:
                continue
            try:
                from datetime import date as _date
                event_date = _date.fromisoformat(date_str[:10])
                event_dt = datetime(event_date.year, event_date.month, event_date.day, 14, 0)
                start = event_dt - timedelta(hours=_MACRO_BEFORE_H)
                end = event_dt + timedelta(hours=_MACRO_AFTER_H)
                btype = next((k for k in _MACRO_EVENTS if k in event_name), "macro").lower()
                _upsert_blackout(db, None, btype, event_date, start, end, "fmp")
                macro_inserted += 1
            except Exception as exc:
                logger.warning("[populate_blackouts] macro row failed: %s", exc)

        db.commit()
        logger.info(
            "[populate_blackouts] earnings=%d macro=%d",
            earnings_inserted, macro_inserted,
        )
        return {"earnings": earnings_inserted, "macro": macro_inserted}

    except Exception as exc:
        logger.error("[populate_blackouts] run() failed: %s", exc, exc_info=True)
        db.rollback()
        return {"error": str(exc)}
    finally:
        db.close()
