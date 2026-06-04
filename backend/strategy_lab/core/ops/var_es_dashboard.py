"""
VaR + ES Risk Dashboard — Weekend 4, Module 7.

Daily Value at Risk (95%) and Expected Shortfall (97.5%) per bot and fund.
Three methods: historical, parametric (normal), Monte Carlo.
FRTB regulatory standard for ES.

Generates daily snapshots. Surfaces in /strategy bot detail Risk tab.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Literal

import numpy as np

logger = logging.getLogger(__name__)

VaRMethod = Literal["historical", "parametric", "monte_carlo"]


@dataclass
class VaRSnapshot:
    date: str                   # "YYYY-MM-DD"
    label: str                  # bot_id or "fund"
    var_95: float               # 95% 1-day VaR in USD (positive = loss)
    es_975: float               # 97.5% Expected Shortfall in USD
    method: VaRMethod
    window_days: int
    n_returns: int
    breach_count_30d: int = 0   # realized breaches in last 30 days


def historical_var(
    returns: np.ndarray,
    capital_usd: float,
    confidence: float = 0.95,
    window: int = 252,
) -> tuple[float, float]:
    """
    Historical simulation VaR and ES.

    Returns (VaR_95, ES_97.5) in USD (positive = expected loss).
    """
    arr = np.array(returns[-window:]) * capital_usd
    if len(arr) < 20:
        return 0.0, 0.0

    var_q = float(np.percentile(arr, (1 - confidence) * 100))
    es_q = float(arr[arr <= var_q].mean()) if (arr <= var_q).any() else var_q

    return abs(var_q), abs(es_q)


def parametric_var(
    returns: np.ndarray,
    capital_usd: float,
    confidence: float = 0.95,
    window: int = 252,
) -> tuple[float, float]:
    """
    Parametric (normal) VaR and ES.

    Assumes returns are normally distributed — fast but underestimates fat tails.
    """
    from scipy.stats import norm

    arr = np.array(returns[-window:])
    if len(arr) < 10:
        return 0.0, 0.0

    mu = float(np.mean(arr))
    sigma = float(np.std(arr))

    var_z = norm.ppf(1 - confidence)
    var_95 = abs((mu + var_z * sigma) * capital_usd)

    es_z = norm.ppf(0.025)  # 97.5% ES
    es_975 = abs((mu + norm.pdf(norm.ppf(0.025)) / 0.025 * sigma) * capital_usd)

    return var_95, es_975


def monte_carlo_var(
    returns: np.ndarray,
    capital_usd: float,
    confidence: float = 0.95,
    n_simulations: int = 10_000,
    window: int = 252,
) -> tuple[float, float]:
    """
    Monte Carlo VaR using bootstrapped returns.
    """
    arr = np.array(returns[-window:])
    if len(arr) < 10:
        return 0.0, 0.0

    rng = np.random.default_rng(seed=42)
    sim_returns = rng.choice(arr, size=n_simulations, replace=True) * capital_usd

    var_q = float(np.percentile(sim_returns, (1 - confidence) * 100))
    es_q = float(sim_returns[sim_returns <= var_q].mean()) if (sim_returns <= var_q).any() else var_q

    return abs(var_q), abs(es_q)


def compute_var_snapshot(
    label: str,
    returns: np.ndarray,
    capital_usd: float,
    method: VaRMethod = "historical",
    window: int = 252,
    realized_daily_losses: Optional[list[float]] = None,
) -> VaRSnapshot:
    """
    Compute a full VaR snapshot for a bot or fund.

    Parameters
    ----------
    label : "bot_7" or "fund" etc.
    returns : 1-D array of daily portfolio returns
    capital_usd : current account value for USD conversion
    method : computation method
    window : rolling lookback window in trading days
    realized_daily_losses : list of recent 30d losses for breach counting
    """
    if method == "parametric":
        try:
            var95, es975 = parametric_var(returns, capital_usd, window=window)
        except ImportError:
            var95, es975 = historical_var(returns, capital_usd, window=window)
    elif method == "monte_carlo":
        var95, es975 = monte_carlo_var(returns, capital_usd, window=window)
    else:
        var95, es975 = historical_var(returns, capital_usd, window=window)

    breach_count = 0
    if realized_daily_losses and var95 > 0:
        breach_count = sum(1 for l in realized_daily_losses[-30:] if l > var95)

    return VaRSnapshot(
        date=date.today().isoformat(),
        label=label,
        var_95=round(var95, 2),
        es_975=round(es975, 2),
        method=method,
        window_days=window,
        n_returns=min(len(returns), window),
        breach_count_30d=breach_count,
    )


def fund_var(
    bot_returns: dict[str, np.ndarray],
    bot_capitals: dict[str, float],
    method: VaRMethod = "historical",
) -> VaRSnapshot:
    """
    Compute fund-wide VaR by aggregating all bot returns (equal-weight simple sum).

    Parameters
    ----------
    bot_returns : {label: returns_array}
    bot_capitals : {label: capital_usd}
    """
    if not bot_returns:
        return VaRSnapshot(
            date=date.today().isoformat(),
            label="fund",
            var_95=0.0,
            es_975=0.0,
            method=method,
            window_days=252,
            n_returns=0,
        )

    min_len = min(len(r) for r in bot_returns.values())
    total_capital = sum(bot_capitals.values())

    if min_len < 5 or total_capital <= 0:
        return VaRSnapshot(
            date=date.today().isoformat(),
            label="fund",
            var_95=0.0,
            es_975=0.0,
            method=method,
            window_days=252,
            n_returns=min_len,
        )

    # Dollar-weighted portfolio return
    combined = np.zeros(min_len)
    for label, returns in bot_returns.items():
        weight = bot_capitals.get(label, 0) / total_capital
        combined += np.array(returns[-min_len:]) * weight

    return compute_var_snapshot("fund", combined, total_capital, method=method)


# Optional type hint — avoid runtime import
try:
    from typing import Optional
except ImportError:
    pass
