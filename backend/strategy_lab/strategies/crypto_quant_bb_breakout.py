"""
Crypto Quant Aggressive — S2: Bollinger Band Breakout

Entry: 15m close outside Bollinger(20, 2) AND volume > 1.5x 20-bar avg → with the breakout
  - Close above upper band + volume surge → long
  - Close below lower band + volume surge → short
Exit: trailing stop at BB middle (SMA-20); time-stop 6h.

Bars: 15m (profile scan_timeframe=15m).
"""
from __future__ import annotations

import logging
import math

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "crypto_quant_bb_breakout"

UNIVERSE = [
    "BTC/USD", "ETH/USD", "SOL/USD", "BNB/USD", "XRP/USD", "ADA/USD",
    "AVAX/USD", "POL/USD", "DOT/USD", "LINK/USD", "ATOM/USD", "NEAR/USD",
    "ARB/USD", "OP/USD", "INJ/USD", "SUI/USD", "APT/USD", "TIA/USD",
    "DOGE/USD", "SHIB/USD",
]

BB_PERIOD = 20
BB_STDEV = 2.0
VOLUME_MULT = 1.5


def _bollinger(closes: list[float], period: int = BB_PERIOD, stdev_mult: float = BB_STDEV) -> tuple[float, float, float]:
    """Return (upper, middle, lower) Bollinger Bands from closes (oldest-first)."""
    if len(closes) < period:
        return 0.0, 0.0, 0.0
    window = closes[-period:]
    sma = sum(window) / period
    variance = sum((c - sma) ** 2 for c in window) / period
    std = math.sqrt(variance)
    return sma + stdev_mult * std, sma, sma - stdev_mult * std


def generate_signals(
    bars: dict[str, list[dict]],
    profile_config: dict,
    regime: dict,
) -> list[Signal]:
    """Generate Bollinger Band breakout signals.

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

    for symbol in symbols:
        symbol_bars = bars.get(symbol, [])
        if len(symbol_bars) < BB_PERIOD + 2:
            logger.debug("[%s] %s: insufficient bars (%d)", STRATEGY_NAME, symbol, len(symbol_bars))
            continue

        closes = [b["c"] for b in symbol_bars]
        volumes = [b["v"] for b in symbol_bars]
        current_close = closes[-1]
        current_vol = volumes[-1]
        if current_close <= 0:
            continue

        upper, middle, lower = _bollinger(closes)
        if upper <= 0 or lower <= 0:
            continue

        avg_vol = sum(volumes[-(BB_PERIOD + 1):-1]) / BB_PERIOD if BB_PERIOD > 0 else 0
        volume_ok = avg_vol > 0 and current_vol >= VOLUME_MULT * avg_vol
        vol_ratio = current_vol / avg_vol if avg_vol > 0 else 0

        band_width = upper - lower
        if band_width <= 0:
            continue

        # Breakout long: close above upper band + volume surge
        if current_close > upper and volume_ok:
            excess = (current_close - upper) / band_width
            raw_conf = min(0.9, 0.58 + excess * 1.5 + (vol_ratio - VOLUME_MULT) * 0.03)
            confidence = min(0.9, raw_conf + conf_bump)
            size_hint = min(1.0, confidence)
            signals.append(Signal(
                symbol=symbol,
                side="buy",
                confidence=confidence,
                size_hint=size_hint,
                reason=(
                    f"BB_BREAKOUT long: close {current_close:.4f} > upper BB {upper:.4f}, "
                    f"vol {vol_ratio:.1f}x avg (need {VOLUME_MULT}x), "
                    f"trail-stop @ mid BB {middle:.4f}, time-stop 6h"
                ),
                strategy=STRATEGY_NAME,
            ))

        # Breakout short: close below lower band + volume surge
        elif current_close < lower and volume_ok:
            excess = (lower - current_close) / band_width
            raw_conf = min(0.9, 0.58 + excess * 1.5 + (vol_ratio - VOLUME_MULT) * 0.03)
            confidence = min(0.9, raw_conf + conf_bump)
            size_hint = min(1.0, confidence)
            signals.append(Signal(
                symbol=symbol,
                side="sell",
                confidence=confidence,
                size_hint=size_hint,
                reason=(
                    f"BB_BREAKOUT short: close {current_close:.4f} < lower BB {lower:.4f}, "
                    f"vol {vol_ratio:.1f}x avg (need {VOLUME_MULT}x), "
                    f"trail-stop @ mid BB {middle:.4f}, time-stop 6h"
                ),
                strategy=STRATEGY_NAME,
            ))

    return signals
