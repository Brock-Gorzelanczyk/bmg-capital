"""
Crypto Quant Aggressive — S8: Range Break Retest

Setup:
  1. Identify a 4h consolidation range (high and low of prior 4h window, 16 bars of 15m).
  2. Range was broken within the last 2h (8 bars).
  3. Price has since pulled back to retest the broken level.
  4. Retest held (current close has NOT crossed back through the level by > 0.1%).

Entry: with the original breakout direction (long after upside break, short after downside break).
Target: 1R further from the entry (using profile stop_loss_pct as R).
Time-stop: 8h.

Bars: 15m (profile scan_timeframe=15m).
"""
from __future__ import annotations

import logging

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "crypto_quant_range_break_retest"

UNIVERSE = [
    "BTC/USD", "ETH/USD", "SOL/USD", "BNB/USD", "XRP/USD", "ADA/USD",
    "AVAX/USD", "POL/USD", "DOT/USD", "LINK/USD", "ATOM/USD", "NEAR/USD",
    "ARB/USD", "OP/USD", "INJ/USD", "SUI/USD", "APT/USD", "TIA/USD",
    "DOGE/USD", "SHIB/USD",
]

# 4h in 15m bars
RANGE_PERIOD_BARS = 16
# 2h in 15m bars (breakout must have happened within last 2h)
BREAK_LOOKBACK_BARS = 8
# Tolerance for "retest held" — price can touch the level but must not close through by > 0.1%
RETEST_TOLERANCE_PCT = 0.001


def generate_signals(
    bars: dict[str, list[dict]],
    profile_config: dict,
    regime: dict,
) -> list[Signal]:
    """Generate range-break-retest signals.

    Algorithm:
      - Define the 4h range from bars[-RANGE_PERIOD_BARS*2-1 : -RANGE_PERIOD_BARS-1]
        (the range window BEFORE the break window).
      - The break window is bars[-RANGE_PERIOD_BARS-1 : -1].
      - Check if the break window's high exceeded the range high (upside break)
        or the low undercut the range low (downside break).
      - Check if the current bar is close to the broken level (retest).
      - If retest holds, signal in breakout direction.

    Args:
        bars: {symbol: [{t, o, h, l, c, v}, ...]} oldest-first, 15m bars.
        profile_config: Profile YAML dict.
        regime: Regime context dict.

    Returns:
        List of Signal objects.
    """
    signals: list[Signal] = []
    universe = profile_config.get("universe", {})
    symbols = universe.get("symbols", UNIVERSE) if isinstance(universe, dict) else UNIVERSE

    import datetime as _dt
    is_weekend = _dt.datetime.utcnow().weekday() >= 5
    conf_bump = float(profile_config.get("risk_overlay", {}).get("weekend_confidence_boost", 0.05)) if is_weekend else 0.0

    # Stop loss from profile (used for 1R target)
    stop_pct = float(profile_config.get("stop_loss_pct", 1.5)) / 100.0

    min_bars_needed = RANGE_PERIOD_BARS * 2 + BREAK_LOOKBACK_BARS + 2
    for symbol in symbols:
        symbol_bars = bars.get(symbol, [])
        if len(symbol_bars) < min_bars_needed:
            logger.debug("[%s] %s: insufficient bars (%d, need %d)",
                         STRATEGY_NAME, symbol, len(symbol_bars), min_bars_needed)
            continue

        closes = [b["c"] for b in symbol_bars]
        highs = [b["h"] for b in symbol_bars]
        lows = [b["l"] for b in symbol_bars]

        current_close = closes[-1]
        if current_close <= 0:
            continue

        # Range window: the 4h period before the break window
        range_end = -(BREAK_LOOKBACK_BARS + 1)
        range_start = range_end - RANGE_PERIOD_BARS
        range_highs = highs[range_start:range_end]
        range_lows = lows[range_start:range_end]
        if not range_highs:
            continue

        range_high = max(range_highs)
        range_low = min(range_lows)

        # Break window: last 2h (8 bars), excluding the current bar
        break_window_highs = highs[-(BREAK_LOOKBACK_BARS + 1):-1]
        break_window_lows = lows[-(BREAK_LOOKBACK_BARS + 1):-1]
        if not break_window_highs:
            continue

        break_window_high = max(break_window_highs)
        break_window_low = min(break_window_lows)

        upside_break = break_window_high > range_high
        downside_break = break_window_low < range_low

        if not upside_break and not downside_break:
            continue

        # Retest: current price near the broken level
        if upside_break:
            broken_level = range_high
            # Retest holds if current close is within RETEST_TOLERANCE_PCT BELOW the level
            # (price came back to test support at old resistance, but didn't close back below)
            retest_in_zone = (
                current_close >= broken_level * (1 - 0.02) and    # within 2% of the level
                current_close <= broken_level * (1 + 0.015)        # not too far above
            )
            retest_held = current_close >= broken_level * (1 - RETEST_TOLERANCE_PCT)
            if not retest_in_zone or not retest_held:
                continue

            break_distance = (break_window_high - range_high) / range_high
            raw_conf = min(0.9, 0.60 + break_distance * 5)
            confidence = min(0.9, raw_conf + conf_bump)
            size_hint = min(1.0, confidence)

            signals.append(Signal(
                symbol=symbol,
                side="buy",
                confidence=confidence,
                size_hint=size_hint,
                reason=(
                    f"RANGE_BREAK_RETEST long: 4h range {range_low:.4f}-{range_high:.4f} "
                    f"broken upside to {break_window_high:.4f} in last 2h, "
                    f"retest @ {current_close:.4f} held broken level {broken_level:.4f}, "
                    f"target 1R={stop_pct * 100:.1f}% above entry, time-stop 8h"
                ),
                strategy=STRATEGY_NAME,
            ))

        elif downside_break:
            broken_level = range_low
            # Retest holds if current close is within RETEST_TOLERANCE_PCT ABOVE the level
            retest_in_zone = (
                current_close <= broken_level * (1 + 0.02) and    # within 2% of the level
                current_close >= broken_level * (1 - 0.015)        # not too far below
            )
            retest_held = current_close <= broken_level * (1 + RETEST_TOLERANCE_PCT)
            if not retest_in_zone or not retest_held:
                continue

            break_distance = (range_low - break_window_low) / range_low
            raw_conf = min(0.9, 0.60 + break_distance * 5)
            confidence = min(0.9, raw_conf + conf_bump)
            size_hint = min(1.0, confidence)

            signals.append(Signal(
                symbol=symbol,
                side="sell",
                confidence=confidence,
                size_hint=size_hint,
                reason=(
                    f"RANGE_BREAK_RETEST short: 4h range {range_low:.4f}-{range_high:.4f} "
                    f"broken downside to {break_window_low:.4f} in last 2h, "
                    f"retest @ {current_close:.4f} held broken level {broken_level:.4f}, "
                    f"target 1R={stop_pct * 100:.1f}% below entry, time-stop 8h"
                ),
                strategy=STRATEGY_NAME,
            ))

    return signals
