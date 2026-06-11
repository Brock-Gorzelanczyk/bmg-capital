"""
CANDIDATE — read-only altdata module. Not scheduled.
FRED High Yield OAS spread regime detector. Fail-open.
Reference: ICE BofA US High Yield Index OAS (BAMLH0A0HYM2)
"""
from __future__ import annotations

import logging
import os
import time

logger = logging.getLogger(__name__)

HY_SPREAD_SERIES = "BAMLH0A0HYM2"
HY_GREEN_MAX = 400
HY_YELLOW_MAX = 600
HY_RED_MIN = 600
HY_4W_CHANGE_YELLOW = 75
HY_4W_CHANGE_RED = 150

_cache: dict = {}
CACHE_TTL_SECONDS = 86400

_NEUTRAL_RESULT: dict = {
    "hy_spread": 350.0,
    "hy_4w_change": 0.0,
    "state": "green",
    "equity_multiplier": 1.0,
    "reason": "FRED unavailable — defaulting green (fail-open)",
    "data_date": "unavailable",
}


def get_credit_regime() -> dict:
    """Return HY spread regime dict.

    Keys: hy_spread, hy_4w_change, state (green|yellow|red),
          equity_multiplier (1.0|0.75|0.35), reason, data_date.
    Fail-open: returns green if FRED is unreachable.
    Requires FRED_API_KEY env var (free at fred.stlouisfed.org).
    """
    now = time.time()
    if _cache.get("ts") and now - _cache["ts"] < CACHE_TTL_SECONDS:
        return _cache["data"]
    try:
        result = _fetch_fred_credit_data()
    except Exception as exc:
        logger.warning("credit_spread_signal: FRED fetch failed: %s", exc)
        return _NEUTRAL_RESULT
    _cache["data"] = result
    _cache["ts"] = now
    return result


def _fetch_fred_credit_data() -> dict:
    import datetime
    import pandas_datareader.data as web

    api_key = os.getenv("FRED_API_KEY")
    start = datetime.datetime.now() - datetime.timedelta(days=90)
    kwargs = {}
    if api_key:
        kwargs["api_key"] = api_key
    hy = web.DataReader(HY_SPREAD_SERIES, "fred", start, **kwargs).dropna()
    if len(hy) < 25:
        raise RuntimeError(f"Insufficient FRED data: {len(hy)} rows")
    current_spread = float(hy.iloc[-1].values[0])
    spread_20d_ago = float(hy.iloc[-20].values[0]) if len(hy) >= 20 else current_spread
    change_4w = current_spread - spread_20d_ago
    data_date = str(hy.index[-1].date())
    if current_spread > HY_RED_MIN or change_4w > HY_4W_CHANGE_RED:
        state, multiplier = "red", 0.35
    elif current_spread > HY_GREEN_MAX or change_4w > HY_4W_CHANGE_YELLOW:
        state, multiplier = "yellow", 0.75
    else:
        state, multiplier = "green", 1.0
    return {
        "hy_spread": current_spread,
        "hy_4w_change": change_4w,
        "state": state,
        "equity_multiplier": multiplier,
        "reason": f"HY_OAS={current_spread:.0f}bps 4w_chg={change_4w:+.0f}bps — credit {state}",
        "data_date": data_date,
    }
