"""
BTC Dominance Regime — crypto_swing position sizing.
NOT a directional signal. Adjusts size_hint for all other crypto signals.
High BTC dominance (>55%): reduce altcoin exposure 50%, increase BTC.
Low BTC dominance (<45%): increase altcoin exposure, reduce BTC 30%.
Mid dominance: neutral.
"""
from __future__ import annotations

import logging

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "crypto_btc_dominance_regime"

DOM_HIGH = 55.0   # above this → risk-off, favor BTC
DOM_LOW = 45.0    # below this → risk-on, favor alts

# BTC symbols — get full allocation when dom is high
BTC_SYMBOLS = {"BTC/USD", "BTC-USD", "BTCUSD"}


def generate_signals(
    bars: dict[str, list[dict]],
    profile_config: dict,
    regime: dict,
) -> list[Signal]:
    """Emit hold signals with size_hint adjusted for BTC dominance regime.

    High dom (>55%): emit buy BTC with size_hint=1.0, alts size_hint=0.5.
    Low dom (<45%): emit buy alts with size_hint=1.5, BTC size_hint=0.7.
    Mid: no adjustment signals (return empty — let other strategies drive).

    Args:
        bars: {symbol: [{t, o, h, l, c, v}, ...]} oldest-first.
        profile_config: Profile YAML dict.
        regime: Regime context dict (must contain btc_dominance).

    Returns:
        List of Signal objects.
    """
    btc_dom = regime.get("btc_dominance", 50.0)
    confidence = abs(btc_dom - 50.0) / 50.0

    universe = profile_config.get("universe", {})
    if isinstance(universe, dict):
        symbols = universe.get("symbols", list(bars.keys()))
    else:
        symbols = list(bars.keys())

    signals: list[Signal] = []

    if btc_dom > DOM_HIGH:
        # High dominance: favor BTC, reduce alts
        for symbol in symbols:
            if symbol in BTC_SYMBOLS:
                # Increase BTC — emit a hold signal with high size_hint
                signals.append(Signal(
                    symbol=symbol,
                    side="buy",
                    confidence=confidence,
                    size_hint=1.0,
                    reason=f"BTC dominance regime: dom={btc_dom:.1f}% > {DOM_HIGH}% — increase BTC",
                    strategy=STRATEGY_NAME,
                ))
            else:
                # Reduce alts
                signals.append(Signal(
                    symbol=symbol,
                    side="hold",
                    confidence=confidence,
                    size_hint=0.5,
                    reason=f"BTC dominance regime: dom={btc_dom:.1f}% > {DOM_HIGH}% — reduce altcoin to 50%",
                    strategy=STRATEGY_NAME,
                ))

    elif btc_dom < DOM_LOW:
        # Low dominance: favor alts, reduce BTC
        for symbol in symbols:
            if symbol in BTC_SYMBOLS:
                signals.append(Signal(
                    symbol=symbol,
                    side="hold",
                    confidence=confidence,
                    size_hint=0.7,
                    reason=f"BTC dominance regime: dom={btc_dom:.1f}% < {DOM_LOW}% — reduce BTC to 70%",
                    strategy=STRATEGY_NAME,
                ))
            else:
                signals.append(Signal(
                    symbol=symbol,
                    side="buy",
                    confidence=confidence,
                    size_hint=min(1.0, 1.5 / len(symbols) * 3) if symbols else 1.0,
                    reason=f"BTC dominance regime: dom={btc_dom:.1f}% < {DOM_LOW}% — increase altcoin exposure",
                    strategy=STRATEGY_NAME,
                ))

    else:
        # Mid range — neutral, no regime override signals
        logger.debug(
            "[%s] BTC dom=%.1f%% in neutral band [%.0f, %.0f] — no regime adjustment",
            STRATEGY_NAME, btc_dom, DOM_LOW, DOM_HIGH,
        )

    return signals
