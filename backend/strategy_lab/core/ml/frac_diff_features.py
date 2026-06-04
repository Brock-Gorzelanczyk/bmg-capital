"""
Fractional Differentiation Features — Priority 5.

Standard log-returns are I(1) — stationary but memory-less.
Raw prices are I(1) with memory but non-stationary.
Fractional differencing (d ∈ (0,1)) finds the minimum d that passes
an ADF test while preserving maximum memory — ideal ML features.

Reference: López de Prado (2018) — Chapter 5.

Usage
-----
from strategy_lab.core.ml.frac_diff_features import frac_diff, min_ffd_d

d = min_ffd_d(price_series)          # find minimum stationary d
fd_series = frac_diff(price_series, d=d)  # fractionally differenced series
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


def _get_weights(d: float, size: int) -> np.ndarray:
    """Compute FFD (Fixed-width window Fractional Differencing) weights."""
    w = [1.0]
    for k in range(1, size):
        w_k = -w[-1] * (d - k + 1) / k
        w.append(w_k)
    return np.array(w[::-1])


def frac_diff(series: np.ndarray, d: float, thresh: float = 1e-5) -> np.ndarray:
    """
    Apply Fixed-width window fractional differencing.

    Parameters
    ----------
    series : 1-D price series (log prices recommended)
    d : differentiation order, 0 < d < 1
    thresh : drop weights below this threshold (truncate window)

    Returns
    -------
    1-D array of same length as series (NaN-padded at start)
    """
    w = _get_weights(d, len(series))
    # Truncate insignificant weights
    w_ = np.cumsum(np.abs(w))
    w_ /= w_[-1]
    skip = int((w_ > thresh).argmax())
    w = w[skip:]

    out = np.full(len(series), np.nan)
    for i in range(len(w) - 1, len(series)):
        out[i] = float(np.dot(w, series[i - len(w) + 1: i + 1]))
    return out


def min_ffd_d(
    series: np.ndarray,
    d_range: tuple[float, float] = (0.0, 1.0),
    n_steps: int = 11,
    adf_threshold: float = -2.86,  # 5% critical value for ADF
) -> float:
    """
    Find the minimum d such that the fractionally differenced series is stationary.

    Falls back to d=0.3 if statsmodels is not available.
    """
    try:
        from statsmodels.tsa.stattools import adfuller
    except ImportError:
        logger.warning("statsmodels not installed — using default d=0.3")
        return 0.3

    log_series = np.log(np.maximum(series, 1e-10))
    candidates = np.linspace(d_range[0], d_range[1], n_steps)

    for d in candidates:
        fd = frac_diff(log_series, d)
        fd_clean = fd[~np.isnan(fd)]
        if len(fd_clean) < 20:
            continue
        try:
            adf_stat = adfuller(fd_clean, maxlag=1, regression="c", autolag=None)[0]
            if adf_stat < adf_threshold:
                logger.info("[frac_diff] min_ffd_d=%.2f (ADF=%.3f)", d, adf_stat)
                return float(d)
        except Exception:
            continue

    logger.warning("[frac_diff] no stationary d found in range — returning 1.0")
    return 1.0


def build_fd_features(ohlcv: dict, d: Optional[float] = None) -> dict[str, np.ndarray]:
    """
    Build fractionally differenced features from OHLCV dict.

    Returns dict with keys: fd_close, fd_volume, fd_high_low_range
    """
    close = np.array(ohlcv.get("close", []), dtype=float)
    volume = np.array(ohlcv.get("volume", []), dtype=float)
    high = np.array(ohlcv.get("high", []), dtype=float)
    low = np.array(ohlcv.get("low", []), dtype=float)

    if len(close) < 30:
        return {}

    d_val = d if d is not None else min_ffd_d(close)
    log_close = np.log(np.maximum(close, 1e-10))
    log_volume = np.log(np.maximum(volume, 1e-10))
    hl_range = high - low

    return {
        "fd_close": frac_diff(log_close, d_val),
        "fd_volume": frac_diff(log_volume, d_val),
        "fd_hl_range": frac_diff(hl_range, d_val),
        "d_used": np.full(len(close), d_val),
    }
