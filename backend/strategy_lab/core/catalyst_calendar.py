"""
Catalyst calendar — fetches and caches upcoming macro + earnings catalyst events.
Sources: hardcoded FOMC/CPI/NFP/PCE dates, Polygon earnings (if key set), Alpaca news.
Cache: in-memory, 1-hour TTL.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone, timedelta, date
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# ── In-memory cache ───────────────────────────────────────────────────────────

_CACHE_TTL_SECONDS = 3600  # 1 hour

_cache: dict[str, dict] = {}  # keyed by symbol or "_macro"


def _cache_get(key: str) -> Optional[list[dict]]:
    entry = _cache.get(key)
    if entry and (time.monotonic() - entry["fetched_at"]) < _CACHE_TTL_SECONDS:
        return entry["events"]
    return None


def _cache_set(key: str, events: list[dict]) -> None:
    _cache[key] = {"events": events, "fetched_at": time.monotonic()}


# ── Hardcoded FOMC dates 2025-2026 ────────────────────────────────────────────

_FOMC_DATES_2025_2026: list[str] = [
    "2025-01-29",
    "2025-03-19",
    "2025-05-07",
    "2025-06-18",
    "2025-07-30",
    "2025-09-17",
    "2025-10-29",
    "2025-12-10",
    "2026-01-28",
    "2026-03-18",
    "2026-04-29",
    "2026-06-17",
    "2026-07-29",
    "2026-09-16",
    "2026-10-28",
    "2026-12-09",
]


def _fomc_events(horizon_dt: datetime) -> list[dict]:
    """Return upcoming FOMC events within horizon."""
    now = datetime.now(timezone.utc)
    events = []
    for d in _FOMC_DATES_2025_2026:
        dt = datetime.strptime(d, "%Y-%m-%d").replace(hour=14, minute=0, tzinfo=timezone.utc)
        if now <= dt <= horizon_dt:
            events.append({
                "event_type": "fomc",
                "symbol": None,
                "event_ts": dt.isoformat(),
                "source": "hardcoded",
            })
    return events


# ── NFP: 1st Friday of each month ────────────────────────────────────────────

def _first_friday(year: int, month: int) -> date:
    d = date(year, month, 1)
    # weekday(): Monday=0, Friday=4
    days_until_friday = (4 - d.weekday()) % 7
    return d + timedelta(days=days_until_friday)


# ── CPI: typically 2nd Wednesday of each month ───────────────────────────────

def _second_wednesday(year: int, month: int) -> date:
    d = date(year, month, 1)
    days_until_wed = (2 - d.weekday()) % 7
    first_wed = d + timedelta(days=days_until_wed)
    return first_wed + timedelta(weeks=1)


# ── PCE: last Friday of each month ───────────────────────────────────────────

def _last_friday(year: int, month: int) -> date:
    # Go to first of next month, step back to find last Friday
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    d = next_month - timedelta(days=1)
    while d.weekday() != 4:
        d -= timedelta(days=1)
    return d


def _macro_schedule_events(horizon_dt: datetime) -> list[dict]:
    """Generate CPI/NFP/PCE events for the next ~90 days."""
    now = datetime.now(timezone.utc)
    events = []
    # Cover current month + 3 more
    for delta_months in range(4):
        ref = now + timedelta(days=delta_months * 30)
        year, month = ref.year, ref.month

        releases: list[tuple[str, date, int]] = [
            ("nfp", _first_friday(year, month), 8),    # 8:30 AM ET
            ("cpi", _second_wednesday(year, month), 8),
            ("pce", _last_friday(year, month), 8),
        ]
        for event_type, rel_date, hour in releases:
            dt = datetime(rel_date.year, rel_date.month, rel_date.day, hour + 5, 30, tzinfo=timezone.utc)  # 8:30 ET = 13:30 UTC
            if now <= dt <= horizon_dt:
                events.append({
                    "event_type": event_type,
                    "symbol": None,
                    "event_ts": dt.isoformat(),
                    "source": "computed_schedule",
                })

    return events


def _polygon_earnings(symbol: str, horizon_dt: datetime) -> list[dict]:
    """Fetch earnings dates from Polygon.io if POLYGON_API_KEY is set."""
    api_key = os.getenv("POLYGON_API_KEY", "")
    if not api_key:
        return []

    now = datetime.now(timezone.utc)
    url = "https://api.polygon.io/v3/reference/tickers/events"
    params = {
        "ticker": symbol,
        "apiKey": api_key,
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code != 200:
            return []
        # Polygon earnings endpoint
        url2 = f"https://api.polygon.io/vX/reference/financials"
        params2 = {
            "ticker": symbol,
            "limit": 5,
            "apiKey": api_key,
            "order": "asc",
        }
        resp2 = requests.get(url2, params=params2, timeout=10)
        if resp2.status_code != 200:
            return []
        data = resp2.json().get("results", [])
        events = []
        for item in data:
            filing_date = item.get("filing_date") or item.get("period_of_report_date")
            if filing_date:
                dt = datetime.strptime(filing_date[:10], "%Y-%m-%d").replace(
                    hour=16, minute=0, tzinfo=timezone.utc
                )
                if now <= dt <= horizon_dt:
                    events.append({
                        "event_type": "earnings",
                        "symbol": symbol,
                        "event_ts": dt.isoformat(),
                        "source": "polygon",
                    })
        return events
    except Exception as exc:
        logger.debug("Polygon earnings fetch failed for %s: %s", symbol, exc)
        return []


def _alpaca_earnings(symbol: str, horizon_dt: datetime) -> list[dict]:
    """Fetch earnings from Alpaca News API as a fallback."""
    api_key = os.getenv("ALPACA_API_KEY", "")
    api_secret = os.getenv("ALPACA_SECRET_KEY", "")
    if not api_key:
        return []

    base_url = os.getenv("ALPACA_BASE_URL", "https://data.alpaca.markets")
    url = f"{base_url}/v1beta1/news"
    now = datetime.now(timezone.utc)
    params = {
        "symbols": symbol,
        "start": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end": horizon_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "limit": 20,
        "include_content": "false",
    }
    headers = {
        "APCA-API-KEY-ID": api_key,
        "APCA-API-SECRET-KEY": api_secret,
    }
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        if resp.status_code != 200:
            return []
        news = resp.json().get("news", [])
        events = []
        for article in news:
            headline = (article.get("headline") or "").lower()
            if "earnings" in headline or "quarterly results" in headline or "eps" in headline:
                created_at = article.get("created_at", "")
                try:
                    dt = datetime.strptime(created_at[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
                    events.append({
                        "event_type": "earnings",
                        "symbol": symbol,
                        "event_ts": dt.isoformat(),
                        "source": "alpaca_news",
                    })
                except Exception:
                    pass
        return events
    except Exception as exc:
        logger.debug("Alpaca news earnings fetch failed for %s: %s", symbol, exc)
        return []


# ── Public API ────────────────────────────────────────────────────────────────

def get_upcoming_catalysts(symbol: str = "", hours_ahead: int = 168) -> list[dict]:
    """
    Return upcoming catalyst events for the given symbol within `hours_ahead` hours.
    Includes macro (FOMC/CPI/NFP/PCE) and earnings for the symbol.
    Results cached in-memory for 1 hour.
    """
    cache_key = f"{symbol or '_macro'}_{hours_ahead}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    horizon_dt = datetime.now(timezone.utc) + timedelta(hours=hours_ahead)
    events: list[dict] = []

    # Always include macro events
    macro_key = f"_macro_{hours_ahead}"
    macro_cached = _cache_get(macro_key)
    if macro_cached is not None:
        events.extend(macro_cached)
    else:
        macro_events = _fomc_events(horizon_dt) + _macro_schedule_events(horizon_dt)
        _cache_set(macro_key, macro_events)
        events.extend(macro_events)

    # Symbol-specific earnings
    if symbol:
        earn_key = f"earnings_{symbol}_{hours_ahead}"
        earn_cached = _cache_get(earn_key)
        if earn_cached is not None:
            events.extend(earn_cached)
        else:
            earnings = _polygon_earnings(symbol, horizon_dt)
            if not earnings:
                earnings = _alpaca_earnings(symbol, horizon_dt)
            _cache_set(earn_key, earnings)
            events.extend(earnings)

    # Deduplicate by (event_type, event_ts, symbol) and sort
    seen: set = set()
    unique: list[dict] = []
    for e in events:
        key = (e.get("event_type"), e.get("event_ts"), e.get("symbol"))
        if key not in seen:
            seen.add(key)
            unique.append(e)

    unique.sort(key=lambda x: x.get("event_ts") or "")
    _cache_set(cache_key, unique)
    return unique


def is_blackout(symbol: str, profile_config: dict) -> tuple[bool, str]:
    """
    Returns (True, reason) if any upcoming catalyst blocks new entries right now.
    Uses profile_config.catalyst_gates for blackout configuration.
    """
    catalyst_gates = profile_config.get("catalyst_gates") or []
    gate_cfg = catalyst_gates[0] if catalyst_gates else {}
    blackout_types: list[str] = gate_cfg.get("blackout_minutes_around", [])
    minutes_before: int = gate_cfg.get("minutes_before", 5)
    minutes_after: int = gate_cfg.get("minutes_after", 5)

    # Default macro blackout if not configured
    if not blackout_types:
        blackout_types = ["fomc", "cpi", "nfp", "pce"]
        minutes_before = 30
        minutes_after = 15

    now = datetime.now(timezone.utc)
    catalysts = get_upcoming_catalysts(symbol=symbol, hours_ahead=168)

    for evt in catalysts:
        evt_type = (evt.get("event_type") or "").lower()
        evt_ts_str = evt.get("event_ts")
        if not evt_ts_str:
            continue
        try:
            evt_dt = datetime.fromisoformat(evt_ts_str.replace("Z", "+00:00"))
        except Exception:
            continue

        if evt_type in [t.lower() for t in blackout_types]:
            delta_minutes = (evt_dt - now).total_seconds() / 60
            if -minutes_after <= delta_minutes <= minutes_before:
                return True, f"Catalyst blackout: {evt_type} at {evt_ts_str}"

        if evt_type == "earnings" and evt.get("symbol") == symbol:
            delta_min = abs((evt_dt - now).total_seconds() / 60)
            if delta_min <= 30:
                return True, f"Earnings blackout for {symbol} at {evt_ts_str}"

    return False, ""
