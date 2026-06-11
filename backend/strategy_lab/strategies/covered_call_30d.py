"""Covered call (30d): sell OTM call against long stock when range-bound."""
from __future__ import annotations
import logging
from statistics import mean
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "covered_call_30d"


def _v1_signals(symbol: str, closes: list[float]) -> List[Signal]:
    """Core logic: range-bound last week = favorable for covered call income."""
    if len(closes) < 5:
        return []
    returns_5d = [(closes[i] - closes[i - 1]) / closes[i - 1]
                  for i in range(-5, 0) if closes[i - 1] > 0]
    avg_5d = mean(returns_5d) if returns_5d else 0
    if -0.01 <= avg_5d <= 0.015:
        return [Signal(
            symbol=symbol, side="buy", confidence=0.65,
            size_hint=0.65,
            reason="Covered call: sell 30d 5-7% OTM call for income, stock range-bound",
            strategy=STRATEGY_NAME,
        )]
    return []


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    if regime.get("vix_regime") == "panic":
        return []

    # IVR gate — only sell premium when IV rank is elevated
    from strategy_lab.strategies.options_iv_gate import check_ivr_gate
    ivr_gate = profile_config.get("ivr_gate", {})
    min_ivr = float(ivr_gate.get("minimum_ivr", 0))
    label_in_reason = bool(ivr_gate.get("label_in_reason", True))

    out: List[Signal] = []
    for symbol, bar_list in bars.items():
        if not bar_list:
            continue
        closes = [float(b.get("c", 0)) for b in bar_list]

        if min_ivr > 0:
            passes, ivr_estimate, ivr_label = check_ivr_gate(
                symbol, closes, regime, min_ivr, label_in_reason
            )
            if not passes:
                continue

        sigs = _v1_signals(symbol, closes)

        if min_ivr > 0 and label_in_reason and sigs:
            _, ivr_estimate, ivr_label = check_ivr_gate(
                symbol, closes, regime, min_ivr, label_in_reason
            )
            out.extend([
                Signal(
                    symbol=s.symbol, side=s.side, confidence=s.confidence,
                    size_hint=s.size_hint,
                    reason=f"{s.reason} {ivr_label}",
                    strategy=s.strategy,
                )
                for s in sigs
            ])
        else:
            out.extend(sigs)
    return out


def generate_signal(symbol: str, closes: list[float], **kwargs) -> Optional[Signal]:
    """Backwards-compat shim."""
    sigs = _v1_signals(symbol, closes)
    return sigs[0] if sigs else None
