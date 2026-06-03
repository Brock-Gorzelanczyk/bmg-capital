"""0DTE iron condor: short strangle with wings, regime-gated options strategy."""
from __future__ import annotations
import logging
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "zero_dte_iron_condor"


def _v1_signals(symbol: str, closes: list[float], vix_regime: str = "") -> List[Signal]:
    """Core logic: open 0DTE iron condor in low/mid VIX regimes."""
    if vix_regime == "panic":
        return []
    return [Signal(
        symbol=symbol, side="buy", confidence=0.60,
        size_hint=0.60,
        reason="0DTE iron condor: sell OTM put+call, buy wings, expire same day",
        strategy=STRATEGY_NAME,
    )]


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    vix_regime = regime.get("vix_regime", "")
    if vix_regime == "panic":
        return []
    out: List[Signal] = []
    for symbol, bar_list in bars.items():
        if not bar_list:
            continue
        closes = [float(b.get("c", 0)) for b in bar_list]
        if not closes:
            continue
        out.extend(_v1_signals(symbol, closes, vix_regime))
    return out


def generate_signal(symbol: str, closes: list[float], **kwargs) -> Optional[Signal]:
    """Backwards-compat shim."""
    sigs = _v1_signals(symbol, closes)
    return sigs[0] if sigs else None
