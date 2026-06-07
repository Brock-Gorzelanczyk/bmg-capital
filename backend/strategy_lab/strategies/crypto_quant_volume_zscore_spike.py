"""
Crypto Quant Aggressive — S5: Volume Z-Score Spike

Entry: 15m volume z-score > 3.0 vs 24h rolling (96 bars at 15m) → with the price direction
  - If the volume-spike bar is bullish (close > open) → long
  - If the volume-spike bar is bearish (close < open) → short
Exit: tight 1.5% stop; time-stop 2h.

Bars: 15m (profile scan_timeframe=15m).
Z-score computed over last 96 bars (24h ÷ 15m).
"""
from __future__ import annotations

import logging
import math

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "crypto_quant_volume_zscore_spike"

UNIVERSE = [
    "BTC/USD", "ETH/USD", "SOL/USD", "BNB/USD", "XRP/USD", "ADA/USD",
    "AVAX/USD", "POL/USD", "DOT/USD", "LINK/USD", "ATOM/USD", "NEAR/USD",
    "ARB/USD", "OP/USD", "INJ/USD", "SUI/USD", "APT/USD", "TIA/USD",
    "DOGE/USD", "SHIB/USD",
]

ZSCORE_PERIOD = 96    # 24h of 15m bars
ZSCORE_THRESHOLD = 3.0
STOP_PCT = 1.5
HOLD_HOURS = 2


def _volume_zscore(volumes: list[float], period: int = ZSCORE_PERIOD) -> float:
    """Compute z-score of current (last) volume vs rolling window."""
    if len(volumes) < period + 1:
        return 0.0
    window = volumes[-(period + 1):-1]   # prior `period` bars, exclude current
    if not window:
        return 0.0
    mean = sum(window) / len(window)
    variance = sum((v - mean) ** 2 for v in window) / len(window)
    std = math.sqrt(variance)
    if std <= 0:
        return 0.0
    return (volumes[-1] - mean) / std


def generate_signals(
    bars: dict[str, list[dict]],
    profile_config: dict,
    regime: dict,
) -> list[Signal]:
    """Generate volume z-score spike signals.

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
        if len(symbol_bars) < ZSCORE_PERIOD + 2:
            logger.debug("[%s] %s: insufficient bars (%d)", STRATEGY_NAME, symbol, len(symbol_bars))
            continue

        volumes = [b["v"] for b in symbol_bars]
        opens = [b["o"] for b in symbol_bars]
        closes = [b["c"] for b in symbol_bars]

        current_close = closes[-1]
        current_open = opens[-1]
        if current_close <= 0:
            continue

        zscore = _volume_zscore(volumes)
        if zscore < ZSCORE_THRESHOLD:
            continue

        current_vol = volumes[-1]
        avg_vol = sum(volumes[-(ZSCORE_PERIOD + 1):-1]) / ZSCORE_PERIOD

        # Bar direction determines signal side
        bar_bullish = current_close > current_open
        bar_move_pct = abs(current_close - current_open) / current_open if current_open > 0 else 0

        # Confidence: scales with z-score magnitude and bar body size
        raw_conf = min(0.9, 0.55 + (zscore - ZSCORE_THRESHOLD) * 0.04 + bar_move_pct * 2)
        confidence = min(0.9, raw_conf + conf_bump)
        size_hint = min(1.0, confidence)

        side = "buy" if bar_bullish else "sell"
        direction_str = "bullish" if bar_bullish else "bearish"

        signals.append(Signal(
            symbol=symbol,
            side=side,
            confidence=confidence,
            size_hint=size_hint,
            reason=(
                f"VOLUME_ZSCORE_SPIKE {direction_str}: vol z-score={zscore:.2f} > {ZSCORE_THRESHOLD} "
                f"(current {current_vol:.0f} vs avg {avg_vol:.0f}), "
                f"bar {'up' if bar_bullish else 'down'} {bar_move_pct * 100:.2f}%, "
                f"tight {STOP_PCT}% stop, time-stop {HOLD_HOURS}h"
            ),
            strategy=STRATEGY_NAME,
        ))

    return signals
