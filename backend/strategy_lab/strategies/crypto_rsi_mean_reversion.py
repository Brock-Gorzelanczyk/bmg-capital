"""
Crypto RSI Mean Reversion for crypto_swing.
Crypto RSI reverts faster than equities due to 24/7 trading.
Long: RSI(14, 4h) < 30 AND BTC dominance stable (not outflow risk).
Short: RSI(14, 4h) > 70.
Hold 1-7 days.
"""
from __future__ import annotations

import logging

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "crypto_rsi_mean_reversion"

RSI_PERIOD = 14
OVERSOLD = 30.0
OVERBOUGHT = 70.0

# BTC dominance change threshold — if change > 2%, risk of altcoin outflow
BTC_DOM_CHANGE_LIMIT = 2.0


def _compute_rsi(closes: list[float], period: int = RSI_PERIOD) -> float:
    """Compute RSI using Wilder's smoothed averages."""
    if len(closes) < period + 1:
        return 50.0  # neutral fallback

    gains, losses = [], []
    for i in range(-period, 0):
        delta = closes[i] - closes[i - 1]
        if delta >= 0:
            gains.append(delta)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(delta))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def generate_signals(
    bars: dict[str, list[dict]],
    profile_config: dict,
    regime: dict,
) -> list[Signal]:
    """Generate RSI mean reversion signals from 4h OHLCV bars.

    Args:
        bars: {symbol: [{t, o, h, l, c, v}, ...]} oldest-first, 4h bars.
        profile_config: Profile YAML dict.
        regime: Regime context dict (may contain btc_dominance, btc_dominance_7d_avg).

    Returns:
        List of Signal objects.
    """
    # BTC dominance stability check
    btc_dom = regime.get("btc_dominance", 50.0)
    btc_dom_7d_avg = regime.get("btc_dominance_7d_avg", btc_dom)
    btc_dom_change = abs(btc_dom - btc_dom_7d_avg)
    btc_stable = btc_dom_change < BTC_DOM_CHANGE_LIMIT

    universe = profile_config.get("universe", {})
    if isinstance(universe, dict):
        symbols = universe.get("symbols", list(bars.keys()))
    else:
        symbols = list(bars.keys())

    signals: list[Signal] = []

    for symbol in symbols:
        symbol_bars = bars.get(symbol, [])
        if len(symbol_bars) < RSI_PERIOD + 1:
            logger.debug("[%s] %s: insufficient bars (%d)", STRATEGY_NAME, symbol, len(symbol_bars))
            continue

        closes = [b["c"] for b in symbol_bars]
        rsi = _compute_rsi(closes, RSI_PERIOD)

        if rsi < OVERSOLD and btc_stable:
            raw_conf = (OVERSOLD - rsi) / OVERSOLD
            confidence = max(0.3, min(0.9, raw_conf))
            signals.append(Signal(
                symbol=symbol,
                side="buy",
                confidence=confidence,
                size_hint=confidence,
                reason=(
                    f"RSI mean reversion long: RSI(14,4h)={rsi:.1f} < {OVERSOLD}, "
                    f"BTC dom change={btc_dom_change:.2f}% (stable)"
                ),
                strategy=STRATEGY_NAME,
            ))

        elif rsi > OVERBOUGHT:
            raw_conf = (rsi - OVERBOUGHT) / OVERBOUGHT
            confidence = max(0.3, min(0.9, raw_conf))
            signals.append(Signal(
                symbol=symbol,
                side="sell",
                confidence=confidence,
                size_hint=confidence,
                reason=(
                    f"RSI mean reversion short: RSI(14,4h)={rsi:.1f} > {OVERBOUGHT}"
                    + (
                        f" [BTC dom unstable: {btc_dom_change:.2f}% change]"
                        if not btc_stable else ""
                    )
                ),
                strategy=STRATEGY_NAME,
            ))

    return signals
