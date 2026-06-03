"""Cross-sectional momentum: rank symbols by 12-1 month return, long top 20%."""
from __future__ import annotations
import logging
from statistics import mean, stdev
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "cross_sectional_momentum_12_1"


def _v1_signals(symbol: str, closes: list[float]) -> List[Signal]:
    """Core logic: 12-1 month return, buy if >8%."""
    if len(closes) < 252:
        return []
    ret = (closes[-21] - closes[-252]) / closes[-252]
    if ret > 0.08:
        return [Signal(
            symbol=symbol, side="buy", confidence=0.65,
            size_hint=0.65, reason=f"12-1m return {ret:.2%} > 8% threshold",
            strategy=STRATEGY_NAME,
        )]
    return []


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    symbol_returns: list[tuple[str, float, list[float]]] = []
    for symbol, bar_list in bars.items():
        if not bar_list:
            continue
        closes = [float(b.get("c", 0)) for b in bar_list]
        if len(closes) < 252:
            continue
        ret = (closes[-21] - closes[-252]) / closes[-252]
        symbol_returns.append((symbol, ret, closes))

    if not symbol_returns:
        return []

    sorted_syms = sorted(symbol_returns, key=lambda x: x[1])
    n = len(sorted_syms)
    out: List[Signal] = []
    for rank, (symbol, ret, closes) in enumerate(sorted_syms):
        rank_pct = rank / n if n > 1 else 0
        if rank_pct >= 0.80:
            conf = min(0.90, 0.5 + rank_pct * 0.4)
            out.append(Signal(
                symbol=symbol, side="buy", confidence=conf,
                size_hint=conf, reason=f"Top 20% cross-sectional momentum, 12-1m={ret:.2%}",
                strategy=STRATEGY_NAME,
            ))
        else:
            out.extend(_v1_signals(symbol, closes))
    return out


def generate_signal(symbol: str, closes: list[float], **kwargs) -> Optional[Signal]:
    """Backwards-compat shim."""
    sigs = _v1_signals(symbol, closes)
    return sigs[0] if sigs else None
