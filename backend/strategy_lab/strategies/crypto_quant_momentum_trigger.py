"""
Crypto Quant Aggressive — S3: Momentum Trigger

Entry (long):  15m close > prior 4h high AND volume > 2.0x avg → long
Entry (short): 15m close < prior 4h low  AND volume > 2.0x avg → short
Exit: trailing 2% stop; time-stop 8h.

Bars: 15m (profile scan_timeframe=15m).
Prior 4h high/low = highest high / lowest low across the preceding 16 bars (4h ÷ 15m).
"""
from __future__ import annotations

import logging

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "crypto_quant_momentum_trigger"

UNIVERSE = [
    "BTC/USD", "ETH/USD", "SOL/USD", "BNB/USD", "XRP/USD", "ADA/USD",
    "AVAX/USD", "POL/USD", "DOT/USD", "LINK/USD", "ATOM/USD", "NEAR/USD",
    "ARB/USD", "OP/USD", "INJ/USD", "SUI/USD", "APT/USD", "TIA/USD",
    "DOGE/USD", "SHIB/USD",
]

LOOKBACK_BARS_4H = 16      # 16 x 15m = 4h
VOLUME_MULT = 1.3          # lowered from 2.0 — 2x was too strict for regular crypto markets
TRAILING_STOP_PCT = 2.0    # 2% trailing stop


def generate_signals(
    bars: dict[str, list[dict]],
    profile_config: dict,
    regime: dict,
) -> list[Signal]:
    """Generate momentum trigger signals.

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
        # Need at least LOOKBACK_BARS_4H + 1 bars (the lookback window + current bar)
        if len(symbol_bars) < LOOKBACK_BARS_4H + 2:
            logger.debug("[%s] %s: insufficient bars (%d)", STRATEGY_NAME, symbol, len(symbol_bars))
            continue

        closes = [b["c"] for b in symbol_bars]
        highs = [b["h"] for b in symbol_bars]
        lows = [b["l"] for b in symbol_bars]
        volumes = [b["v"] for b in symbol_bars]

        current_close = closes[-1]
        if current_close <= 0:
            continue

        # Prior 4h window: bars[-LOOKBACK_BARS_4H-1 : -1] (excludes current bar)
        prior_window_highs = highs[-(LOOKBACK_BARS_4H + 1):-1]
        prior_window_lows = lows[-(LOOKBACK_BARS_4H + 1):-1]
        if not prior_window_highs:
            continue

        prior_4h_high = max(prior_window_highs)
        prior_4h_low = min(prior_window_lows)

        # Volume: current vs average of prior 20 bars
        vol_period = min(20, len(volumes) - 1)
        avg_vol = sum(volumes[-(vol_period + 1):-1]) / vol_period if vol_period > 0 else 0
        current_vol = volumes[-1]
        volume_ok = avg_vol > 0 and current_vol >= VOLUME_MULT * avg_vol
        vol_ratio = current_vol / avg_vol if avg_vol > 0 else 0

        if not volume_ok:
            continue

        # Momentum long: close breaks above prior 4h high
        if current_close > prior_4h_high:
            breakout_pct = (current_close - prior_4h_high) / prior_4h_high
            raw_conf = min(0.9, 0.60 + breakout_pct * 10 + (vol_ratio - VOLUME_MULT) * 0.02)
            confidence = min(0.9, raw_conf + conf_bump)
            size_hint = min(1.0, confidence)
            signals.append(Signal(
                symbol=symbol,
                side="buy",
                confidence=confidence,
                size_hint=size_hint,
                reason=(
                    f"MOMENTUM_TRIGGER long: close {current_close:.4f} > 4h high {prior_4h_high:.4f} "
                    f"(+{breakout_pct * 100:.2f}%), vol {vol_ratio:.1f}x avg, "
                    f"trail-stop {TRAILING_STOP_PCT}%, time-stop 8h"
                ),
                strategy=STRATEGY_NAME,
            ))

        # Momentum short: close breaks below prior 4h low
        elif current_close < prior_4h_low:
            breakdown_pct = (prior_4h_low - current_close) / prior_4h_low
            raw_conf = min(0.9, 0.60 + breakdown_pct * 10 + (vol_ratio - VOLUME_MULT) * 0.02)
            confidence = min(0.9, raw_conf + conf_bump)
            size_hint = min(1.0, confidence)
            signals.append(Signal(
                symbol=symbol,
                side="sell",
                confidence=confidence,
                size_hint=size_hint,
                reason=(
                    f"MOMENTUM_TRIGGER short: close {current_close:.4f} < 4h low {prior_4h_low:.4f} "
                    f"(-{breakdown_pct * 100:.2f}%), vol {vol_ratio:.1f}x avg, "
                    f"trail-stop {TRAILING_STOP_PCT}%, time-stop 8h"
                ),
                strategy=STRATEGY_NAME,
            ))

    return signals
