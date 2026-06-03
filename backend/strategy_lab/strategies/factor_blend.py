"""Factor Blend strategy (stock_lt).

Blends momentum (12-1 month), value (P/E relative), quality (ROE).
Since fundamental data is unavailable, uses 12-month price momentum only.
12-month momentum = (current - price_12mo_ago) / price_12mo_ago.
Buy top 20% by momentum score across the universe.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "factor_blend"
TOP_PERCENTILE = 0.20  # Buy top 20% by momentum score

# Default factor weights (must sum to 1.0)
_DEFAULT_WEIGHTS = {
    "momentum": 0.40,
    "value": 0.35,
    "quality": 0.25,
}


def compute_12mo_momentum(closes: list[float]) -> float:
    """Compute 12-month (12*21 = ~252 bars) price momentum.

    Returns (current - price_12mo_ago) / price_12mo_ago, or 0 if insufficient data.
    """
    bars_required = 252
    if len(closes) < bars_required:
        return 0.0
    price_now = closes[-1]
    price_12mo = closes[-bars_required]
    if price_12mo <= 0:
        return 0.0
    return (price_now - price_12mo) / price_12mo


def rank_universe(universe: Dict[str, list[float]]) -> List[str]:
    """Rank symbols by 12-month momentum. Returns list sorted desc."""
    scores = {sym: compute_12mo_momentum(closes) for sym, closes in universe.items()}
    return sorted(scores, key=lambda s: scores[s], reverse=True)


def generate_signals_for_universe(universe: Dict[str, list[float]]) -> List[Signal]:
    """Generate buy signals for the top 20% of symbols by 12-month momentum.

    Args:
        universe: {symbol: closes_list} mapping.
    """
    if not universe:
        return []

    scores = {sym: compute_12mo_momentum(closes) for sym, closes in universe.items()}
    ranked = sorted(scores, key=lambda s: scores[s], reverse=True)
    cutoff = max(1, int(len(ranked) * TOP_PERCENTILE))
    top_symbols = ranked[:cutoff]

    signals = []
    for sym in top_symbols:
        mom = scores[sym]
        # Normalise: confidence = clamp(momentum_pct / 0.50, 0.3, 0.9)
        confidence = max(0.3, min(0.9, abs(mom) / 0.50))
        signals.append(Signal(
            symbol=sym,
            side="buy",
            confidence=confidence,
            size_hint=confidence,
            reason=f"Factor blend buy: 12mo momentum={mom:.2%} (top {TOP_PERCENTILE:.0%})",
            strategy=STRATEGY_NAME,
        ))
    return signals


# Backwards-compat single-symbol interface
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
