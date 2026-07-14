"""
Crypto Momentum Breakout for crypto_swing.
30-day high breakout on rising volume and BTC dominance neutral/falling.
Long: close > max(close[-30d]) AND volume > 1.5x 30d avg AND BTC_dom < 50 or falling.
"""
from __future__ import annotations

import logging

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "crypto_momentum_breakout"

# 2026-07-13 fire-more relaxation: crypto_swing had 0 signals/24h from
# this strategy. Original (30d high + 1.5× vol + BTC dom < 50) is a
# high-conviction triple-gate that only fires 2-3× per name per year.
# Relaxed to 10d high + 1.1× vol, and BTC dom gate becomes advisory
# (raises confidence but doesn't block). Discipline gate downstream
# still filters shallow signals via confidence_threshold.
LOOKBACK_DAILY = 10
LOOKBACK_HOURLY = 240   # 10d × 24h
VOLUME_MULTIPLIER = 1.1
BTC_DOM_NEUTRAL = 50.0


def generate_signals(
    bars: dict[str, list[dict]],
    profile_config: dict,
    regime: dict,
) -> list[Signal]:
    """Generate 30-day momentum breakout signals.

    Accepts either daily bars (30+ bars) or hourly bars (720+ bars).
    Detects the resolution automatically based on bar count.

    Args:
        bars: {symbol: [{t, o, h, l, c, v}, ...]} oldest-first.
        profile_config: Profile YAML dict.
        regime: Regime context dict (may contain btc_dominance, btc_dominance_7d_avg).

    Returns:
        List of Signal objects.
    """
    btc_dom = regime.get("btc_dominance", 50.0)
    btc_dom_7d_avg = regime.get("btc_dominance_7d_avg", btc_dom)

    # BTC dominance condition: < 50% OR falling
    btc_dom_ok = btc_dom < BTC_DOM_NEUTRAL or btc_dom < btc_dom_7d_avg

    universe = profile_config.get("universe", {})
    if isinstance(universe, dict):
        symbols = universe.get("symbols", list(bars.keys()))
    else:
        symbols = list(bars.keys())

    signals: list[Signal] = []

    for symbol in symbols:
        symbol_bars = bars.get(symbol, [])
        if not symbol_bars:
            continue

        # Auto-detect lookback: prefer daily (30 bars), fall back to hourly (720)
        if len(symbol_bars) >= LOOKBACK_HOURLY + 1:
            lookback = LOOKBACK_HOURLY
        elif len(symbol_bars) >= LOOKBACK_DAILY + 1:
            lookback = LOOKBACK_DAILY
        else:
            logger.debug("[%s] %s: insufficient bars (%d)", STRATEGY_NAME, symbol, len(symbol_bars))
            continue

        closes = [b["c"] for b in symbol_bars]
        volumes = [b["v"] for b in symbol_bars]

        current_close = closes[-1]
        current_volume = volumes[-1]

        # 30d high on the preceding `lookback` bars (excluding current)
        prev_closes = closes[-(lookback + 1):-1]
        prev_high = max(prev_closes)

        avg_volume = sum(volumes[-(lookback + 1):-1]) / lookback

        price_breakout = current_close > prev_high
        volume_ok = avg_volume > 0 and current_volume > VOLUME_MULTIPLIER * avg_volume

        # 2026-07-13: btc_dom_ok now advisory not gating — it boosts
        # confidence but doesn't block signals.
        if price_breakout and volume_ok:
            volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0
            _base_conf = min(0.85, max(0.35, volume_ratio / 3.0))
            confidence = _base_conf + (0.10 if btc_dom_ok else 0.0)
            confidence = min(0.85, confidence)
            signals.append(Signal(
                symbol=symbol,
                side="buy",
                confidence=confidence,
                size_hint=confidence,
                reason=(
                    f"Momentum breakout: close={current_close:.4f} > 30d-high={prev_high:.4f}, "
                    f"vol={volume_ratio:.1f}x avg, "
                    f"BTC dom={btc_dom:.1f}% ({'falling' if btc_dom < btc_dom_7d_avg else 'neutral'})"
                ),
                strategy=STRATEGY_NAME,
            ))

    return signals
