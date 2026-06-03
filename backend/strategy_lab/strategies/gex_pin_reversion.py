"""
GEX Pin Reversion
Gamma Exposure (GEX) creates magnetic price levels where market makers
must hedge, pulling price back toward high-GEX strikes.

Since we don't have options data in paper phase, use a simplified proxy:
- Use round number levels (nearest $5, $10 for SPY/QQQ)
- Price within 0.5% of round level AND vol is compressing = reversion signal
- Vol compression: ATR(14) < 0.8 * ATR(30)

Signal:
  - Find nearest round $5 level
  - If |price - round_level| < 0.5%: potential pin
  - If ATR(14) < 0.8 * ATR(30): vol compressing
  - If price approached pin from below: buy (revert to pin)
  - If price approached pin from above: sell (revert to pin)
  - confidence = (1 - |deviation_pct| / 0.005) * 0.65  # max 0.65

Note: Real GEX requires Polygon options data. This is proxy implementation.
Regime: skip if VIX > 25 (gamma dynamics break down in high vol).
"""
from __future__ import annotations

import logging
from statistics import mean

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "gex_pin_reversion"

# Round level granularity
ROUND_LEVEL_STEP = 5.0

# Pin proximity threshold: within 0.5% of round level
PIN_PROXIMITY_PCT = 0.005

# Vol compression: ATR(14) < this fraction of ATR(30)
VOL_COMPRESSION_RATIO = 0.8

# Max confidence for this proxy strategy
MAX_CONFIDENCE = 0.65

# Regime: skip when VIX is high or panic
SKIP_VIX_REGIMES = frozenset({"high", "panic"})

# Lookback periods for ATR
ATR_SHORT = 14
ATR_LONG = 30


def _nearest_round_level(price: float, step: float = ROUND_LEVEL_STEP) -> float:
    """Return the nearest multiple of `step` to `price`."""
    return round(round(price / step) * step, 2)


def _compute_atr(bars: list[dict], period: int) -> float:
    """Compute Average True Range over `period` bars."""
    if len(bars) < 2:
        return 0.0
    true_ranges: list[float] = []
    for i in range(1, min(len(bars), period + 1)):
        high = bars[i].get("h", bars[i].get("high", 0))
        low = bars[i].get("l", bars[i].get("low", 0))
        prev_close = bars[i - 1].get("c", bars[i - 1].get("close", 0))
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(tr)
    return mean(true_ranges) if true_ranges else 0.0


def _approach_direction(bars: list[dict], round_level: float) -> str | None:
    """
    Determine whether price approached the pin level from below or above.
    Look at the last 3 bars before the current one to detect direction.
    Returns 'from_below', 'from_above', or None if inconclusive.
    """
    if len(bars) < 4:
        return None
    # Use the bar 3 periods ago to determine prior position
    prior_bar = bars[-4]
    prior_close = prior_bar.get("c", prior_bar.get("close", 0))
    if prior_close <= 0:
        return None
    if prior_close < round_level:
        return "from_below"
    if prior_close > round_level:
        return "from_above"
    return None


def generate_signals(
    bars: dict[str, list[dict]],
    profile_config: dict,
    regime: dict,
) -> list[Signal]:
    """Generate GEX pin reversion signals using round-number proxy levels.

    bars: {symbol: [{t, o, h, l, c, v}, ...]} sorted oldest-first.
    profile_config: loaded YAML profile.
    regime: {vix_regime, trend_regime, vol_pctile, ...}.
    """
    vix_regime = regime.get("vix_regime", "mid")
    if vix_regime in SKIP_VIX_REGIMES:
        logger.info(f"GEX pin reversion: skipping — vix_regime={vix_regime}")
        return []

    signals: list[Signal] = []

    for symbol, bar_list in bars.items():
        if not bar_list or len(bar_list) < ATR_LONG + 1:
            continue

        current_bar = bar_list[-1]
        current_price = current_bar.get("c", current_bar.get("close", 0))
        if current_price <= 0:
            continue

        # Compute round level
        round_level = _nearest_round_level(current_price, ROUND_LEVEL_STEP)
        if round_level <= 0:
            continue

        deviation_pct = abs(current_price - round_level) / round_level
        if deviation_pct >= PIN_PROXIMITY_PCT:
            # Not close enough to a pin level
            continue

        # Vol compression check
        atr_short = _compute_atr(bar_list, ATR_SHORT)
        atr_long = _compute_atr(bar_list, ATR_LONG)
        if atr_long <= 0:
            continue

        if atr_short >= VOL_COMPRESSION_RATIO * atr_long:
            # Vol not compressing
            continue

        # Determine reversion direction
        approach = _approach_direction(bar_list, round_level)
        if approach is None:
            continue

        if approach == "from_below":
            # Price came up from below and is hovering near pin — expect it to
            # be pulled back toward the pin (or stick to it). Enter buy.
            side = "buy"
        else:
            # Price came down from above and is hovering near pin — enter sell.
            side = "sell"

        confidence = (1.0 - deviation_pct / PIN_PROXIMITY_PCT) * MAX_CONFIDENCE
        confidence = max(0.0, min(MAX_CONFIDENCE, confidence))

        reason = (
            f"GEX pin reversion: {symbol} price {current_price:.2f} within "
            f"{deviation_pct * 100:.3f}% of round level ${round_level:.0f}; "
            f"ATR14/ATR30={atr_short / atr_long:.2f} (compressing); "
            f"approached {approach}; side={side}"
        )

        signals.append(Signal(
            symbol=symbol,
            side=side,
            confidence=confidence,
            size_hint=round(confidence * 0.7, 3),
            reason=reason,
            strategy=STRATEGY_NAME,
        ))

    return signals
