"""
Crypto Weekend Momentum.
Crypto tends to trend on weekends with lower liquidity amplifying moves.
Long Sunday if weekly return > 5%. Short if < -5%.
Adjust size down 30% vs weekday (lower liquidity).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "crypto_weekend_momentum"

# 7d on hourly bars ≈ 168 bars; use 336 for a broader window check
BARS_7D_HOURLY = 168
WEEKLY_RETURN_THRESHOLD = 0.05  # 5%
WEEKEND_SIZE_DISCOUNT = 0.7    # 30% smaller for liquidity


def generate_signals(
    bars: dict[str, list[dict]],
    profile_config: dict,
    regime: dict,
) -> list[Signal]:
    """Generate weekend momentum signals from hourly OHLCV bars.

    Only fires on Saturday or Sunday UTC. Uses 7d return from hourly bars.

    Args:
        bars: {symbol: [{t, o, h, l, c, v}, ...]} oldest-first, hourly bars.
        profile_config: Profile YAML dict.
        regime: Regime context dict.

    Returns:
        List of Signal objects.
    """
    # Only fire on weekends
    now_utc = datetime.now(timezone.utc)
    weekday = now_utc.weekday()  # 5=Saturday, 6=Sunday
    if weekday not in (5, 6):
        logger.debug("[%s] Skipping — not a weekend (weekday=%d)", STRATEGY_NAME, weekday)
        return []

    universe = profile_config.get("universe", {})
    if isinstance(universe, dict):
        symbols = universe.get("symbols", list(bars.keys()))
    else:
        symbols = list(bars.keys())

    signals: list[Signal] = []

    for symbol in symbols:
        symbol_bars = bars.get(symbol, [])
        if len(symbol_bars) < BARS_7D_HOURLY + 1:
            logger.debug("[%s] %s: insufficient bars (%d)", STRATEGY_NAME, symbol, len(symbol_bars))
            continue

        closes = [b["c"] for b in symbol_bars]
        current_close = closes[-1]
        close_7d_ago = closes[-(BARS_7D_HOURLY + 1)]

        if close_7d_ago <= 0:
            continue

        weekly_return = (current_close - close_7d_ago) / close_7d_ago

        if weekly_return > WEEKLY_RETURN_THRESHOLD:
            raw_conf = abs(weekly_return) / 0.15
            confidence = min(0.8, raw_conf)
            size_hint = min(1.0, confidence * WEEKEND_SIZE_DISCOUNT)
            signals.append(Signal(
                symbol=symbol,
                side="buy",
                confidence=confidence,
                size_hint=size_hint,
                reason=(
                    f"Weekend momentum long: 7d_ret={weekly_return:.3f} > {WEEKLY_RETURN_THRESHOLD:.2f} "
                    f"(size discounted {int((1-WEEKEND_SIZE_DISCOUNT)*100)}% for weekend liquidity)"
                ),
                strategy=STRATEGY_NAME,
            ))

        elif weekly_return < -WEEKLY_RETURN_THRESHOLD:
            raw_conf = abs(weekly_return) / 0.15
            confidence = min(0.8, raw_conf)
            size_hint = min(1.0, confidence * WEEKEND_SIZE_DISCOUNT)
            signals.append(Signal(
                symbol=symbol,
                side="sell",
                confidence=confidence,
                size_hint=size_hint,
                reason=(
                    f"Weekend momentum short: 7d_ret={weekly_return:.3f} < -{WEEKLY_RETURN_THRESHOLD:.2f} "
                    f"(size discounted {int((1-WEEKEND_SIZE_DISCOUNT)*100)}% for weekend liquidity)"
                ),
                strategy=STRATEGY_NAME,
            ))

    return signals
