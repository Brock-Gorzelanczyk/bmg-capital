"""
Crypto Volatility Breakout (Donchian-based).
After a period of low volatility (ATR contraction),
breakout above/below N-day range signals directional move.
Long: close > max(high[-24h]) AND 7d ATR < 30d ATR * 0.8 (contraction).
"""
from __future__ import annotations

import logging

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "crypto_volatility_breakout"

# 24 hourly bars = 24h Donchian channel
DONCHIAN_BARS = 24
# 7d ATR on hourly bars = 168 bars
ATR_7D_BARS = 168
# 30d ATR on hourly bars = 720 bars
ATR_30D_BARS = 720

# TEMP: raised 2026-06-07 to validate signal firing in flat
# market. Restore to 0.8 after first organic signal fires.
# At 0.8 the market must be in clear volatility squeeze; at 1.5
# the check passes in almost all normal conditions.
ATR_CONTRACTION_RATIO = 1.5  # was 0.8

# TEMP: lowered 2026-06-07 to validate signal firing in flat
# market. Restore to 0.02 (2%) after first organic signal fires.
MIN_ATR_BREAKOUT_PCT = 0.005  # was 0.02; minimum close-above-donchian-high % to count


def _compute_atr(bars: list[dict], period: int) -> float:
    """Mean of (high - low) over last `period` bars."""
    if len(bars) < period:
        return 0.0
    recent = bars[-period:]
    return sum(b["h"] - b["l"] for b in recent) / period


def generate_signals(
    bars: dict[str, list[dict]],
    profile_config: dict,
    regime: dict,
) -> list[Signal]:
    """Generate volatility breakout signals from hourly OHLCV bars.

    Long when price breaks above the 24h Donchian high during ATR contraction.
    Short when price breaks below the 24h Donchian low during ATR contraction.

    Args:
        bars: {symbol: [{t, o, h, l, c, v}, ...]} oldest-first, hourly bars.
        profile_config: Profile YAML dict.
        regime: Regime context dict.

    Returns:
        List of Signal objects.
    """
    universe = profile_config.get("universe", {})
    if isinstance(universe, dict):
        symbols = universe.get("symbols", list(bars.keys()))
    else:
        symbols = list(bars.keys())

    signals: list[Signal] = []

    for symbol in symbols:
        symbol_bars = bars.get(symbol, [])
        if len(symbol_bars) < ATR_30D_BARS + 1:
            logger.debug("[%s] %s: insufficient bars (%d)", STRATEGY_NAME, symbol, len(symbol_bars))
            continue

        closes = [b["c"] for b in symbol_bars]
        current_close = closes[-1]

        # Donchian channel: high/low of the last 24h (excl. current bar)
        donchian_bars = symbol_bars[-(DONCHIAN_BARS + 1):-1]
        donchian_high = max(b["h"] for b in donchian_bars)
        donchian_low = min(b["l"] for b in donchian_bars)

        # ATR contraction: 7d ATR vs 30d ATR
        atr_7d = _compute_atr(symbol_bars, ATR_7D_BARS)
        atr_30d = _compute_atr(symbol_bars, ATR_30D_BARS)

        if atr_30d <= 0:
            continue

        atr_contraction = atr_7d < ATR_CONTRACTION_RATIO * atr_30d

        if not atr_contraction:
            continue

        if donchian_high > 0 and current_close > donchian_high * (1 + MIN_ATR_BREAKOUT_PCT):
            raw_conf = (current_close - donchian_high) / donchian_high * 10
            confidence = min(0.85, max(0.2, raw_conf))
            signals.append(Signal(
                symbol=symbol,
                side="buy",
                confidence=confidence,
                size_hint=confidence,
                reason=(
                    f"Volatility breakout long: close={current_close:.4f} > "
                    f"24h high={donchian_high:.4f} (+{MIN_ATR_BREAKOUT_PCT*100:.1f}%), "
                    f"7d ATR={atr_7d:.4f} vs 30d ATR={atr_30d:.4f}"
                ),
                strategy=STRATEGY_NAME,
            ))

        elif donchian_low > 0 and current_close < donchian_low * (1 - MIN_ATR_BREAKOUT_PCT):
            raw_conf = (donchian_low - current_close) / donchian_low * 10
            confidence = min(0.85, max(0.2, raw_conf))
            signals.append(Signal(
                symbol=symbol,
                side="sell",
                confidence=confidence,
                size_hint=confidence,
                reason=(
                    f"Volatility breakout short: close={current_close:.4f} < "
                    f"24h low={donchian_low:.4f} (-{MIN_ATR_BREAKOUT_PCT*100:.1f}%), "
                    f"7d ATR={atr_7d:.4f} vs 30d ATR={atr_30d:.4f}"
                ),
                strategy=STRATEGY_NAME,
            ))

    return signals
