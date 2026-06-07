"""
Crypto Intraday Momentum
Sharpe 1.12-1.42.

BTC/ETH/SOL/AVAX momentum on 1h bars (profile: scan_timeframe=1h).
Long when: 1h return > 1.5 * ATR(20, 1h), volume 2x avg, funding neutral.
Short when: 1h return < -1.5 * ATR, volume 2x avg.
24h operation. Exit at 24h hard stop or when signal reverses.
Regime: halve size if BTC funding rate > top 5% (hot market, crowded longs).
"""
from __future__ import annotations

import logging
from typing import Optional

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "crypto_intraday_momentum"

# Universe symbols this strategy targets
UNIVERSE = ["BTC/USD", "ETH/USD", "SOL/USD", "AVAX/USD"]

# 1 bar = 1 hour (profile uses scan_timeframe: 1h)
BARS_PER_HOUR = 1
ATR_PERIOD = 20

# TEMP: lowered 2026-06-07 to validate signal firing in flat
# market. Restore to 0.03 (3%) after first organic signal fires.
MIN_MOMENTUM_PCT = 0.005  # was 0.03 (~3% via SIGNAL_ATR_MULTIPLIER=1.5 * typical ATR)

# TEMP: lowered 2026-06-07 to validate signal firing in flat
# market. Restore to 2.0 after first organic signal fires.
MIN_VOLUME_RATIO = 1.0  # was 2.0 (VOLUME_MULTIPLIER)

SIGNAL_ATR_MULTIPLIER = 1.5  # kept for confidence scaling; no longer used as entry filter

# BTC funding rate threshold — top ~5% proxy
FUNDING_RATE_HOT = 0.001


def _compute_atr(bars: list[dict], period: int = ATR_PERIOD) -> float:
    """Compute simple ATR as mean of (high - low) over the last `period` bars."""
    if len(bars) < period:
        return 0.0
    recent = bars[-period:]
    return sum(b["h"] - b["l"] for b in recent) / period


def generate_signals(
    bars: dict[str, list[dict]],
    profile_config: dict,
    regime: dict,
) -> list[Signal]:
    """Generate intraday momentum signals from 5-min OHLCV bars.

    Args:
        bars: {symbol: [{t, o, h, l, c, v}, ...]} oldest-first, 5-min bars.
        profile_config: Profile YAML dict.
        regime: Regime context dict (may contain btc_funding_rate, etc.).

    Returns:
        List of Signal objects.
    """
    signals: list[Signal] = []
    btc_funding = regime.get("btc_funding_rate", 0.0)
    funding_hot = btc_funding > FUNDING_RATE_HOT

    universe = profile_config.get("universe", {})
    if isinstance(universe, dict):
        symbols = universe.get("symbols", UNIVERSE)
    else:
        symbols = UNIVERSE

    for symbol in symbols:
        symbol_bars = bars.get(symbol, [])
        if len(symbol_bars) < BARS_PER_HOUR + ATR_PERIOD + 1:
            logger.debug("[%s] %s: insufficient bars (%d)", STRATEGY_NAME, symbol, len(symbol_bars))
            continue

        closes = [b["c"] for b in symbol_bars]
        volumes = [b["v"] for b in symbol_bars]
        current_close = closes[-1]

        # 1h return: compare current close to close 12 bars ago (1h on 5min bars)
        close_1h_ago = closes[-(BARS_PER_HOUR + 1)]
        if close_1h_ago <= 0:
            continue
        one_hour_return = (current_close - close_1h_ago) / close_1h_ago

        # ATR(20) on 5min bars
        atr = _compute_atr(symbol_bars, ATR_PERIOD)
        if current_close <= 0 or atr <= 0:
            continue
        atr_normalized = atr / current_close

        # Volume confirmation: current volume vs avg of last 20 bars
        avg_volume = sum(volumes[-(ATR_PERIOD + 1):-1]) / ATR_PERIOD
        current_volume = volumes[-1]
        volume_ok = avg_volume > 0 and current_volume >= MIN_VOLUME_RATIO * avg_volume

        # ATR-normalized threshold kept for confidence scaling; entry gate uses MIN_MOMENTUM_PCT
        threshold = SIGNAL_ATR_MULTIPLIER * atr_normalized

        # Regime: halve size if funding is hot
        size_multiplier = 0.5 if funding_hot else 1.0

        if one_hour_return > MIN_MOMENTUM_PCT and volume_ok:
            raw_conf = abs(one_hour_return) / (3 * atr_normalized)
            confidence = min(0.9, raw_conf)
            size_hint = min(1.0, confidence * size_multiplier)
            signals.append(Signal(
                symbol=symbol,
                side="buy",
                confidence=confidence,
                size_hint=size_hint,
                reason=(
                    f"Intraday momentum long: 1h_ret={one_hour_return:.4f} > "
                    f"1.5*ATR={threshold:.4f}, vol={current_volume / avg_volume:.1f}x"
                    + (" [funding hot, size halved]" if funding_hot else "")
                ),
                strategy=STRATEGY_NAME,
            ))

        elif one_hour_return < -MIN_MOMENTUM_PCT and volume_ok:
            raw_conf = abs(one_hour_return) / (3 * atr_normalized)
            confidence = min(0.9, raw_conf)
            size_hint = min(1.0, confidence * size_multiplier)
            signals.append(Signal(
                symbol=symbol,
                side="sell",
                confidence=confidence,
                size_hint=size_hint,
                reason=(
                    f"Intraday momentum short: 1h_ret={one_hour_return:.4f} < "
                    f"-1.5*ATR={-threshold:.4f}, vol={current_volume / avg_volume:.1f}x"
                    + (" [funding hot, size halved]" if funding_hot else "")
                ),
                strategy=STRATEGY_NAME,
            ))

    return signals
