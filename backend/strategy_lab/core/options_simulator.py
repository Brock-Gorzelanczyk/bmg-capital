"""Black-Scholes options pricing, Greeks, and iron condor simulation."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd
from scipy.stats import norm

# ── Volatility helpers ────────────────────────────────────────────────────────


def realized_vol_30d(bars: pd.DataFrame) -> float:
    """Annualised realised volatility using the last 30 close prices.

    Args:
        bars: OHLCV DataFrame; must contain a ``close`` or ``c`` column.

    Returns:
        Annualised standard deviation of log-returns (float).
    """
    close_col = "close" if "close" in bars.columns else "c"
    closes = bars[close_col].dropna().values[-30:]
    if len(closes) < 2:
        return 0.20  # fallback 20 % vol
    log_returns = np.diff(np.log(closes.astype(float)))
    return float(np.std(log_returns, ddof=1) * math.sqrt(252))


def iv_approximation(realized_vol: float, vrp: float = 1.20) -> float:
    """Estimate implied volatility by scaling realised vol by a VRP factor.

    Args:
        realized_vol: Annualised realised volatility (e.g. 0.18 = 18 %).
        vrp: Variance-risk-premium multiplier; default 1.20 (IV > RV on average).

    Returns:
        Approximate implied volatility.
    """
    return realized_vol * vrp


def iv_rank_approximation(historical_realized_vol: pd.Series) -> float:
    """Estimate IV rank (0–100) by normalising the most recent realised vol.

    Args:
        historical_realized_vol: Series of daily realised-vol observations.

    Returns:
        Float in [0, 100].  50.0 when there is no spread in the history.
    """
    if historical_realized_vol.empty:
        return 50.0
    latest = float(historical_realized_vol.iloc[-1])
    min_rv = float(historical_realized_vol.min())
    max_rv = float(historical_realized_vol.max())
    if max_rv == min_rv:
        return 50.0
    return float((latest - min_rv) / (max_rv - min_rv) * 100.0)


# ── Black-Scholes pricing ─────────────────────────────────────────────────────


def black_scholes_price(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    option_type: str = "call",
) -> float:
    """Compute the Black-Scholes price for a European option.

    Args:
        S: Current underlying price.
        K: Strike price.
        T: Time to expiry in years.
        r: Risk-free rate (annualised, decimal).
        sigma: Implied volatility (annualised, decimal).
        option_type: ``"call"`` or ``"put"``.

    Returns:
        Option price.  0.0 on invalid inputs.
    """
    if S <= 0 or K <= 0:
        return 0.0

    ot = option_type.lower()

    # Intrinsic value when no time or no vol
    if T <= 0 or sigma <= 0:
        if ot == "call":
            return max(0.0, S - K)
        return max(0.0, K - S)

    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    if ot == "call":
        return float(S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2))
    if ot == "put":
        return float(K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1))

    raise ValueError(f"option_type must be 'call' or 'put', got {option_type!r}")


def black_scholes_greeks(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    option_type: str = "call",
) -> dict:
    """Compute first-order Black-Scholes Greeks.

    Args:
        S: Current underlying price.
        K: Strike price.
        T: Time to expiry in years.
        r: Risk-free rate (annualised, decimal).
        sigma: Implied volatility (annualised, decimal).
        option_type: ``"call"`` or ``"put"``.

    Returns:
        dict with keys delta, gamma, theta (per calendar day), vega (per 1 % vol).
    """
    zeros = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}

    if T <= 0 or S <= 0 or K <= 0 or sigma <= 0:
        return zeros

    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T

    pdf_d1 = float(norm.pdf(d1))
    ot = option_type.lower()

    # Delta
    if ot == "call":
        delta = float(norm.cdf(d1))
    else:
        delta = float(norm.cdf(d1) - 1.0)

    # Gamma (same for call and put)
    gamma = pdf_d1 / (S * sigma * sqrt_T)

    # Theta (per calendar day)
    time_decay = S * pdf_d1 * sigma / (2.0 * sqrt_T)
    disc_factor = r * K * math.exp(-r * T)
    if ot == "call":
        theta = -(time_decay + disc_factor * float(norm.cdf(d2))) / 365.0
    else:
        theta = -(time_decay - disc_factor * float(norm.cdf(-d2))) / 365.0

    # Vega (per 1 % change in vol, i.e. per 0.01 sigma)
    vega = S * pdf_d1 * sqrt_T / 100.0

    return {
        "delta": float(delta),
        "gamma": float(gamma),
        "theta": float(theta),
        "vega": float(vega),
    }


# ── Iron condor dataclass ─────────────────────────────────────────────────────


@dataclass
class IronCondorTrade:
    """Snapshot of an iron condor trade at entry."""

    entry_date: date
    expiry: date
    spot_at_entry: float
    short_call_strike: float
    long_call_strike: float
    short_put_strike: float
    long_put_strike: float
    credit_received: float
    max_loss: float
    iv_at_entry: float


# ── Iron condor simulation ────────────────────────────────────────────────────


def _round_to_nearest(value: float, increment: float) -> float:
    """Round *value* to the nearest *increment*."""
    return round(value / increment) * increment


def _condor_mark(
    spot: float,
    short_call: float,
    long_call: float,
    short_put: float,
    long_put: float,
    T: float,
    r: float,
    iv: float,
) -> float:
    """Current mark-to-market value of the short condor (what we owe to close)."""
    return (
        black_scholes_price(spot, short_call, T, r, iv, "call")
        - black_scholes_price(spot, long_call, T, r, iv, "call")
        + black_scholes_price(spot, short_put, T, r, iv, "put")
        - black_scholes_price(spot, long_put, T, r, iv, "put")
    )


def simulate_iron_condor(
    bars: pd.DataFrame,
    entry_date: date,
    dte_target: int = 45,
    short_delta: float = 0.16,
    spread_width: float = 5.0,
    profit_target: float = 0.50,
    stop_loss_mult: float = 2.0,
    time_stop_dte: int = 21,
) -> dict:
    """Simulate a single iron condor trade from entry to exit.

    Strikes are chosen analytically from the Black-Scholes delta formula and
    rounded to the nearest ``spread_width``-dollar increment.  The simulation
    walks forward bar by bar, checking profit-target, stop-loss, and time-stop
    rules each day.

    Args:
        bars: Daily OHLCV DataFrame with a DatetimeIndex.  Must contain
            ``close`` or ``c`` column.
        entry_date: Calendar date to enter the trade.
        dte_target: Approximate days to expiry at entry.
        short_delta: Target delta for both short strikes (e.g. 0.16 ≈ 16-delta).
        spread_width: Width of each vertical spread in dollars.
        profit_target: Close early when PnL reaches this fraction of credit.
        stop_loss_mult: Close early when loss reaches this multiple of credit.
        time_stop_dte: Close early when DTE falls to this threshold.

    Returns:
        Result dict with entry, exit, pnl_pct, days_held, exit_reason,
        credit_received, max_loss, iv_at_entry.  ``{"error": ...}`` on failure.
    """
    close_col = "close" if "close" in bars.columns else "c"

    # Normalise index to date objects for comparison
    bars = bars.copy()
    if not isinstance(bars.index, pd.DatetimeIndex):
        bars.index = pd.to_datetime(bars.index)
    bars.index = bars.index.normalize()

    entry_ts = pd.Timestamp(entry_date)
    if entry_ts not in bars.index:
        return {"error": f"entry date {entry_date} not in bars"}

    spot = float(bars.loc[entry_ts, close_col])
    expiry_dt = entry_date + timedelta(days=dte_target)
    expiry_ts = pd.Timestamp(expiry_dt)

    T_entry = dte_target / 365.0
    r = 0.05
    iv = iv_approximation(realized_vol_30d(bars.loc[:entry_ts]))

    # ── Strike selection ──────────────────────────────────────────────────────
    # Analytical approximation: find K s.t. BS-delta(call) == short_delta
    # d1 = 0 when K = S * exp((r + 0.5*sig^2)*T); delta falls monotonically.
    # For a given delta d: K = S * exp(norm.ppf(1 - d) * sigma * sqrt(T) - 0.5*sig^2*T)
    from scipy.stats import norm as _norm  # already imported at module level

    sig_sqrt_T = iv * math.sqrt(T_entry)
    log_moneyness_call = _norm.ppf(1.0 - short_delta) * sig_sqrt_T - 0.5 * iv ** 2 * T_entry
    short_call_raw = spot * math.exp(log_moneyness_call)
    short_call_strike = _round_to_nearest(short_call_raw, spread_width)

    # Symmetric put wing
    short_put_strike = _round_to_nearest(spot - (short_call_strike - spot), spread_width)

    long_call_strike = short_call_strike + spread_width
    long_put_strike = short_put_strike - spread_width

    # ── Entry pricing ─────────────────────────────────────────────────────────
    credit_received = _condor_mark(
        spot, short_call_strike, long_call_strike,
        short_put_strike, long_put_strike,
        T_entry, r, iv,
    )
    max_loss = spread_width - credit_received

    trade = IronCondorTrade(
        entry_date=entry_date,
        expiry=expiry_dt,
        spot_at_entry=spot,
        short_call_strike=short_call_strike,
        long_call_strike=long_call_strike,
        short_put_strike=short_put_strike,
        long_put_strike=long_put_strike,
        credit_received=credit_received,
        max_loss=max_loss,
        iv_at_entry=iv,
    )

    # ── Simulation loop ───────────────────────────────────────────────────────
    future_bars = bars.loc[bars.index > entry_ts].copy()
    exit_date = expiry_dt
    exit_reason = "expiry"
    pnl = 0.0

    for ts, row in future_bars.iterrows():
        current_date: date = ts.date()
        if current_date >= expiry_dt:
            break

        current_T = (expiry_dt - current_date).days / 365.0
        current_spot = float(row[close_col])
        current_iv = iv_approximation(realized_vol_30d(bars.loc[:ts]))

        current_value = _condor_mark(
            current_spot,
            short_call_strike, long_call_strike,
            short_put_strike, long_put_strike,
            current_T, r, current_iv,
        )
        pnl = credit_received - current_value

        # Profit target
        if pnl >= profit_target * credit_received:
            exit_date = current_date
            exit_reason = "profit_target"
            break

        # Stop loss
        if pnl <= -stop_loss_mult * credit_received:
            exit_date = current_date
            exit_reason = "stop_loss"
            break

        # Time stop
        if current_T * 365.0 <= time_stop_dte:
            exit_date = current_date
            exit_reason = "time_stop"
            pnl = credit_received - current_value
            break
    else:
        # Reached expiry — compute intrinsic P&L
        expiry_bars = bars[bars.index >= expiry_ts]
        if not expiry_bars.empty:
            spot_final = float(expiry_bars.iloc[0][close_col])
        else:
            # Use last available bar
            spot_final = float(future_bars.iloc[-1][close_col]) if not future_bars.empty else spot

        intrinsic = (
            max(0.0, spot_final - short_call_strike)
            - max(0.0, spot_final - long_call_strike)
            + max(0.0, short_put_strike - spot_final)
            - max(0.0, long_put_strike - spot_final)
        )
        pnl = credit_received - intrinsic

    days_held = (exit_date - entry_date).days
    # pnl_pct: P&L as a percentage of max risk (spread_width per share * 100 shares notional)
    risk_notional = spread_width * 100.0
    pnl_pct = (pnl / risk_notional * 100.0) if risk_notional > 0 else 0.0

    return {
        "entry": entry_date.isoformat(),
        "exit": exit_date.isoformat(),
        "pnl_pct": float(pnl_pct),
        "days_held": int(days_held),
        "exit_reason": exit_reason,
        "credit_received": float(credit_received),
        "max_loss": float(max_loss),
        "iv_at_entry": float(iv),
    }


# ── Expected-value estimator ──────────────────────────────────────────────────


def mechanical_expected_value(
    short_delta: float,
    credit: float,
    max_loss: float,
) -> dict:
    """Estimate the mechanical edge of an iron condor strategy.

    Uses a simplified model where both short strikes must expire worthless
    for full credit retention.  The probability of profit is approximated as
    the complement of the probability that *either* short option is touched.

    Args:
        short_delta: The delta of the short options at entry (e.g. 0.16).
        credit: Credit received per spread (dollars).
        max_loss: Maximum loss per spread (dollars).

    Returns:
        dict with p_profit, expected_value, and sharpe_estimate.
    """
    # Probability both short strikes expire worthless (independent approximation)
    p_profit = max(0.0, 1.0 - 2.0 * short_delta)
    expected_value = credit * p_profit - max_loss * (1.0 - p_profit)

    # Annualised Sharpe estimate: 12 trades/year, unit sizing
    n_per_year = 12.0
    ev_annual = expected_value * n_per_year
    vol_annual = max_loss * math.sqrt(n_per_year)
    sharpe_estimate = ev_annual / vol_annual if vol_annual > 0 else 0.0

    return {
        "p_profit": float(p_profit),
        "expected_value": float(expected_value),
        "sharpe_estimate": float(sharpe_estimate),
    }
