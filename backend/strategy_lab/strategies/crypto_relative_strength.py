"""Crypto Relative Strength strategy — rank alts by 14-day RS vs BTC."""
from __future__ import annotations

import logging
from typing import List, Optional

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "crypto_relative_strength"
# 2026-07-13: 1.05 (5% outperformance in 14d) was too strict — crypto_swing
# saw 0 signals in 24h with the whole strategy roster. Relaxed to 1.02 (2%
# outperformance), which is a realistic RS-leader threshold. Composite gate
# downstream keeps the noise out.
RS_THRESHOLD = 1.02  # alt must outperform BTC by 2% over 14d


def _v1_signals(
    symbol: str,
    closes: list[float],
    btc_closes: list[float],
) -> List[Signal]:
    """Return buy when alt shows RS > 1.05 vs BTC over 14 days.

    Args:
        symbol: Ticker/pair symbol.
        closes: Alt close prices, most-recent last. Requires len >= 14.
        btc_closes: BTC close prices, most-recent last. Requires len >= 14.
    """
    if len(closes) < 14 or len(btc_closes) < 14:
        return []

    if closes[-14] == 0 or btc_closes[-14] == 0:
        return []

    alt_return = closes[-1] / closes[-14]
    btc_return = btc_closes[-1] / btc_closes[-14]

    rs_vs_btc = alt_return / btc_return if btc_return != 0 else 0.0

    if rs_vs_btc > RS_THRESHOLD:
        confidence = max(0.4, min(0.85, (rs_vs_btc - 1.0) * 8 + 0.4))
        return [Signal(
            symbol=symbol,
            side="buy",
            confidence=confidence,
            size_hint=confidence,
            reason=(
                f"Crypto RS leader: RS vs BTC = {rs_vs_btc:.3f} "
                f"(alt +{(alt_return-1)*100:.1f}% vs BTC +{(btc_return-1)*100:.1f}% over 14d)"
            ),
            strategy=STRATEGY_NAME,
        )]

    return []


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    """New-style interface called by runner.py."""
    out: List[Signal] = []

    # Find BTC closes
    btc_closes: list[float] = []
    for key in ("BTC/USD", "BTCUSD", "BTC-USD", "XBTUSD"):
        if key in bars and bars[key]:
            btc_closes = [float(b.get("c", 0)) for b in bars[key]]
            break

    if not btc_closes:
        return []

    for symbol, bar_list in bars.items():
        if not bar_list:
            continue
        if symbol in ("BTC/USD", "BTCUSD", "BTC-USD", "XBTUSD"):
            continue
        closes = [float(b.get("c", 0)) for b in bar_list]
        out.extend(_v1_signals(symbol, closes, btc_closes))
    return out


def generate_signal(
    symbol: str,
    closes: list[float],
    btc_closes: list[float],
) -> Optional[Signal]:
    """Backwards-compat shim."""
    signals = _v1_signals(symbol, closes, btc_closes)
    return signals[0] if signals else None
