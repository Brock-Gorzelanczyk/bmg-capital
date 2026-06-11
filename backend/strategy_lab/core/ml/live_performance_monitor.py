"""Live vs backtest divergence detection using Lo (2002) Sharpe SE."""
from __future__ import annotations

import math
import numpy as np
from scipy import stats


def sharpe_standard_error(sharpe: float, n_days: int) -> float:
    """Lo (2002) asymptotic standard error of the annualized Sharpe ratio."""
    return math.sqrt((1 + sharpe**2 / 2) / n_days)


def divergence_zscore(
    backtest_sharpe: float,
    backtest_days: int,
    live_sharpe: float,
    live_days: int,
) -> float:
    """Z-score of the difference between live and backtest Sharpe ratios."""
    se_bt = sharpe_standard_error(backtest_sharpe, backtest_days)
    se_live = sharpe_standard_error(live_sharpe, live_days)
    combined_se = math.sqrt(se_bt**2 + se_live**2)
    if combined_se == 0.0:
        return 0.0
    return (live_sharpe - backtest_sharpe) / combined_se


def traffic_light(zscore: float) -> str:
    """Map a divergence z-score to a GREEN / YELLOW / RED signal."""
    if zscore > -2.0:
        return "GREEN"
    if zscore > -3.0:
        return "YELLOW"
    return "RED"


def ks_divergence(
    live_returns: np.ndarray,
    backtest_returns: np.ndarray,
) -> dict:
    """Two-sample KS test between live and backtest return distributions."""
    if live_returns.size == 0 or backtest_returns.size == 0:
        return {"ks_stat": 0.0, "p_value": 1.0, "diverged_at_5pct": False}
    ks_stat, p_value = stats.ks_2samp(live_returns, backtest_returns)
    return {
        "ks_stat": float(ks_stat),
        "p_value": float(p_value),
        "diverged_at_5pct": bool(p_value < 0.05),
    }


def bayesian_true_sharpe_posterior(
    live_returns: np.ndarray,
    prior_sharpe: float,
    prior_strength: int = 100,
) -> dict:
    """Bayesian update of true Sharpe posterior given live returns and a normal prior."""
    n = len(live_returns)
    if n > 1:
        mu = float(np.mean(live_returns))
        sigma = float(np.std(live_returns, ddof=1))
        live_sharpe = (mu / sigma) * math.sqrt(252) if sigma > 0.0 else 0.0
    else:
        live_sharpe = 0.0

    posterior_precision = prior_strength + n
    posterior_mean = (prior_sharpe * prior_strength + live_sharpe * n) / posterior_precision
    posterior_std = 1.0 / math.sqrt(posterior_precision)
    prob_true_sr_below_0_5 = float(
        stats.norm.cdf(0.5, loc=posterior_mean, scale=posterior_std)
    )
    return {
        "posterior_mean": float(posterior_mean),
        "posterior_std": float(posterior_std),
        "prob_true_sr_below_0_5": prob_true_sr_below_0_5,
    }
