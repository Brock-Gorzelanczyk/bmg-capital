"""Cash-secured put: sell put at strike you'd accept assignment on."""
from __future__ import annotations
import logging
from statistics import mean
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "cash_secured_put"


def _v1_signals(symbol: str, closes: list[float]) -> List[Signal]:
    """Core logic: sell CSP when in uptrend with slight pullback."""
    if len(closes) < 20:
        return []
    sma20 = mean(closes[-20:])
    in_uptrend = closes[-1] > sma20
    recent_high = max(closes[-20:])
    pullback = (closes[-1] - recent_high) / recent_high < -0.02 if recent_high > 0 else False
    if in_uptrend and pullback:
        return [Signal(
            symbol=symbol, side="buy", confidence=0.72,
            size_hint=0.72,
            reason="CSP: sell 30d put 5-8% OTM, willing to own at strike if assigned",
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
