"""Wheel strategy: sell cash-secured puts in uptrend, then covered calls if assigned."""
from __future__ import annotations
import logging
from statistics import mean
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "wheel_strategy"


def _v1_signals(symbol: str, closes: list[float]) -> List[Signal]:
    """Core logic: sell CSP when near support in uptrend."""
    if len(closes) < 20:
        return []
    sma20 = mean(closes[-20:])
    deviation = (closes[-1] - sma20) / sma20 if sma20 > 0 else 0
    in_uptrend = closes[-1] > closes[-40] if len(closes) >= 40 else True
    if -0.08 <= deviation <= -0.02 and in_uptrend:
        return [Signal(
            symbol=symbol, side="buy", confidence=0.70,
            size_hint=0.70,
            reason=f"Wheel: sell 30d CSP at current strike, deviation={deviation:.2%} from SMA20",
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

        # IVR check using VIX percentile proxy
        if min_ivr > 0:
            passes, ivr_estimate, ivr_label = check_ivr_gate(
                symbol, closes, regime, min_ivr, label_in_reason
            )
            if not passes:
                continue

        sigs = _v1_signals(symbol, closes)

        # Annotate signal with IVR info if gate is configured and label requested
        if min_ivr > 0 and label_in_reason and sigs:
            _, ivr_estimate, ivr_label = check_ivr_gate(
                symbol, closes, regime, min_ivr, label_in_reason
            )
            annotated = []
            for sig in sigs:
                annotated.append(Signal(
                    symbol=sig.symbol,
                    side=sig.side,
                    confidence=sig.confidence,
                    size_hint=sig.size_hint,
                    reason=f"{sig.reason} {ivr_label}",
                    strategy=sig.strategy,
                ))
            out.extend(annotated)
        else:
            out.extend(sigs)
    return out


def generate_signal(symbol: str, closes: list[float], **kwargs) -> Optional[Signal]:
    """Backwards-compat shim."""
    sigs = _v1_signals(symbol, closes)
    return sigs[0] if sigs else None
