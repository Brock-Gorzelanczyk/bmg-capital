"""
Token Unlock Monitor — upcoming cliff unlock sell-pressure tracker.

Large cliff unlocks (>5% of supply releasing on a single date) historically
create pre-unlock price suppression and post-unlock dumps. This module:
  1. Fetches upcoming unlocks from DeFiLlama's unlock tracker
  2. Computes a sell_pressure_score for each upcoming event
  3. Provides a gate function (should_suppress_buy) used by candidate strategies

Data source: https://api.llama.fi/unlocks (DeFiLlama unlock API)
Cache TTL: 6 hours (unlock schedules rarely change intraday).
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 21600  # 6 hours

_cache: dict = {
    "unlocks": None,
    "fetched_at": 0.0,
}

_LLAMA_UNLOCKS_URL = "https://api.llama.fi/unlocks"


def _parse_unlock_type(event: dict) -> str:
    """Extract unlock type from DeFiLlama event structure."""
    category = event.get("category", "").lower()
    if "cliff" in category:
        return "cliff"
    if "linear" in category or "vesting" in category:
        return "linear"
    return "other"


def _compute_sell_pressure(unlock_pct_supply: float, unlock_type: str) -> float:
    """
    Compute sell pressure score 0-1.
    Cliffs get 2× multiplier vs. linear vesting.
    """
    base = min(unlock_pct_supply / 10.0, 1.0)
    if unlock_type == "cliff":
        return min(base * 2.0, 1.0)
    return base


def _fetch_unlocks_raw() -> list[dict]:
    """Fetch raw unlock data from DeFiLlama."""
    try:
        resp = requests.get(_LLAMA_UNLOCKS_URL, timeout=15)
        if resp.status_code != 200:
            logger.warning("[token_unlock] DeFiLlama unlocks returned %d", resp.status_code)
            return []
        data = resp.json()
        # DeFiLlama returns a list of protocol objects with unlock events
        if isinstance(data, list):
            return data
        # Some versions wrap in {"protocols": [...]}
        return data.get("protocols", [])
    except Exception as exc:
        logger.warning("[token_unlock] DeFiLlama unlocks fetch failed: %s", exc)
        return []


def get_upcoming_unlocks(days_ahead: int = 14) -> list[dict]:
    """
    Fetch and return upcoming token unlock events within `days_ahead` days.

    Each returned dict contains:
        symbol            : str  (token ticker)
        unlock_date       : str  (ISO date string)
        unlock_pct_supply : float (% of total supply unlocking)
        unlock_type       : str  ("cliff" | "linear" | "other")
        days_until        : int
        sell_pressure_score: float (0-1; higher = more sell pressure)

    Cached for 6 hours. Returns [] on any failure.

    Parameters
    ----------
    days_ahead : int
        Only include unlocks within this many days from now.
    """
    now_ts = time.monotonic()

    if _cache["unlocks"] is not None and (now_ts - _cache["fetched_at"]) < _CACHE_TTL_SECONDS:
        cached = _cache["unlocks"]
        now_dt = datetime.now(timezone.utc)
        return [u for u in cached if u["days_until"] <= days_ahead and u["days_until"] >= 0]

    try:
        raw_protocols = _fetch_unlocks_raw()
        if not raw_protocols:
            _cache["unlocks"] = []
            _cache["fetched_at"] = now_ts
            return []

        now_dt = datetime.now(timezone.utc)
        upcoming: list[dict] = []

        for protocol in raw_protocols:
            symbol = protocol.get("symbol", "").upper()
            if not symbol:
                continue

            total_supply = protocol.get("totalLocked", None) or protocol.get("maxSupply", None)
            events = protocol.get("events", [])

            for event in events:
                try:
                    # DeFiLlama events have a "timestamp" (unix) or "date" field
                    ts = event.get("timestamp") or event.get("date")
                    if ts is None:
                        continue
                    if isinstance(ts, (int, float)):
                        event_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                    else:
                        event_dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))

                    days_until = (event_dt.date() - now_dt.date()).days
                    if days_until < 0 or days_until > days_ahead:
                        continue

                    unlock_amount = float(event.get("noOfTokens", 0) or event.get("amount", 0))
                    unlock_pct = 0.0
                    if total_supply and float(total_supply) > 0:
                        unlock_pct = round((unlock_amount / float(total_supply)) * 100.0, 3)
                    else:
                        # Use protocol's own unlock percentage if provided
                        unlock_pct = float(event.get("percentUnlocked", 0) or 0)

                    unlock_type = _parse_unlock_type(event)
                    sell_pressure = _compute_sell_pressure(unlock_pct, unlock_type)

                    upcoming.append({
                        "symbol": symbol,
                        "unlock_date": event_dt.date().isoformat(),
                        "unlock_pct_supply": unlock_pct,
                        "unlock_type": unlock_type,
                        "days_until": days_until,
                        "sell_pressure_score": round(sell_pressure, 4),
                    })
                except Exception as parse_exc:
                    logger.debug("[token_unlock] Error parsing event for %s: %s", symbol, parse_exc)
                    continue

        # Sort by days_until ascending
        upcoming.sort(key=lambda x: x["days_until"])

        # Cache all upcoming (not just within current days_ahead)
        _cache["unlocks"] = upcoming
        _cache["fetched_at"] = now_ts

        logger.info(
            "[token_unlock] Fetched %d upcoming unlocks within %d days",
            len(upcoming), days_ahead,
        )
        return upcoming

    except Exception as exc:
        logger.warning("[token_unlock] get_upcoming_unlocks failed: %s", exc)
        _cache["unlocks"] = []
        _cache["fetched_at"] = now_ts
        return []


def should_suppress_buy(symbol: str, days_ahead: int = 14) -> bool:
    """
    Returns True if the given symbol has a CLIFF unlock of >5% supply
    within `days_ahead` days. Used to suppress new long entries.

    Case-insensitive symbol match.

    Parameters
    ----------
    symbol    : token ticker (e.g. "ARB", "OP", "arb")
    days_ahead: look-ahead window in days
    """
    symbol_upper = symbol.upper()
    try:
        unlocks = get_upcoming_unlocks(days_ahead=days_ahead)
        for unlock in unlocks:
            if unlock.get("symbol", "").upper() != symbol_upper:
                continue
            if unlock.get("unlock_type") != "cliff":
                continue
            if unlock.get("unlock_pct_supply", 0.0) > 5.0:
                logger.info(
                    "[token_unlock] Suppressing buy for %s: cliff %.1f%% in %d days",
                    symbol,
                    unlock["unlock_pct_supply"],
                    unlock["days_until"],
                )
                return True
        return False
    except Exception as exc:
        logger.warning("[token_unlock] should_suppress_buy failed for %s: %s", symbol, exc)
        return False  # Fail open — don't suppress if data unavailable
