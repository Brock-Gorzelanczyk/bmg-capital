"""
Black-Scholes Greeks library using only the `math` module (no scipy).

All pricing functions assume:
  S     — current underlying price
  K     — strike price
  T     — time to expiry in years (must be > 0)
  r     — risk-free rate (annualized, e.g. 0.05 for 5%)
  sigma — implied volatility (annualized, e.g. 0.20 for 20%)
"""
from __future__ import annotations

import math


def _norm_cdf(x: float) -> float:
    """Standard normal CDF via math.erfc."""
    return 0.5 * math.erfc(-x / math.sqrt(2))


def _norm_pdf(x: float) -> float:
    """Standard normal PDF."""
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def d1(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Black-Scholes d1 term."""
    return (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))


def d2(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Black-Scholes d2 term (d1 minus sigma*sqrt(T))."""
    return d1(S, K, T, r, sigma) - sigma * math.sqrt(T)


def call_price(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """
    Black-Scholes call option price.

    Returns 0.0 if T <= 0 or sigma <= 0 (degenerate inputs).
    """
    if T <= 0 or sigma <= 0:
        return max(0.0, S - K)
    _d1 = d1(S, K, T, r, sigma)
    _d2 = d2(S, K, T, r, sigma)
    return S * _norm_cdf(_d1) - K * math.exp(-r * T) * _norm_cdf(_d2)


def put_price(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """
    Black-Scholes put option price.

    Returns max(K-S, 0) if T <= 0 or sigma <= 0 (degenerate inputs).
    """
    if T <= 0 or sigma <= 0:
        return max(0.0, K - S)
    _d1 = d1(S, K, T, r, sigma)
    _d2 = d2(S, K, T, r, sigma)
    return K * math.exp(-r * T) * _norm_cdf(-_d2) - S * _norm_cdf(-_d1)


def call_delta(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """
    Call option delta — N(d1). Range: 0 to 1.

    Returns 1.0 if deep ITM (T<=0, S>>K) or 0.0 if T<=0 and OTM.
    Returns 0.0 if sigma <= 0.
    """
    if T <= 0 or sigma <= 0:
        return 1.0 if S > K else 0.0
    return _norm_cdf(d1(S, K, T, r, sigma))


def put_delta(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """
    Put option delta — N(d1) - 1. Range: -1 to 0.

    Returns -1.0 if deep ITM (T<=0, S<<K) or 0.0 if T<=0 and OTM.
    Returns 0.0 if sigma <= 0.
    """
    if T <= 0 or sigma <= 0:
        return -1.0 if S < K else 0.0
    return _norm_cdf(d1(S, K, T, r, sigma)) - 1.0


def vega(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """
    Option vega — sensitivity to a 1% change in implied volatility (divided by 100).

    Returns 0.0 if T <= 0 or sigma <= 0.
    """
    if T <= 0 or sigma <= 0:
        return 0.0
    return S * _norm_pdf(d1(S, K, T, r, sigma)) * math.sqrt(T) / 100.0


def iv_from_call_price(
    market_price: float,
    S: float,
    K: float,
    T: float,
    r: float,
    tol: float = 1e-5,
    max_iter: int = 100,
) -> float | None:
    """
    Implied volatility from a call market price via Newton's method.

    Returns None if T <= 0, market_price <= 0, or no convergence within max_iter.
    """
    if T <= 0 or market_price <= 0:
        return None

    # Initial guess: simple approximation
    sigma = math.sqrt(2 * math.pi / T) * market_price / S
    sigma = max(0.001, min(sigma, 10.0))  # clamp to sane range

    for _ in range(max_iter):
        price = call_price(S, K, T, r, sigma)
        v = vega(S, K, T, r, sigma) * 100.0  # undo /100 scaling for Newton step
        if v == 0.0:
            return None
        diff = price - market_price
        if abs(diff) < tol:
            return sigma
        sigma -= diff / v
        if sigma <= 0:
            sigma = 1e-6

    return None  # no convergence


def iv_from_put_price(
    market_price: float,
    S: float,
    K: float,
    T: float,
    r: float,
    tol: float = 1e-5,
    max_iter: int = 100,
) -> float | None:
    """
    Implied volatility from a put market price via Newton's method.

    Returns None if T <= 0, market_price <= 0, or no convergence within max_iter.
    """
    if T <= 0 or market_price <= 0:
        return None

    # Initial guess
    sigma = math.sqrt(2 * math.pi / T) * market_price / S
    sigma = max(0.001, min(sigma, 10.0))

    for _ in range(max_iter):
        price = put_price(S, K, T, r, sigma)
        v = vega(S, K, T, r, sigma) * 100.0  # undo /100 scaling for Newton step
        if v == 0.0:
            return None
        diff = price - market_price
        if abs(diff) < tol:
            return sigma
        sigma -= diff / v
        if sigma <= 0:
            sigma = 1e-6

    return None  # no convergence
