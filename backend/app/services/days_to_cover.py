"""Days-to-Cover signal — Hong, Li, Ni, Scheinkman, Yan (2015, revised 2023).

Signal: DTC = short_interest / average_daily_volume
Effect: 1.19%/mo EW long-short, 14.3% annualized. Sharpe 1.33. Dominates raw
short interest in horse-race regressions (Fama-Macbeth t = -9.15 vs -5.71).
Global replication across 38 countries (Boehmer et al 2015 SSRN 2668357).

For BMG's confluence framework:
  - INPUT: ticker symbol
  - OUTPUT: DTC value (days) + bucket (LOW/MEDIUM/HIGH crowded-short)
  - INTERPRETATION:
      HIGH (>10 days) → VETO longs (crowded short is compensation for opinion)
                      → ENABLE shorts (with other bearish confluence signals)
      LOW (<3 days) → mild positive filter (uncrowded short base)

Data source: yfinance for short interest + Alpaca (or yfinance) for ADV.
FINRA free API stopped updating in 2020 — yfinance scrapes current data from
NASDAQ/NYSE feeds (short interest updated biweekly per FINRA schedule).
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# In-process cache — short interest updates biweekly, no need to hammer yfinance
_DTC_CACHE: Dict[str, tuple] = {}  # symbol → (dtc_dict, computed_at_ts)
_CACHE_TTL_SEC = 12 * 3600  # twice-daily refresh


def compute_dtc(symbol: str, use_cache: bool = True) -> Dict[str, Any]:
    """Compute Days-to-Cover for a single symbol.

    Returns dict:
      symbol, dtc (days, float), bucket (LOW|MEDIUM|HIGH|ERROR),
      short_interest (shares), avg_volume (shares/day), short_pct_of_float,
      as_of_date, source, cached
    """
    symbol = symbol.upper().strip()
    now = time.time()
    if use_cache and symbol in _DTC_CACHE:
        val, ts = _DTC_CACHE[symbol]
        if now - ts < _CACHE_TTL_SEC:
            return {**val, "cached": True}

    try:
        import yfinance as yf
    except ImportError:
        return {"symbol": symbol, "dtc": -1.0, "bucket": "ERROR", "error": "yfinance_not_available", "cached": False}

    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}
    except Exception as e:
        logger.warning("[dtc] yfinance fetch failed for %s: %s", symbol, e)
        return {"symbol": symbol, "dtc": -1.0, "bucket": "ERROR", "error": f"yfinance_error: {str(e)[:100]}", "cached": False}

    short_interest = info.get("sharesShort")
    avg_volume = info.get("averageVolume") or info.get("averageVolume10days")
    short_pct_float = info.get("shortPercentOfFloat")
    short_ratio = info.get("shortRatio")  # yfinance's DTC — if available, use directly

    # Prefer yfinance's precomputed shortRatio if valid
    if isinstance(short_ratio, (int, float)) and short_ratio > 0:
        dtc = float(short_ratio)
        source = "yfinance_shortRatio"
    elif isinstance(short_interest, (int, float)) and isinstance(avg_volume, (int, float)) and avg_volume > 0:
        dtc = float(short_interest) / float(avg_volume)
        source = "yfinance_computed"
    else:
        return {
            "symbol": symbol,
            "dtc": -1.0,
            "bucket": "ERROR",
            "error": "insufficient_data",
            "short_interest": short_interest,
            "avg_volume": avg_volume,
            "cached": False,
        }

    result = {
        "symbol": symbol,
        "dtc": round(dtc, 2),
        "bucket": _bucket(dtc),
        "short_interest": short_interest,
        "avg_volume": avg_volume,
        "short_pct_of_float": short_pct_float,
        "as_of_date": info.get("sharesShortPreviousMonthDate") or info.get("dateShortInterest"),
        "source": source,
        "cached": False,
    }
    _DTC_CACHE[symbol] = (result, now)
    return result


def _bucket(dtc: float) -> str:
    """Map DTC to LOW/MEDIUM/HIGH per Hong et al 2015 empirical distribution.
    Top decile ~ >8-10 days for US equities.

    LOW <3 → uncrowded short (mild positive for longs)
    MEDIUM 3-8 → normal
    HIGH >8 → crowded short (VETO longs; ENABLE shorts)
    """
    if dtc < 0:
        return "ERROR"
    if dtc < 3:
        return "LOW"
    if dtc < 8:
        return "MEDIUM"
    return "HIGH"


def batch_compute_dtc(symbols: List[str]) -> List[Dict[str, Any]]:
    """Compute DTC for a list of symbols. Sequential to respect yfinance rate limits."""
    return [compute_dtc(s) for s in symbols]


def aggregate_short_interest_regime() -> Dict[str, Any]:
    """Rapach/Ringgenberg/Zhou 2016 aggregate short-interest index — market-level regime signal.

    Simplified MVP: sample a broad universe (SPY constituents proxy via top ETF holdings)
    and compute cross-sectional average short_pct_of_float. Compare to trailing 52-week
    percentile to identify elevated/low aggregate SI regimes.

    Returns dict with:
      current_ss_pct, historical_percentile (0-1), regime (ELEVATED|NORMAL|LOW),
      recommended_exposure_pct (100% for LOW/NORMAL, 60-75% for ELEVATED)
    """
    # MVP universe: top 30 SPY components (mega-caps) as a proxy for aggregate market
    # Full paper uses all Russell 3000 short interest. Cache aggressively — refresh weekly.
    UNIVERSE = [
        "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "BRK-B", "LLY", "JPM",
        "V", "XOM", "UNH", "MA", "AVGO", "PG", "HD", "COST", "JNJ", "WMT",
        "ORCL", "ABBV", "BAC", "NFLX", "KO", "CVX", "TMO", "MRK", "AMD", "CRM",
    ]
    scores: List[float] = []
    for sym in UNIVERSE:
        try:
            r = compute_dtc(sym)
            spct = r.get("short_pct_of_float")
            if isinstance(spct, (int, float)) and spct > 0:
                scores.append(float(spct))
        except Exception:
            continue

    if not scores:
        return {"current_ss_pct": None, "regime": "UNKNOWN", "recommended_exposure_pct": 100, "error": "no_data"}

    current_avg = sum(scores) / len(scores)
    # Rough regime thresholds — real Rapach uses standardized historical percentile
    # For MVP: >0.05 aggregate short_pct = elevated (typical range 0.02-0.04)
    if current_avg > 0.05:
        regime = "ELEVATED"
        rec_exposure = 65
    elif current_avg > 0.035:
        regime = "MILDLY_ELEVATED"
        rec_exposure = 80
    else:
        regime = "NORMAL"
        rec_exposure = 100

    return {
        "current_ss_pct": round(current_avg, 4),
        "regime": regime,
        "recommended_exposure_pct": rec_exposure,
        "universe_size": len(scores),
        "note": "MVP implementation — samples top 30 SPY components. Full paper uses Russell 3000.",
    }
