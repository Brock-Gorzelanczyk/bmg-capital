"""Cross-sectional momentum — Jegadeesh & Titman (1993).

Ranks universe by 12-1M return (skip the most recent month to avoid
short-term reversal), buys top quintile, sells bottom quintile.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "cross_sectional_momentum"

# Formation window: 12 months of daily bars ≈ 252 bars; skip last 21
_FORM_BARS = 252
_SKIP_BARS = 21
_TOP_PCTILE = 0.20   # buy top 20 %
_BOT_PCTILE = 0.20   # sell bottom 20 %


def _momentum_return(closes: list[float]) -> float | None:
    """Return (12-1)M momentum: return from bar -252 to bar -21."""
    if len(closes) < _FORM_BARS:
        return None
    p_start = closes[-(
        _FORM_BARS)]
    p_end = closes[-(_SKIP_BARS)]
    if p_start <= 0:
        return None
    return (p_end - p_start) / p_start


def generate_signals(
    bars: dict,
    profile_config: dict,
    regime: dict,
) -> List[Signal]:
    # No new longs in a panic regime
    if regime.get("vix_regime") == "panic":
        return []

    scores: dict[str, float] = {}
    for symbol, bar_list in bars.items():
        if not bar_list:
            continue
        closes = [float(b.get("c", 0)) for b in bar_list]
        mom = _momentum_return(closes)
        if mom is not None:
            scores[symbol] = mom

    if len(scores) < 5:
        return []

    sorted_syms = sorted(scores, key=lambda s: scores[s])
    n = len(sorted_syms)
    n_bucket = max(1, int(n * _TOP_PCTILE))

    winners = sorted_syms[-n_bucket:]
    losers = sorted_syms[:n_bucket]

    out: List[Signal] = []
    for sym in winners:
        out.append(Signal(
            symbol=sym,
            side="buy",
            confidence=min(0.85, 0.50 + scores[sym] * 0.5),
            size_hint=0.60,
            reason=f"CSM top quintile: 12-1M mom={scores[sym]:.3f}",
            strategy=STRATEGY_NAME,
        ))
    for sym in losers:
        out.append(Signal(
            symbol=sym,
            side="sell",
            confidence=min(0.80, 0.50 + abs(scores[sym]) * 0.5),
            size_hint=0.40,
            reason=f"CSM bottom quintile: 12-1M mom={scores[sym]:.3f}",
            strategy=STRATEGY_NAME,
        ))
    return out


def generate_signal(
    symbol: str,
    closes: list[float],
    **kwargs,
) -> Optional[Signal]:
    """Backwards-compat shim — evaluates symbol in isolation (no ranking)."""
    mom = _momentum_return(closes)
    if mom is None:
        return None
    if mom > 0.05:
        return Signal(
            symbol=symbol,
            side="buy",
            confidence=min(0.80, 0.50 + mom * 0.5),
            size_hint=0.60,
            reason=f"CSM positive 12-1M momentum: {mom:.3f}",
            strategy=STRATEGY_NAME,
        )
    if mom < -0.05:
        return Signal(
            symbol=symbol,
            side="sell",
            confidence=min(0.75, 0.50 + abs(mom) * 0.5),
            size_hint=0.40,
            reason=f"CSM negative 12-1M momentum: {mom:.3f}",
            strategy=STRATEGY_NAME,
        )
    return None
