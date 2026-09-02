"""Alpaca options data helpers — chain snapshots, Black-Scholes greeks,
contract picker (nearest-delta at target DTE).

Alpaca provides free options data with a paper/live account. This wraps
the raw API into functions we need for the setup scanner.
"""
from __future__ import annotations

import math
import os
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", "..", "backend", ".env"))

ALPACA_BASE = "https://paper-api.alpaca.markets"
DATA_BASE = "https://data.alpaca.markets"


def _headers() -> dict:
    return {
        "APCA-API-KEY-ID": os.getenv("ALPACA_API_KEY", ""),
        "APCA-API-SECRET-KEY": os.getenv("ALPACA_SECRET_KEY", ""),
    }


# ────────────────────────────────────────────────────────────────────────────
# Underlying data
# ────────────────────────────────────────────────────────────────────────────

def get_bars(symbol: str, timeframe: str = "1Day", limit: int = 200,
             start: Optional[str] = None) -> list[dict]:
    """Fetch OHLCV bars for an equity/ETF.
    timeframe: '1Min', '5Min', '15Min', '1Hour', '1Day'
    """
    params = {"timeframe": timeframe, "limit": limit, "adjustment": "raw"}
    if start:
        params["start"] = start
    r = requests.get(f"{DATA_BASE}/v2/stocks/{symbol}/bars", headers=_headers(),
                     params=params, timeout=15)
    r.raise_for_status()
    return r.json().get("bars", [])


def get_latest_quote(symbol: str) -> dict:
    r = requests.get(f"{DATA_BASE}/v2/stocks/{symbol}/quotes/latest",
                     headers=_headers(), timeout=10)
    r.raise_for_status()
    return r.json().get("quote", {})


def get_latest_trade(symbol: str) -> dict:
    r = requests.get(f"{DATA_BASE}/v2/stocks/{symbol}/trades/latest",
                     headers=_headers(), timeout=10)
    r.raise_for_status()
    return r.json().get("trade", {})


# ────────────────────────────────────────────────────────────────────────────
# Options chain
# ────────────────────────────────────────────────────────────────────────────

def get_option_chain(underlying: str, expiration_date: str,
                     option_type: Optional[str] = None,
                     strike_gte: Optional[float] = None,
                     strike_lte: Optional[float] = None) -> dict:
    """Get chain snapshots for an underlying at a given expiration.

    option_type: 'call', 'put', or None for both
    Returns dict of {occ_symbol: snapshot}
    """
    params = {
        "feed": "indicative",
        "expiration_date": expiration_date,
    }
    if option_type:
        params["type"] = option_type
    if strike_gte is not None:
        params["strike_price_gte"] = strike_gte
    if strike_lte is not None:
        params["strike_price_lte"] = strike_lte
    r = requests.get(f"{DATA_BASE}/v1beta1/options/snapshots/{underlying}",
                     headers=_headers(), params=params, timeout=15)
    r.raise_for_status()
    return r.json().get("snapshots", {})


def get_expirations(underlying: str) -> list[str]:
    """Get available expiration dates for an underlying. Returns sorted list of 'YYYY-MM-DD'."""
    # Alpaca doesn't have a direct expirations endpoint — probe next 60 days
    today = date.today()
    exps = []
    for days_out in range(0, 90, 1):
        d = today + timedelta(days=days_out)
        # Options generally expire on Fridays (weeklies) + monthlies (3rd Fri)
        if d.weekday() != 4:  # not Friday
            continue
        # Probe with a small request
        snaps = get_option_chain(underlying, d.isoformat(),
                                 strike_gte=1, strike_lte=999999)
        if snaps:
            exps.append(d.isoformat())
        if len(exps) >= 12:
            break
    return exps


# ────────────────────────────────────────────────────────────────────────────
# Black-Scholes greeks (Alpaca returns None on some feeds, so compute ourselves)
# ────────────────────────────────────────────────────────────────────────────

def _cdf(x: float) -> float:
    """Standard normal CDF using erf."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def bs_greeks(spot: float, strike: float, dte_days: float, iv: float,
              option_type: str, risk_free: float = 0.05, div_yield: float = 0.0) -> dict:
    """Black-Scholes greeks for a European option.

    Returns dict with delta, gamma, theta (per day), vega (per 1% IV), rho.
    """
    if dte_days <= 0 or iv <= 0 or spot <= 0 or strike <= 0:
        return {"delta": None, "gamma": None, "theta": None, "vega": None, "rho": None,
                "d1": None, "d2": None, "intrinsic": max(0, (spot - strike) if option_type == "call" else (strike - spot)),
                "extrinsic": 0}

    T = dte_days / 365.0
    q = div_yield
    r = risk_free
    sigma = iv

    d1 = (math.log(spot / strike) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    exp_qT = math.exp(-q * T)
    exp_rT = math.exp(-r * T)

    if option_type.lower() == "call":
        price = spot * exp_qT * _cdf(d1) - strike * exp_rT * _cdf(d2)
        delta = exp_qT * _cdf(d1)
        rho = strike * T * exp_rT * _cdf(d2) / 100.0  # per 1% rate
    else:  # put
        price = strike * exp_rT * _cdf(-d2) - spot * exp_qT * _cdf(-d1)
        delta = -exp_qT * _cdf(-d1)
        rho = -strike * T * exp_rT * _cdf(-d2) / 100.0

    gamma = exp_qT * _pdf(d1) / (spot * sigma * math.sqrt(T))
    vega = spot * exp_qT * _pdf(d1) * math.sqrt(T) / 100.0  # per 1% IV
    theta = -(spot * sigma * exp_qT * _pdf(d1)) / (2 * math.sqrt(T))
    if option_type.lower() == "call":
        theta = (theta - r * strike * exp_rT * _cdf(d2) + q * spot * exp_qT * _cdf(d1)) / 365.0
    else:
        theta = (theta + r * strike * exp_rT * _cdf(-d2) - q * spot * exp_qT * _cdf(-d1)) / 365.0

    intrinsic = max(0.0, (spot - strike) if option_type.lower() == "call" else (strike - spot))
    return {
        "delta": round(delta, 4),
        "gamma": round(gamma, 5),
        "theta": round(theta, 4),  # per day
        "vega": round(vega, 4),    # per 1% IV
        "rho": round(rho, 4),
        "d1": round(d1, 4),
        "d2": round(d2, 4),
        "bs_price": round(price, 4),
        "intrinsic": round(intrinsic, 4),
    }


def implied_vol_from_price(spot: float, strike: float, dte_days: float, price: float,
                           option_type: str, risk_free: float = 0.05) -> Optional[float]:
    """Solve for IV given market price using bisection. Returns None if no solution."""
    if dte_days <= 0 or price <= 0 or spot <= 0 or strike <= 0:
        return None

    lo, hi = 0.001, 5.0  # 0.1% to 500%
    for _ in range(60):
        mid = (lo + hi) / 2.0
        bs = bs_greeks(spot, strike, dte_days, mid, option_type, risk_free)
        model_price = bs["bs_price"]
        if model_price is None:
            return None
        if model_price > price:
            hi = mid
        else:
            lo = mid
        if hi - lo < 1e-5:
            return round(mid, 4)
    return round((lo + hi) / 2.0, 4)


# ────────────────────────────────────────────────────────────────────────────
# Contract picker
# ────────────────────────────────────────────────────────────────────────────

def pick_contract_by_delta(underlying: str, spot: float,
                           target_dte: int, option_type: str,
                           target_delta: float,
                           dte_tolerance: int = 7) -> Optional[dict]:
    """Pick the option contract closest to target_delta at target_dte DTE.

    Returns dict with: occ_symbol, strike, expiration, bid, ask, mid, greeks.
    None if no viable chain found.
    """
    # Try to find an expiration close to target_dte
    today = date.today()
    target_exp = today + timedelta(days=target_dte)

    # Probe expirations within tolerance
    candidates_exp = []
    for offset in range(-dte_tolerance, dte_tolerance + 1):
        d = target_exp + timedelta(days=offset)
        if d.weekday() != 4:  # options normally expire Fridays
            continue
        if d < today:
            continue
        candidates_exp.append(d.isoformat())

    if not candidates_exp:
        return None

    # Sort by proximity to target
    candidates_exp.sort(key=lambda e: abs((date.fromisoformat(e) - target_exp).days))

    for exp_str in candidates_exp:
        # Get chain in a strike window around spot (±15% covers most of ATM/near-ATM)
        strike_lo = spot * 0.85
        strike_hi = spot * 1.15
        chain = get_option_chain(underlying, exp_str, option_type=option_type,
                                 strike_gte=strike_lo, strike_lte=strike_hi)
        if not chain:
            continue

        exp_date = date.fromisoformat(exp_str)
        dte = max(1, (exp_date - today).days)

        best = None
        best_delta_gap = float("inf")

        for occ_sym, snap in chain.items():
            lq = snap.get("latestQuote") or {}
            bid = float(lq.get("bp") or 0)
            ask = float(lq.get("ap") or 0)
            if bid <= 0 or ask <= 0:
                continue
            mid = (bid + ask) / 2.0

            # Parse strike from OCC symbol
            # Format: SYMBOL YYMMDD C/P NNNNNNNN (8-digit strike in 1/1000)
            try:
                strike = float(occ_sym[-8:]) / 1000.0
            except Exception:
                continue

            # Compute IV from mid, then greeks
            iv = implied_vol_from_price(spot, strike, dte, mid, option_type)
            if iv is None:
                continue
            greeks = bs_greeks(spot, strike, dte, iv, option_type)
            delta = greeks.get("delta")
            if delta is None:
                continue

            # For puts, target_delta is signed negative — accept both signs
            target_signed = -abs(target_delta) if option_type == "put" else abs(target_delta)
            gap = abs(delta - target_signed)
            if gap < best_delta_gap:
                best_delta_gap = gap
                best = {
                    "occ_symbol": occ_sym,
                    "underlying": underlying,
                    "expiration": exp_str,
                    "dte": dte,
                    "strike": strike,
                    "option_type": option_type,
                    "bid": bid,
                    "ask": ask,
                    "mid": round(mid, 4),
                    "iv": iv,
                    "spot": spot,
                    **greeks,
                }
        if best:
            return best

    return None


if __name__ == "__main__":
    # Smoke test
    print("SPY spot:", get_latest_trade("SPY").get("p"))
    quote = get_latest_quote("SPY")
    spot = (quote.get("bp", 0) + quote.get("ap", 0)) / 2 if quote else 0
    print(f"SPY mid: {spot}")
    contract = pick_contract_by_delta("SPY", spot, target_dte=30,
                                      option_type="call", target_delta=0.30)
    print(f"30-delta 30-DTE call: {contract}")
