"""
Pull live option chain from Alpaca data API.
Requires a paid Alpaca options data subscription.
Gracefully degrades to synthetic chain (Black-Scholes estimated) when API is unavailable.
"""
from __future__ import annotations

import logging
import math
import os
from datetime import date

logger = logging.getLogger(__name__)

# Set True once Alpaca options data subscription is confirmed active
DATA_SOURCE_LIVE = False


def get_chain_alpaca(
    symbol: str,
    expiry_date: str,  # "YYYY-MM-DD"
    token: str = "",
    base_url: str = "https://data.alpaca.markets",
) -> dict:
    """
    Fetch option chain from Alpaca. Returns {} on any error.
    Response shape: {strike_str: {"call_bid", "call_ask", "put_bid", "put_ask", "delta_c", "delta_p"}}
    """
    token = token or os.getenv("ALPACA_API_KEY", "")
    if not token:
        logger.debug("[chain_fetcher] no ALPACA_API_KEY — skipping live chain fetch")
        return {}
    try:
        import httpx
        resp = httpx.get(
            f"{base_url}/v2/options/contracts",
            params={"underlying_symbols": symbol, "expiration_date": expiry_date, "limit": 200},
            headers={"APCA-API-KEY-ID": token, "APCA-API-SECRET-KEY": os.getenv("ALPACA_SECRET_KEY", "")},
            timeout=10,
        )
        if resp.status_code == 403:
            logger.warning("[chain_fetcher] Alpaca options API returned 403 — paid subscription required. Using synthetic chain.")
            return {}
        resp.raise_for_status()
        contracts = resp.json().get("option_contracts", [])
        chain: dict = {}
        for c in contracts:
            strike = str(c.get("strike_price", ""))
            if not strike:
                continue
            chain.setdefault(strike, {})
            if c.get("type") == "call":
                chain[strike]["call_bid"] = c.get("close_price", 0)
                chain[strike]["call_ask"] = c.get("close_price", 0)
                chain[strike]["delta_c"]  = c.get("delta", None)
            elif c.get("type") == "put":
                chain[strike]["put_bid"] = c.get("close_price", 0)
                chain[strike]["put_ask"] = c.get("close_price", 0)
                chain[strike]["delta_p"] = c.get("delta", None)
        return chain
    except Exception as exc:
        logger.warning("[chain_fetcher] live chain fetch failed for %s: %s", symbol, exc)
        return {}


def get_synthetic_chain(S: float, T: float, r: float = 0.05, sigma: float = 0.20) -> dict:
    """
    Synthetic chain via Black-Scholes for strikes at ±5% to ±30% OTM (2.5% steps).
    Used when live data is unavailable.
    """
    from .greeks import call_price, put_price, call_delta, put_delta
    chain = {}
    for pct in [i * 0.025 for i in range(-12, 13)]:  # -30% to +30%
        K = round(S * (1 + pct), 2)
        if K <= 0:
            continue
        cp = call_price(S, K, T, r, sigma)
        pp = put_price(S, K, T, r, sigma)
        cd = call_delta(S, K, T, r, sigma)
        pd = put_delta(S, K, T, r, sigma)
        chain[str(K)] = {
            "call_bid": round(cp * 0.99, 4), "call_ask": round(cp * 1.01, 4),
            "put_bid":  round(pp * 0.99, 4), "put_ask":  round(pp * 1.01, 4),
            "delta_c": round(cd, 4), "delta_p": round(pd, 4),
        }
    return chain


def get_chain_or_estimate(
    symbol: str, expiry_date: str, S: float, T: float, r: float = 0.05, sigma: float = 0.20
) -> dict:
    """Try live Alpaca chain; fall back to synthetic if unavailable."""
    if DATA_SOURCE_LIVE:
        chain = get_chain_alpaca(symbol, expiry_date)
        if chain:
            return chain
    return get_synthetic_chain(S, T, r, sigma)
