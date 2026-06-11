"""Crypto dual momentum — Liu & Tsyvinski (2021) + Antonacci (2014).

Combines absolute momentum (is the asset trending up vs. cash?) with
relative momentum (which crypto is trending strongest?).  Only takes
long positions — no shorting crypto in this candidate.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "crypto_dual_momentum"

_LOOKBACK = 90    # ~3 months
_ABS_HURDLE = 0.0  # absolute return must beat cash (0 %)
_TOP_N = 3         # hold top-N assets by momentum


def _trailing_return(closes: list[float], lookback: int) -> float | None:
    if len(closes) < lookback:
        return None
    p0 = closes[-lookback]
    if p0 <= 0:
        return None
    return (closes[-1] - p0) / p0


def generate_signals(
    bars: dict,
    profile_config: dict,
    regime: dict,
) -> List[Signal]:
    vix = regime.get("vix_regime", "mid")
    btc_dom = float(regime.get("btc_dominance", 50.0))

    # When BTC dominance is spiking (>65 %) the entire alt market weakens
    dom_penalty = 0.80 if btc_dom > 65 else 1.0

    # No new positions in panic
    if vix == "panic":
        return []

    scores: dict[str, float] = {}
    for symbol, bar_list in bars.items():
        if not bar_list:
            continue
        # Only process crypto pairs
        if "/" not in symbol:
            continue
        closes = [float(b.get("c", 0)) for b in bar_list]
        ret = _trailing_return(closes, _LOOKBACK)
        if ret is not None:
            scores[symbol] = ret

    if not scores:
        return []

    # Absolute momentum gate: only trade assets with positive return
    abs_pass = {s: r for s, r in scores.items() if r > _ABS_HURDLE}
    if not abs_pass:
        return []

    # Relative momentum: pick top-N
    top = sorted(abs_pass, key=lambda s: abs_pass[s], reverse=True)[:_TOP_N]

    out: List[Signal] = []
    for sym in top:
        ret = scores[sym]
        conf = min(0.88, 0.55 + ret * 0.3)
        out.append(Signal(
            symbol=sym,
            side="buy",
            confidence=round(conf * dom_penalty, 4),
            size_hint=round(0.70 / len(top), 4),
            reason=f"Crypto dual-mom: 3M ret={ret:.3f} btc_dom={btc_dom:.1f}",
            strategy=STRATEGY_NAME,
        ))
    return out


def generate_signal(
    symbol: str,
    closes: list[float],
    **kwargs,
) -> Optional[Signal]:
    """Backwards-compat shim."""
    if "/" not in symbol:
        return None
    ret = _trailing_return(closes, _LOOKBACK)
    if ret is None or ret <= _ABS_HURDLE:
        return None
    conf = min(0.85, 0.55 + ret * 0.3)
    return Signal(
        symbol=symbol,
        side="buy",
        confidence=conf,
        size_hint=0.60,
        reason=f"Crypto dual-mom: 3M ret={ret:.3f}",
        strategy=STRATEGY_NAME,
    )
