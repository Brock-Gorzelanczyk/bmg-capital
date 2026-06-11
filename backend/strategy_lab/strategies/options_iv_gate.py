"""
Shared IVR (IV Rank) gate for options income strategies.

Provides _estimate_ivr_proxy() — computes a 0-100 IV rank estimate
using realized vol percentile or VIX percentile from the regime dict.

Import in each options strategy with:
    from strategy_lab.strategies.options_iv_gate import (
        check_ivr_gate, _estimate_ivr_proxy
    )

Design:
  - Primary: use vix_pctile_252 from regime dict (already computed by regime_detector)
  - Fallback: compute realized vol percentile from the price series
  - Returns 50.0 (assume average IV) when insufficient data

Usage:
    ivr_gate = profile_config.get("ivr_gate", {})
    min_ivr = ivr_gate.get("minimum_ivr", 0)
    if min_ivr > 0:
        ivr = _estimate_ivr_proxy(closes, regime)
        if ivr < min_ivr:
            # skip this symbol
"""
from __future__ import annotations

import logging
import math

logger = logging.getLogger(__name__)


def _estimate_ivr_proxy(closes: list[float], regime: dict) -> float:
    """Proxy IV rank using recent realized vol percentile (252-day).

    Returns 0-100 estimate. Labeled as 'proxy' in reason strings.
    Falls back to VIX pctile from regime dict if available.

    Priority:
      1. vix_pctile_252 from regime dict (0.0-1.0 float → scaled to 0-100)
      2. Compute realized vol percentile from the provided price series

    Args:
        closes: List of closing prices, chronological order.
        regime: Regime dict from detect_regime().

    Returns:
        Float 0-100 representing estimated IV rank.
    """
    # Use vix_pctile_252 from regime if available
    vix_pctile = regime.get("vix_pctile_252")
    if vix_pctile is not None:
        try:
            rank = float(vix_pctile)
            # Handle both 0-1 and 0-100 formats
            if rank <= 1.0:
                rank = rank * 100
            return round(rank, 1)
        except (TypeError, ValueError):
            pass

    # Fallback: compute realized vol percentile from price series
    if len(closes) < 30:
        return 50.0  # assume average when insufficient data

    # Compute log returns
    returns: list[float] = []
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        curr = closes[i]
        if prev > 0 and curr > 0:
            returns.append(math.log(curr / prev))
        else:
            returns.append(0.0)

    # Recent 30-day realized vol (annualized)
    recent_window = returns[-30:]
    if len(recent_window) < 2:
        return 50.0
    mean_r = sum(recent_window) / len(recent_window)
    variance = sum((r - mean_r) ** 2 for r in recent_window) / len(recent_window)
    recent_vol = math.sqrt(variance) * math.sqrt(252)

    # Historical 252-day vol distribution: rolling 30-day windows
    if len(returns) >= 60:
        hist_vols: list[float] = []
        window_size = 30
        step = 5  # non-overlapping step to reduce autocorrelation
        for start in range(0, len(returns) - window_size, step):
            window = returns[start: start + window_size]
            if len(window) < 2:
                continue
            mean_w = sum(window) / len(window)
            var_w = sum((r - mean_w) ** 2 for r in window) / len(window)
            v = math.sqrt(var_w) * math.sqrt(252)
            hist_vols.append(v)

        if hist_vols:
            rank_pct = sum(1 for v in hist_vols if v < recent_vol) / len(hist_vols)
            logger.debug(
                "[ivr_gate] realized_vol_proxy: recent_vol=%.2f%% rank=%.0f%% (n=%d historical windows)",
                recent_vol * 100, rank_pct * 100, len(hist_vols),
            )
            return round(rank_pct * 100, 1)

    return 50.0  # insufficient history


def check_ivr_gate(
    symbol: str,
    closes: list[float],
    regime: dict,
    min_ivr: float,
    label_in_reason: bool = True,
) -> tuple[bool, float, str]:
    """Check if a symbol passes the IVR gate.

    Args:
        symbol:          Ticker symbol (for logging).
        closes:          Close prices list.
        regime:          Regime dict from detect_regime().
        min_ivr:         Minimum IVR threshold (0-100).
        label_in_reason: If True, return an IVR label for appending to reason strings.

    Returns:
        (passes_gate, ivr_estimate, ivr_label)
        - passes_gate: True if ivr_estimate >= min_ivr
        - ivr_estimate: float 0-100
        - ivr_label: string like "[IVR proxy: 65%]" for appending to reason
    """
    if min_ivr <= 0:
        return True, 0.0, ""

    ivr_estimate = _estimate_ivr_proxy(closes, regime)
    # Determine if VIX pctile was used (proxy) or per-symbol data (actual)
    source = "proxy" if regime.get("vix_pctile_252") is not None else "proxy"
    ivr_label = f"[IVR {source}: {ivr_estimate:.0f}%]" if label_in_reason else ""

    if ivr_estimate < min_ivr:
        logger.debug(
            "[ivr_gate] %s IVR %s %.0f%% < gate %.0f%%, skip",
            symbol, source, ivr_estimate, min_ivr,
        )
        return False, ivr_estimate, ivr_label

    return True, ivr_estimate, ivr_label
