"""
DCA BTC+ETH for crypto_lt.
Every Monday 10am UTC, buy BTC/USD and ETH/USD in equal dollar amounts.
SOL/AVAX/LINK get smaller allocation (20% each, BTC+ETH split 40/40).
No stops. Hold indefinitely. Monthly rebalance to target weights.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "dca_btc_eth"

# DCA cadence: Monday (weekday=0) at ~10am UTC
DCA_WEEKDAY = 0  # Monday
DCA_HOUR = 10

# Target allocation weights
TARGET_WEIGHTS: dict[str, float] = {
    "BTC/USD": 0.40,
    "ETH/USD": 0.40,
    "SOL/USD": 0.067,
    "AVAX/USD": 0.067,
    "LINK/USD": 0.066,
}


def _is_dca_window(now: datetime) -> bool:
    """Return True if we're in the Monday 10am UTC DCA window."""
    return now.weekday() == DCA_WEEKDAY and now.hour == DCA_HOUR


def generate_signals(
    bars: dict[str, list[dict]],
    profile_config: dict,
    regime: dict,
) -> list[Signal]:
    """Generate DCA buy signals on Monday 10am UTC for configured crypto_lt universe.

    All signals are conviction buys (confidence=1.0). Size is proportional to
    target allocation weights.

    Args:
        bars: {symbol: [{t, o, h, l, c, v}, ...]} oldest-first.
        profile_config: Profile YAML dict (expects universe.symbols and universe.target_weights).
        regime: Regime context dict (unused — DCA ignores regime).

    Returns:
        List of Signal objects.
    """
    now_utc = datetime.now(timezone.utc)

    if not _is_dca_window(now_utc):
        logger.debug("[%s] Skipping — not DCA window (weekday=%d, hour=%d)", STRATEGY_NAME, now_utc.weekday(), now_utc.hour)
        return []

    universe = profile_config.get("universe", {})
    if isinstance(universe, dict):
        symbols = universe.get("symbols", list(TARGET_WEIGHTS.keys()))
        target_weights = universe.get("target_weights", TARGET_WEIGHTS)
    else:
        symbols = list(TARGET_WEIGHTS.keys())
        target_weights = TARGET_WEIGHTS

    position_size_pct = profile_config.get("position_size_pct", 20.0)
    universe_size = max(1, len(symbols))

    signals: list[Signal] = []

    for symbol in symbols:
        # size_hint proportional to target weight; fallback to equal split
        weight = target_weights.get(symbol, 1.0 / universe_size)
        size_hint = min(1.0, weight)

        signals.append(Signal(
            symbol=symbol,
            side="buy",
            confidence=1.0,
            size_hint=size_hint,
            reason=(
                f"DCA Monday buy: target_weight={weight:.1%}, "
                f"position_size={position_size_pct:.1f}% of allocation"
            ),
            strategy=STRATEGY_NAME,
        ))
        logger.info("[%s] DCA signal: BUY %s size_hint=%.3f", STRATEGY_NAME, symbol, size_hint)

    return signals
