"""
Dividend Growth strategy for stock_lt.
Proxy: track stocks that have consistently increased over time
using 12-month price appreciation as quality signal (dividends
not available in paper API without premium data).
Hold top-20 equal-weight, monthly rebalance.
"""
from __future__ import annotations

import logging
import math
from typing import Dict, List

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "dividend_growth"

# Daily bars required
MIN_BARS = 252

# Trend consistency windows (quarterly checks)
QUARTER_BARS = 63

# Number of top symbols to hold
TOP_N = 20

# Minimum total 12-month appreciation to qualify
MIN_12M_RETURN = 0.05   # 5%


def _compute_trend_consistency(closes: list[float]) -> float:
    """Measure how consistently the stock has been appreciating.

    Splits the last 252 bars into four quarterly windows.
    Returns fraction of quarters with positive return (0.0-1.0).
    Score of 1.0 means every quarter was positive (dividend-growth-like consistency).
    """
    if len(closes) < MIN_BARS:
        return 0.0
    quarterly_returns = []
    for i in range(4):
        start_idx = -(MIN_BARS - i * QUARTER_BARS)
        end_idx = -(MIN_BARS - (i + 1) * QUARTER_BARS) if (i + 1) * QUARTER_BARS < MIN_BARS else -1
        start_price = closes[start_idx]
        end_price = closes[end_idx] if end_idx != -1 else closes[-1]
        if start_price > 0:
            quarterly_returns.append((end_price - start_price) / start_price)
    if not quarterly_returns:
        return 0.0
    positive_quarters = sum(1 for r in quarterly_returns if r > 0)
    return positive_quarters / len(quarterly_returns)


def _compute_realized_vol(closes: list[float], window: int = 21) -> float:
    """Annualised realised volatility over `window` bars."""
    sample = closes[-window:] if len(closes) >= window else closes
    if len(sample) < 5:
        return 1.0
    returns = [
        (sample[i] - sample[i - 1]) / sample[i - 1]
        for i in range(1, len(sample))
        if sample[i - 1] > 0
    ]
    if not returns:
        return 1.0
    mean_r = sum(returns) / len(returns)
    variance = sum((r - mean_r) ** 2 for r in returns) / len(returns)
    return math.sqrt(variance * 252)


def _compute_composite(closes: list[float]) -> float | None:
    """Composite score = consistency * appreciation / vol.

    Favours consistent appreciators with low volatility (like quality dividend growers).
    """
    if len(closes) < MIN_BARS:
        return None
    price_12m_ago = closes[-MIN_BARS]
    if price_12m_ago <= 0:
        return None
    total_12m_return = (closes[-1] - price_12m_ago) / price_12m_ago
    if total_12m_return < MIN_12M_RETURN:
        return None

    consistency = _compute_trend_consistency(closes)
    vol = _compute_realized_vol(closes)
    if vol <= 0:
        return None

    # Sharpe-like composite: consistent appreciation adjusted for vol
    return (total_12m_return * consistency) / vol


def generate_signals(
    bars: dict[str, list[dict]],
    profile_config: dict,
    regime: dict,
) -> list[Signal]:
    """Generate dividend-growth proxy signals for the top 20 by composite score.

    bars: {symbol: [{t, o, h, l, c, v}, ...]} sorted oldest-first (daily bars).
    profile_config: loaded YAML profile.
    regime: {vix_regime, trend_regime, vol_pctile, btc_dominance, btc_funding_rate}.
    """
    vix_regime = regime.get("vix_regime", "normal")

    scores: dict[str, float] = {}
    for symbol, bar_list in bars.items():
        if not bar_list or len(bar_list) < MIN_BARS:
            continue
        closes = [b["c"] for b in bar_list]
        score = _compute_composite(closes)
        if score is not None and score > 0:
            scores[symbol] = score

    if not scores:
        return []

    ranked = sorted(scores, key=lambda s: scores[s], reverse=True)
    top_symbols = ranked[:TOP_N]

    # Normalise scores for confidence
    max_score = scores[top_symbols[0]] if top_symbols else 1.0

    signals: list[Signal] = []
    for sym in top_symbols:
        score = scores[sym]
        confidence = max(0.3, min(0.9, score / max_score * 0.9))
        if vix_regime == "high":
            confidence *= 0.80
        confidence = max(0.0, min(1.0, confidence))

        closes = [b["c"] for b in bars[sym]]
        price_12m_ago = closes[-MIN_BARS]
        total_return = (closes[-1] - price_12m_ago) / price_12m_ago if price_12m_ago > 0 else 0.0
        consistency = _compute_trend_consistency(closes)

        signals.append(Signal(
            symbol=sym,
            side="buy",
            confidence=confidence,
            size_hint=confidence,
            reason=(
                f"Dividend growth proxy: 12m_return={total_return:.2%}; "
                f"quarterly_consistency={consistency:.0%}; "
                f"composite_score={score:.3f}"
            ),
            strategy=STRATEGY_NAME,
        ))

    return signals
