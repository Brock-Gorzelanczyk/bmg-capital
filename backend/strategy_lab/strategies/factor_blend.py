"""
Factor Blend — stock_lt monthly rebalance.
Equal-weight top 20 by composite score:
  - Momentum (12-1m): 40%
  - Quality (ROE proxy via price stability): 20%
  - Value (low 52w high = cheap): 20%
  - Low volatility (30d realized vol): 20%
Rebalance monthly. No stops. Mean-revert on drawdown.
"""
from __future__ import annotations

import logging
import math
from typing import Dict, List, Optional

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "factor_blend"

# Lookbacks
MOMENTUM_LONG_BARS = 252   # 12 months
MOMENTUM_SHORT_BARS = 21   # skip last month
QUALITY_WINDOW = 63        # 3-month price stability window
VOLATILITY_WINDOW = 21     # 30 calendar days ~ 21 trading days

# Factor weights (must sum to 1.0)
FACTOR_WEIGHTS = {
    "momentum": 0.40,
    "quality": 0.20,
    "value": 0.20,
    "low_vol": 0.20,
}

# Top N to hold
TOP_N = 20
# Backwards-compat top-percentile (kept for old callers)
TOP_PERCENTILE = 0.20


# ---------------------------------------------------------------------------
# Factor computation helpers
# ---------------------------------------------------------------------------

def compute_12mo_momentum(closes: list[float]) -> float:
    """12-1 month momentum (skip last month to avoid reversal)."""
    if len(closes) < MOMENTUM_LONG_BARS:
        return 0.0
    base = closes[-MOMENTUM_LONG_BARS]
    end = closes[-MOMENTUM_SHORT_BARS] if len(closes) > MOMENTUM_SHORT_BARS else closes[-1]
    if base <= 0:
        return 0.0
    return (end - base) / base


def compute_quality_score(closes: list[float]) -> float:
    """Quality proxy: inverse of price coefficient of variation over 63 days.

    Low CV = stable price = high quality proxy.
    Returns a score in [0, 1] where 1 = highest stability.
    """
    sample = closes[-QUALITY_WINDOW:] if len(closes) >= QUALITY_WINDOW else closes
    if len(sample) < 5:
        return 0.5
    mean = sum(sample) / len(sample)
    if mean <= 0:
        return 0.5
    variance = sum((c - mean) ** 2 for c in sample) / len(sample)
    std = math.sqrt(variance)
    cv = std / mean
    # Convert CV to a score: lower CV = higher score
    # Typical CV range ~0.01 (very stable) to ~0.30 (volatile)
    score = max(0.0, 1.0 - cv / 0.30)
    return min(1.0, score)


def compute_value_score(closes: list[float]) -> float:
    """Value proxy: how far below the 52-week high.

    Cheap stocks are significantly below their 52w high.
    Score = 1.0 - (current / 52w_high); 0 = at high, ~0.5 = 50% below high.
    """
    if len(closes) < 2:
        return 0.0
    window = closes[-252:] if len(closes) >= 252 else closes
    max_52w = max(window)
    if max_52w <= 0:
        return 0.0
    current = closes[-1]
    return max(0.0, min(1.0, 1.0 - current / max_52w))


def compute_low_vol_score(closes: list[float]) -> float:
    """Low-volatility factor: inverse of 21-day realized vol.

    Returns score in [0, 1] where 1 = lowest volatility.
    """
    sample = closes[-VOLATILITY_WINDOW:] if len(closes) >= VOLATILITY_WINDOW else closes
    if len(sample) < 5:
        return 0.5
    returns = [
        (sample[i] - sample[i - 1]) / sample[i - 1]
        for i in range(1, len(sample))
        if sample[i - 1] > 0
    ]
    if not returns:
        return 0.5
    mean_r = sum(returns) / len(returns)
    variance = sum((r - mean_r) ** 2 for r in returns) / len(returns)
    realized_vol = math.sqrt(variance * 252)  # annualised
    # Typical annualised vol range ~0.10 (low) to ~0.80 (high)
    score = max(0.0, 1.0 - realized_vol / 0.80)
    return min(1.0, score)


def compute_composite_score(closes: list[float]) -> float:
    """Weighted composite of all four factors."""
    mom = compute_12mo_momentum(closes)
    # Normalise momentum to [0,1]: assume range [-0.50, +0.80]
    mom_norm = max(0.0, min(1.0, (mom + 0.50) / 1.30))

    quality = compute_quality_score(closes)
    value = compute_value_score(closes)
    low_vol = compute_low_vol_score(closes)

    return (
        FACTOR_WEIGHTS["momentum"] * mom_norm
        + FACTOR_WEIGHTS["quality"] * quality
        + FACTOR_WEIGHTS["value"] * value
        + FACTOR_WEIGHTS["low_vol"] * low_vol
    )


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def rank_universe(universe: Dict[str, list[float]]) -> List[str]:
    """Rank symbols by composite factor score. Returns list sorted desc."""
    scores = {sym: compute_composite_score(closes) for sym, closes in universe.items()}
    return sorted(scores, key=lambda s: scores[s], reverse=True)


def generate_signals(
    bars: dict[str, list[dict]],
    profile_config: dict,
    regime: dict,
) -> list[Signal]:
    """Generate factor-blend long signals for the top 20 by composite score.

    bars: {symbol: [{t, o, h, l, c, v}, ...]} sorted oldest-first (daily bars).
    profile_config: loaded YAML profile.
    regime: {vix_regime, trend_regime, vol_pctile, btc_dominance, btc_funding_rate}.
    """
    vix_regime = regime.get("vix_regime", "normal")

    universe: dict[str, list[float]] = {
        sym: [b["c"] for b in bar_list]
        for sym, bar_list in bars.items()
        if bar_list and len(bar_list) >= MOMENTUM_LONG_BARS
    }

    if not universe:
        return []

    scores = {sym: compute_composite_score(closes) for sym, closes in universe.items()}
    ranked = sorted(scores, key=lambda s: scores[s], reverse=True)
    top_symbols = ranked[:TOP_N]

    signals: list[Signal] = []
    for sym in top_symbols:
        score = scores[sym]
        confidence = max(0.3, min(0.9, score))
        if vix_regime == "high":
            confidence *= 0.80
        confidence = max(0.0, min(1.0, confidence))

        signals.append(Signal(
            symbol=sym,
            side="buy",
            confidence=confidence,
            size_hint=confidence,
            reason=(
                f"Factor blend top-{TOP_N}: composite_score={score:.3f} "
                f"(mom={FACTOR_WEIGHTS['momentum']:.0%}, "
                f"quality={FACTOR_WEIGHTS['quality']:.0%}, "
                f"value={FACTOR_WEIGHTS['value']:.0%}, "
                f"low_vol={FACTOR_WEIGHTS['low_vol']:.0%})"
            ),
            strategy=STRATEGY_NAME,
        ))
    return signals


def generate_signals_for_universe(universe: Dict[str, list[float]]) -> List[Signal]:
    """Generate buy signals for the top symbols by composite score.

    Args:
        universe: {symbol: closes_list} mapping.
    """
    if not universe:
        return []

    scores = {sym: compute_composite_score(closes) for sym, closes in universe.items()}
    ranked = sorted(scores, key=lambda s: scores[s], reverse=True)
    cutoff = max(1, int(len(ranked) * TOP_PERCENTILE))
    top_symbols = ranked[:cutoff]

    signals = []
    for sym in top_symbols:
        score = scores[sym]
        confidence = max(0.3, min(0.9, score))
        signals.append(Signal(
            symbol=sym,
            side="buy",
            confidence=confidence,
            size_hint=confidence,
            reason=f"Factor blend buy: composite_score={score:.3f} (top {TOP_PERCENTILE:.0%})",
            strategy=STRATEGY_NAME,
        ))
    return signals


# ---------------------------------------------------------------------------
# Backwards-compat single-symbol interface
# ---------------------------------------------------------------------------

_DEFAULT_WEIGHTS = {
    "momentum": 0.40,
    "value": 0.35,
    "quality": 0.25,
}


def generate_signal(
    symbol: str,
    momentum_score: float,
    value_score: float = 0.0,
    quality_score: float = 0.0,
    buy_threshold: float = 0.4,
    sell_threshold: float = -0.4,
    weights: Optional[dict] = None,
) -> Optional[Signal]:
    """Blended-factor single-symbol wrapper (kept for backwards compatibility)."""
    w = weights or _DEFAULT_WEIGHTS
    score = (
        w["momentum"] * momentum_score
        + w["value"] * value_score
        + w["quality"] * quality_score
    )
    if score >= buy_threshold:
        confidence = max(0.3, min(0.9, (score - buy_threshold) / (1.0 - buy_threshold)))
        return Signal(
            symbol=symbol,
            side="buy",
            confidence=confidence,
            size_hint=confidence,
            reason=f"Factor blend score {score:.3f} (mom={momentum_score:.2f})",
            strategy=STRATEGY_NAME,
        )
    if score <= sell_threshold:
        confidence = max(0.3, min(0.9, (abs(score) - abs(sell_threshold)) / (1.0 - abs(sell_threshold))))
        return Signal(
            symbol=symbol,
            side="sell",
            confidence=confidence,
            size_hint=confidence,
            reason=f"Factor blend score {score:.3f} below sell threshold {sell_threshold}",
            strategy=STRATEGY_NAME,
        )
    return None
