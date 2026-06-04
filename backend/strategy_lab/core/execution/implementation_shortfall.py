"""
Implementation Shortfall (Almgren-Chriss) — Weekend 5, Module 10.

Minimizes E[cost] + λ·Var[cost] vs arrival mid using the closed-form
optimal liquidation trajectory.

Optimal schedule:
  x(t) = X · sinh(κ(T−t)) / sinh(κT)
  κ = √(λσ² / η)
  η = temporary impact coefficient
  σ = asset daily vol

Child orders are submitted on this curve and repriced each slice.
Default algo for all alpha-driven directional orders.

Reference: Almgren & Chriss (2001), "Optimal Execution of Portfolio Transactions"
           Perold (1988), "The Implementation Shortfall: Paper vs Reality"
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class AlmgrenChrissParams:
    """Market impact parameters per asset class."""
    sigma_daily: float           # daily vol (e.g. 0.015 = 1.5%)
    eta: float = 2.5e-7          # temporary impact (shares^-1 per share)
    gamma: float = 2.5e-8        # permanent impact (shares^-1 per share)
    risk_aversion: float = 1e-6  # λ — higher = faster execution

    @classmethod
    def from_adv(cls, sigma_daily: float, adv_shares: float) -> "AlmgrenChrissParams":
        """Estimate params from daily vol and average daily volume."""
        # Typical calibration: η ≈ σ / (2 × ADV^0.5)
        eta = sigma_daily / (2.0 * math.sqrt(max(adv_shares, 1)))
        gamma = eta * 0.3  # permanent impact ~30% of temporary
        return cls(sigma_daily=sigma_daily, eta=eta, gamma=gamma)


@dataclass
class ExecutionSlice:
    """A single child order slice."""
    slice_idx: int
    t_start: float          # fraction of total horizon at start
    t_end: float            # fraction at end
    shares_remaining_at_start: float
    shares_to_trade: float
    limit_price: Optional[float]
    urgency: str            # "passive" | "neutral" | "aggressive"


def optimal_schedule(
    total_shares: float,
    n_slices: int,
    horizon_minutes: float,
    params: AlmgrenChrissParams,
) -> np.ndarray:
    """
    Compute the Almgren-Chriss optimal execution trajectory.

    Returns array of length n_slices with shares to trade per slice.
    Array sums to total_shares.
    """
    kappa = math.sqrt(params.risk_aversion * params.sigma_daily ** 2 / max(params.eta, 1e-20))

    T = horizon_minutes / 390.0  # normalize to fraction of trading day
    dt = T / n_slices

    # x(t) = total_shares × sinh(κ(T-t)) / sinh(κT)
    def remaining_at(t: float) -> float:
        denom = math.sinh(kappa * T)
        if denom < 1e-15:
            return total_shares * (1 - t / T)  # linear fallback
        return total_shares * math.sinh(kappa * (T - t)) / denom

    slices = np.zeros(n_slices)
    for i in range(n_slices):
        t0 = i * dt
        t1 = (i + 1) * dt
        r0 = remaining_at(t0)
        r1 = remaining_at(t1)
        slices[i] = max(0, r0 - r1)

    # Normalize to exact total (floating point rounding)
    if slices.sum() > 0:
        slices = slices * total_shares / slices.sum()

    return slices


def build_execution_plan(
    symbol: str,
    side: str,
    total_shares: float,
    arrival_mid: float,
    params: AlmgrenChrissParams,
    n_slices: int = 10,
    horizon_minutes: float = 60.0,
    spread_usd: float = 0.01,
) -> list[ExecutionSlice]:
    """
    Build the full Almgren-Chriss execution plan as a list of slices.

    Parameters
    ----------
    symbol : ticker
    side : "buy" | "sell"
    total_shares : total quantity to execute
    arrival_mid : NBBO mid at decision time
    params : calibrated AlmgrenChrissParams
    n_slices : number of child orders
    horizon_minutes : total execution window
    spread_usd : current bid-ask spread for limit pricing

    Returns
    -------
    list of ExecutionSlice
    """
    schedule = optimal_schedule(total_shares, n_slices, horizon_minutes, params)
    slices: list[ExecutionSlice] = []
    remaining = total_shares

    dt_min = horizon_minutes / n_slices

    for i, qty in enumerate(schedule):
        # Determine limit price: for buys, bid at mid - half_spread initially,
        # become more aggressive as slice ages
        urgency_factor = i / max(n_slices - 1, 1)  # 0 (passive) to 1 (aggressive)
        half_spread = spread_usd / 2

        if urgency_factor < 0.4:
            urgency = "passive"
            if side == "buy":
                limit_price = arrival_mid - half_spread * 0.5
            else:
                limit_price = arrival_mid + half_spread * 0.5
        elif urgency_factor < 0.8:
            urgency = "neutral"
            limit_price = arrival_mid
        else:
            urgency = "aggressive"
            limit_price = None  # market order for last slices

        slices.append(ExecutionSlice(
            slice_idx=i,
            t_start=i * dt_min,
            t_end=(i + 1) * dt_min,
            shares_remaining_at_start=remaining,
            shares_to_trade=round(qty, 4),
            limit_price=round(limit_price, 4) if limit_price else None,
            urgency=urgency,
        ))
        remaining -= qty

    logger.info(
        "[IS] %s %s %.0f shares over %.0fm in %d slices (κ=%.4f)",
        side, symbol, total_shares, horizon_minutes, n_slices,
        math.sqrt(params.risk_aversion * params.sigma_daily ** 2 / max(params.eta, 1e-20)),
    )
    return slices


def expected_cost_bps(
    total_shares: float,
    params: AlmgrenChrissParams,
    arrival_mid: float,
    schedule: np.ndarray,
) -> float:
    """
    Estimate expected execution cost in basis points vs arrival mid.

    Cost = permanent impact + temporary impact.
    """
    if arrival_mid <= 0 or total_shares <= 0:
        return 0.0

    # Permanent impact: γ × X²
    perm = params.gamma * total_shares ** 2 * arrival_mid

    # Temporary impact: η × Σ(n_i²) where n_i = shares per slice
    temp = params.eta * float(np.sum(schedule ** 2)) * arrival_mid

    total_cost_usd = perm + temp
    total_notional = total_shares * arrival_mid
    return round((total_cost_usd / total_notional) * 10_000, 2)
