"""Alpha decay detection: OU half-life, SPRT, CUSUM, rolling IC."""
from __future__ import annotations

import math
import numpy as np
from scipy import stats


def ou_half_life(returns: np.ndarray) -> float:
    """Estimate mean-reversion half-life via OLS of the OU process on the return series."""
    if len(returns) < 3:
        return float("inf")
    diff = np.diff(returns)
    lagged = returns[:-1]
    reg = stats.linregress(lagged, diff)
    kappa = -reg.slope
    if kappa <= 0:
        return float("inf")
    return math.log(2) / kappa


class SPRTDecayDetector:
    """Sequential Probability Ratio Test for strategy mean-shift decay."""

    def __init__(
        self,
        mu0: float,
        sigma: float,
        alpha: float = 0.05,
        beta: float = 0.20,
    ) -> None:
        self.mu0 = mu0
        self.mu1 = mu0 - sigma
        self.sigma = sigma
        self.threshold = math.log((1 - beta) / alpha)
        self.llr: float = 0.0
        self.alarm: bool = False

    def update(self, return_today: float) -> dict:
        """Ingest one daily return, update the log-likelihood ratio, and check alarm."""
        llr_increment = (
            (self.mu1 - self.mu0) / self.sigma**2
        ) * return_today + (self.mu0**2 - self.mu1**2) / (2 * self.sigma**2)
        self.llr += llr_increment
        self.alarm = self.llr >= self.threshold
        return {"llr": self.llr, "alarm": self.alarm, "threshold": self.threshold}

    def reset(self) -> None:
        """Reset cumulative LLR and alarm state."""
        self.llr = 0.0
        self.alarm = False


class CUSUMDetector:
    """Two-sided CUSUM chart for detecting a shift in strategy returns."""

    def __init__(self, target_mean: float, sigma: float, h: float = 4.0) -> None:
        self.target = target_mean
        self.h = h * sigma
        self.cusum_up: float = 0.0
        self.cusum_down: float = 0.0

    def update(self, return_today: float) -> dict:
        """Ingest one daily return and return current CUSUM statistics and alarm flag."""
        k = self.h / 2
        deviation = return_today - self.target
        self.cusum_up = max(0.0, self.cusum_up + deviation - k)
        self.cusum_down = max(0.0, self.cusum_down - deviation - k)
        alarm = (self.cusum_up >= self.h) or (self.cusum_down >= self.h)
        return {
            "cusum_up": self.cusum_up,
            "cusum_down": self.cusum_down,
            "alarm": alarm,
        }

    def reset(self) -> None:
        """Reset both CUSUM accumulators."""
        self.cusum_up = 0.0
        self.cusum_down = 0.0


def rolling_information_coefficient(
    signal_strength: np.ndarray,
    next_day_return: np.ndarray,
    window: int = 63,
) -> np.ndarray:
    """Rolling Spearman IC between signal and forward return over a fixed lookback window."""
    n = len(signal_strength)
    if n != len(next_day_return) or n < window:
        return np.full(n, np.nan)

    result = np.full(n, np.nan)
    for i in range(window - 1, n):
        s = signal_strength[i - window + 1 : i + 1]
        r = next_day_return[i - window + 1 : i + 1]
        if np.std(s) > 0 and np.std(r) > 0:
            corr, _ = stats.spearmanr(s, r)
            result[i] = corr
    return result
