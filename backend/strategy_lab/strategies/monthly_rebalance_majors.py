"""
Monthly Rebalance — crypto_lt.
First Tuesday monthly: compare current allocation vs target.
Sell overweight (>5% above target), buy underweight (>5% below target).
Target: BTC 40%, ETH 30%, SOL 15%, AVAX 10%, LINK 5%.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "monthly_rebalance_majors"

# Default target weights
DEFAULT_TARGET_WEIGHTS: dict[str, float] = {
    "BTC/USD": 0.40,
    "ETH/USD": 0.30,
    "SOL/USD": 0.15,
    "AVAX/USD": 0.10,
    "LINK/USD": 0.05,
}

# Rebalance threshold — only act if deviation > 5%
REBALANCE_THRESHOLD = 0.05

# First Tuesday of month: weekday=1 (Tuesday), and day 1-7
REBALANCE_WEEKDAY = 1  # Tuesday
REBALANCE_HOUR = 10


def _is_rebalance_day(now: datetime) -> bool:
    """Return True if today is the first Tuesday of the month at 10am UTC."""
    return (
        now.weekday() == REBALANCE_WEEKDAY
        and 1 <= now.day <= 7
        and now.hour == REBALANCE_HOUR
    )


def generate_signals(
    bars: dict[str, list[dict]],
    profile_config: dict,
    regime: dict,
) -> list[Signal]:
    """Generate rebalance buy/sell signals on first Tuesday of month at 10am UTC.

    Reads current_weights from regime context (keyed as 'portfolio_weights').
    Without current weights, emits buy signals for all underweight symbols
    relative to target (conservative fallback).

    Args:
        bars: {symbol: [{t, o, h, l, c, v}, ...]} oldest-first.
        profile_config: Profile YAML dict (expects universe.target_weights).
        regime: Regime context dict (may contain portfolio_weights: {symbol: float}).

    Returns:
        List of Signal objects.
    """
    now_utc = datetime.now(timezone.utc)

    if not _is_rebalance_day(now_utc):
        logger.debug(
            "[%s] Skipping — not rebalance day (weekday=%d, day=%d, hour=%d)",
            STRATEGY_NAME, now_utc.weekday(), now_utc.day, now_utc.hour,
        )
        return []

    universe = profile_config.get("universe", {})
    if isinstance(universe, dict):
        symbols = universe.get("symbols", list(DEFAULT_TARGET_WEIGHTS.keys()))
        target_weights = universe.get("target_weights", DEFAULT_TARGET_WEIGHTS)
    else:
        symbols = list(DEFAULT_TARGET_WEIGHTS.keys())
        target_weights = DEFAULT_TARGET_WEIGHTS

    # Current portfolio weights from regime context (or assume equal if not provided)
    current_weights: dict[str, float] = regime.get("portfolio_weights", {})
    if not current_weights:
        # No current weight data — assume equal weighting as baseline
        equal_wt = 1.0 / max(1, len(symbols))
        current_weights = {s: equal_wt for s in symbols}
        logger.debug("[%s] No portfolio_weights in regime — using equal baseline", STRATEGY_NAME)

    signals: list[Signal] = []

    for symbol in symbols:
        target = target_weights.get(symbol, 0.0)
        current = current_weights.get(symbol, 0.0)
        deviation = current - target  # positive = overweight, negative = underweight

        if abs(deviation) < REBALANCE_THRESHOLD:
            continue  # within band — no action

        if deviation > 0:
            # Overweight — sell down to target
            confidence = min(0.9, deviation / 0.20)
            size_hint = min(1.0, deviation / target) if target > 0 else deviation
            signals.append(Signal(
                symbol=symbol,
                side="sell",
                confidence=confidence,
                size_hint=min(1.0, size_hint),
                reason=(
                    f"Monthly rebalance SELL: {symbol} is {deviation:.1%} overweight "
                    f"(current={current:.1%}, target={target:.1%})"
                ),
                strategy=STRATEGY_NAME,
            ))

        else:
            # Underweight — buy up to target
            abs_dev = abs(deviation)
            confidence = min(0.9, abs_dev / 0.20)
            size_hint = min(1.0, abs_dev / target) if target > 0 else abs_dev
            signals.append(Signal(
                symbol=symbol,
                side="buy",
                confidence=confidence,
                size_hint=min(1.0, size_hint),
                reason=(
                    f"Monthly rebalance BUY: {symbol} is {abs_dev:.1%} underweight "
                    f"(current={current:.1%}, target={target:.1%})"
                ),
                strategy=STRATEGY_NAME,
            ))

    logger.info("[%s] Rebalance signals generated: %d", STRATEGY_NAME, len(signals))
    return signals
