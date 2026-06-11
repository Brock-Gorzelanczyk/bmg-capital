"""Seven orthogonal market regime signals."""

import logging
import math
from typing import Optional

import numpy as np
import pandas as pd

from strategy_lab.core.altdata.credit_spread_signal import get_credit_regime

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Signal 1 — Hurst DFA
# ---------------------------------------------------------------------------


def hurst_dfa(
    ts: np.ndarray,
    min_window: int = 10,
    max_window: Optional[int] = None,
    polynomial_order: int = 1,
) -> float:
    """
    Detrended Fluctuation Analysis. Returns H in [0, 1].

    H > 0.5  → trending (persistent)
    H < 0.5  → mean-reverting (anti-persistent)
    H ≈ 0.5  → random walk

    Algorithm:
    1. Cumulative sum of (ts - mean(ts)).
    2. For each window size w in log-spaced range [min_window, max_window]:
       a. Divide the integrated series into non-overlapping segments of size w.
       b. Detrend each segment (fit polynomial of order ``polynomial_order``,
          then subtract the fit).
       c. Compute the RMS of the residuals for each segment.
       d. F(w) = mean(RMS across all segments).
    3. H = slope of log(F(w)) vs log(w) via linear regression.
    4. Clip result to [0.0, 1.0].
    """
    ts = np.asarray(ts, dtype=float)
    n = len(ts)

    if n < min_window * 2:
        return float("nan")

    if max_window is None:
        max_window = n // 4

    max_window = min(max_window, n // 2)

    if min_window >= max_window:
        return float("nan")

    # Step 1: integrate the mean-centred series
    integrated = np.cumsum(ts - np.mean(ts))

    # Step 2: generate log-spaced window sizes (at least 4 points for regression)
    num_windows = max(4, int(math.log2(max_window / min_window) * 8))
    window_sizes = np.unique(
        np.logspace(
            math.log10(min_window),
            math.log10(max_window),
            num=num_windows,
            dtype=int,
        )
    )
    window_sizes = window_sizes[window_sizes >= min_window]

    log_windows: list[float] = []
    log_fluctuations: list[float] = []

    for w in window_sizes:
        n_segments = n // w
        if n_segments < 1:
            continue

        rms_values: list[float] = []
        for seg_idx in range(n_segments):
            segment = integrated[seg_idx * w : (seg_idx + 1) * w]
            x = np.arange(len(segment), dtype=float)
            coeffs = np.polyfit(x, segment, polynomial_order)
            trend = np.polyval(coeffs, x)
            residuals = segment - trend
            rms = math.sqrt(np.mean(residuals ** 2))
            rms_values.append(rms)

        if not rms_values:
            continue

        f_w = float(np.mean(rms_values))
        if f_w > 0:
            log_windows.append(math.log(w))
            log_fluctuations.append(math.log(f_w))

    if len(log_windows) < 2:
        return float("nan")

    log_w_arr = np.array(log_windows)
    log_f_arr = np.array(log_fluctuations)

    # Step 3: slope via linear regression
    slope, _ = np.polyfit(log_w_arr, log_f_arr, 1)

    # Step 4: clip to [0, 1]
    return float(np.clip(slope, 0.0, 1.0))


def rolling_hurst(
    returns: np.ndarray,
    window: int = 63,
    method: str = "dfa",
) -> np.ndarray:
    """
    Compute a rolling Hurst exponent over ``returns``.

    Returns an array of the same length as ``returns``.  The first
    ``window - 1`` values are NaN.  Currently only ``method="dfa"`` is
    supported; any other value raises ``ValueError``.
    """
    if method != "dfa":
        raise ValueError(f"Unsupported Hurst method: {method!r}. Only 'dfa' is supported.")

    returns = np.asarray(returns, dtype=float)
    n = len(returns)
    result = np.full(n, float("nan"))

    for i in range(window - 1, n):
        window_slice = returns[i - window + 1 : i + 1]
        result[i] = hurst_dfa(window_slice)

    return result


# ---------------------------------------------------------------------------
# Signal 2 — Credit Spread
# ---------------------------------------------------------------------------


def credit_spread_state() -> dict:
    """
    Thin wrapper around ``get_credit_regime()``.

    Returns the same dict shape produced by that function.  On any
    exception the function fails-open, returning a neutral/green default
    so that downstream regime logic is never blocked by a data outage.
    """
    try:
        return get_credit_regime()
    except Exception as e:
        logger.warning(f"credit_spread_state failed: {e}")
        return {
            "state": "green",
            "equity_multiplier": 1.0,
            "hy_spread": None,
            "reason": "fallback",
        }


# ---------------------------------------------------------------------------
# Signal 3 — VIX Regime
# ---------------------------------------------------------------------------


def vix_regime(
    vix_level: float,
    vx1: Optional[float] = None,
    vx2: Optional[float] = None,
) -> dict:
    """
    Classify the current volatility environment from the VIX spot level and
    the front-two VIX futures (for term-structure direction).

    Level thresholds:
        < 15        → "calm"
        15 – 20     → "normal"
        20 – 30     → "elevated"
        > 30        → "stress"

    Term structure (vx2 / vx1):
        > 1.05      → "contango"   (normal/bullish)
        < 1.00      → "backwardation"  (stress)
        otherwise   → "flat"

    Returns::

        {
            "state": "calm" | "normal" | "elevated" | "stress",
            "level_regime": str,          # same as state
            "term_structure": "contango" | "backwardation" | "flat" | "unknown",
            "equity_multiplier": float,   # 1.2 calm, 1.0 normal, 0.7 elevated, 0.0 stress
            "vix_level": float,
        }
    """
    # Level classification
    if vix_level < 15:
        level_regime = "calm"
        equity_multiplier = 1.2
    elif vix_level < 20:
        level_regime = "normal"
        equity_multiplier = 1.0
    elif vix_level < 30:
        level_regime = "elevated"
        equity_multiplier = 0.7
    else:
        level_regime = "stress"
        equity_multiplier = 0.0

    # Term structure
    if vx1 is not None and vx2 is not None and vx1 > 0:
        ratio = vx2 / vx1
        if ratio > 1.05:
            term_structure = "contango"
        elif ratio < 1.0:
            term_structure = "backwardation"
        else:
            term_structure = "flat"
    else:
        term_structure = "unknown"

    return {
        "state": level_regime,
        "level_regime": level_regime,
        "term_structure": term_structure,
        "equity_multiplier": equity_multiplier,
        "vix_level": vix_level,
    }


# ---------------------------------------------------------------------------
# Signal 4 — Yield Curve
# ---------------------------------------------------------------------------


def yield_curve_state(t10y2y: float) -> dict:
    """
    Classify the yield curve using the FRED T10Y2Y spread (10-year minus
    2-year Treasury yield, expressed in percentage points).

    Thresholds:
        > 1.0   → "steep"    (bullish growth expectations)
        0.0–1.0 → "flat"
        < 0.0   → "inverted" (recession risk)

    ``recession_signal`` is ``True`` when the spread is below –0.25 %,
    which has historically preceded recessions with a 6–18 month lag.

    Returns::

        {
            "state": "steep" | "flat" | "inverted",
            "t10y2y": float,
            "equity_multiplier": float,  # steep=1.1, flat=0.9, inverted=0.6
            "recession_signal": bool,
        }
    """
    if t10y2y > 1.0:
        state = "steep"
        equity_multiplier = 1.1
    elif t10y2y >= 0.0:
        state = "flat"
        equity_multiplier = 0.9
    else:
        state = "inverted"
        equity_multiplier = 0.6

    recession_signal = t10y2y < -0.25

    return {
        "state": state,
        "t10y2y": t10y2y,
        "equity_multiplier": equity_multiplier,
        "recession_signal": recession_signal,
    }


# ---------------------------------------------------------------------------
# Signal 5 — DXY Momentum
# ---------------------------------------------------------------------------


def dxy_momentum_state(uup_60d_zscore: float) -> dict:
    """
    Classify USD momentum using the UUP (Invesco DB US Dollar Index Bullish
    Fund) 60-day z-score.

    Thresholds:
        Z < –1.0    → "weak"    (risk-on, dollar selling)
        –1.0–1.5    → "neutral"
        Z > 1.5     → "strong"  (risk-off, dollar buying)

    Returns::

        {
            "state": "weak" | "neutral" | "strong",
            "zscore": float,
            "equity_multiplier": float,  # weak=1.1, neutral=1.0, strong=0.75
        }
    """
    if uup_60d_zscore < -1.0:
        state = "weak"
        equity_multiplier = 1.1
    elif uup_60d_zscore <= 1.5:
        state = "neutral"
        equity_multiplier = 1.0
    else:
        state = "strong"
        equity_multiplier = 0.75

    return {
        "state": state,
        "zscore": uup_60d_zscore,
        "equity_multiplier": equity_multiplier,
    }


# ---------------------------------------------------------------------------
# Signal 6 — Market Breadth
# ---------------------------------------------------------------------------


def market_breadth_state(pct_above_200dma: float) -> dict:
    """
    Classify market participation health using the percentage of S&P 500
    constituent stocks trading above their 200-day moving average.

    Thresholds:
        > 70    → "strong"  (healthy bull participation)
        40–70   → "normal"
        20–40   → "weak"
        < 20    → "panic"   (broad capitulation)

    Returns::

        {
            "state": "strong" | "normal" | "weak" | "panic",
            "pct_above_200dma": float,
            "equity_multiplier": float,  # strong=1.2, normal=1.0, weak=0.6, panic=0.2
        }
    """
    if pct_above_200dma > 70:
        state = "strong"
        equity_multiplier = 1.2
    elif pct_above_200dma >= 40:
        state = "normal"
        equity_multiplier = 1.0
    elif pct_above_200dma >= 20:
        state = "weak"
        equity_multiplier = 0.6
    else:
        state = "panic"
        equity_multiplier = 0.2

    return {
        "state": state,
        "pct_above_200dma": pct_above_200dma,
        "equity_multiplier": equity_multiplier,
    }
