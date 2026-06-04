"""
Gamma Exposure (GEX) Dealer Positioning — Weekend 7, Module 17.

GEX = Σ(call_gamma × OI) - Σ(put_gamma × OI) per ticker

Positive GEX: dealers are long gamma → they buy dips / sell rips
              → vol-dampening, mean-reverting regime
Negative GEX: dealers are short gamma → they follow momentum
              → vol-amplifying, trending/breakout regime

Strategy gates:
  positive GEX on SPY → prefer mean-reversion strategies (RSI, BB, pairs)
  negative GEX on SPY → prefer momentum strategies (ORB, VWAP breakout)

Data: Polygon options chain (paid) or Unusual Whales / SpotGamma APIs.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# Thresholds for regime classification
GEX_POSITIVE_STRONG = 500_000_000     # $500M gamma — strongly pinned
GEX_POSITIVE_MILD = 100_000_000       # $100M
GEX_NEGATIVE_MILD = -100_000_000
GEX_NEGATIVE_STRONG = -500_000_000   # $-500M — very explosive


@dataclass
class GEXSnapshot:
    symbol: str
    gex_usd: float              # net gamma exposure in USD
    call_gamma_usd: float
    put_gamma_usd: float
    regime: str                 # "pinned" | "mild_positive" | "neutral" | "mild_negative" | "explosive"
    prefers_mean_reversion: bool
    prefers_momentum: bool
    data_source: str


def classify_gex(gex_usd: float) -> tuple[str, bool, bool]:
    """Return (regime_label, prefers_mean_reversion, prefers_momentum)."""
    if gex_usd >= GEX_POSITIVE_STRONG:
        return "pinned", True, False
    elif gex_usd >= GEX_POSITIVE_MILD:
        return "mild_positive", True, False
    elif gex_usd <= GEX_NEGATIVE_STRONG:
        return "explosive", False, True
    elif gex_usd <= GEX_NEGATIVE_MILD:
        return "mild_negative", False, True
    else:
        return "neutral", True, True  # neutral → allow both


def compute_gex_from_chain(
    options_chain: list[dict],
    spot_price: float,
    moneyness_range: float = 0.15,  # only include strikes within ±15% of spot
) -> float:
    """
    Compute GEX from raw options chain data.

    Parameters
    ----------
    options_chain : list of dicts with keys:
        strike, option_type (call/put), gamma, open_interest
    spot_price : current underlying price
    moneyness_range : filter to strikes within this % of spot

    Returns
    -------
    GEX in dollar terms (gamma × OI × spot² × 100 per contract)
    """
    gex = 0.0
    lo = spot_price * (1 - moneyness_range)
    hi = spot_price * (1 + moneyness_range)

    for opt in options_chain:
        strike = float(opt.get("strike", 0))
        if strike < lo or strike > hi:
            continue

        gamma = float(opt.get("gamma", 0))
        oi = float(opt.get("open_interest", 0))
        opt_type = str(opt.get("option_type", "")).lower()

        # Dollar gamma: gamma × OI × spot² × 100 (per standard 100-share contract)
        dollar_gamma = gamma * oi * spot_price ** 2 * 100

        if opt_type in ("call", "c"):
            gex += dollar_gamma
        elif opt_type in ("put", "p"):
            gex -= dollar_gamma

    return gex


def fetch_polygon_gex(symbol: str, spot_price: float) -> Optional[float]:
    """
    Fetch options chain from Polygon and compute GEX.
    Requires POLYGON_API_KEY with options access.
    """
    try:
        import requests
        api_key = os.getenv("POLYGON_API_KEY", "")
        if not api_key:
            return None

        url = f"https://api.polygon.io/v3/snapshot/options/{symbol}"
        params = {"apiKey": api_key, "limit": 250}
        resp = requests.get(url, params=params, timeout=5)
        if resp.status_code != 200:
            logger.debug("[gex] Polygon error %d for %s", resp.status_code, symbol)
            return None

        data = resp.json().get("results", [])
        chain = [
            {
                "strike": r.get("details", {}).get("strike_price", 0),
                "option_type": r.get("details", {}).get("contract_type", ""),
                "gamma": r.get("greeks", {}).get("gamma", 0),
                "open_interest": r.get("open_interest", 0),
            }
            for r in data
        ]
        return compute_gex_from_chain(chain, spot_price)
    except Exception as exc:
        logger.debug("[gex] Polygon fetch error for %s: %s", symbol, exc)
        return None


def get_gex_snapshot(symbol: str, spot_price: float) -> GEXSnapshot:
    """
    Get GEX snapshot for symbol. Falls back to neutral if no data.
    """
    gex = fetch_polygon_gex(symbol, spot_price)

    if gex is None:
        # Return neutral when data unavailable
        return GEXSnapshot(
            symbol=symbol,
            gex_usd=0.0,
            call_gamma_usd=0.0,
            put_gamma_usd=0.0,
            regime="neutral",
            prefers_mean_reversion=True,
            prefers_momentum=True,
            data_source="default_neutral",
        )

    regime, prefers_mr, prefers_mom = classify_gex(gex)
    logger.info("[gex] %s gex=$%.0fM regime=%s", symbol, gex / 1e6, regime)

    return GEXSnapshot(
        symbol=symbol,
        gex_usd=round(gex, 0),
        call_gamma_usd=max(0, gex),
        put_gamma_usd=min(0, gex),
        regime=regime,
        prefers_mean_reversion=prefers_mr,
        prefers_momentum=prefers_mom,
        data_source="polygon",
    )


# Cache — refresh every 30 minutes
_cache: dict[str, tuple[float, GEXSnapshot]] = {}  # symbol → (expires_at, snapshot)
_CACHE_TTL = 1800


def get_cached_gex(symbol: str, spot_price: float) -> GEXSnapshot:
    import time
    cached = _cache.get(symbol)
    if cached and time.time() < cached[0]:
        return cached[1]
    snap = get_gex_snapshot(symbol, spot_price)
    _cache[symbol] = (time.time() + _CACHE_TTL, snap)
    return snap
