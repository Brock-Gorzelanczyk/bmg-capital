"""Wheel Strategy — sell CSP in uptrend; if assigned, sell covered calls until called away.

Signal = CSP entry trigger. The "wheel" proceeds when assigned:
  Phase 1: Sell 30d CSP at 20-delta strike (5-8% OTM)
  Phase 2: If assigned, sell 30d CC at 20-delta strike above cost basis
  Repeat until called away or strategy exits.

Entry conditions for Phase 1 CSP (all required):
  1. Market IVR proxy (vol_pctile) >= 25 — elevated premium
  2. Per-symbol realized vol pctile >= 25 — worth the premium
  3. Long-term uptrend: price above 40-period high (or last 40 bars)
  4. Pullback from SMA20: -8% to -2% (buying dip = better CSP entry)
  5. Not in bear regime, not panic

Reference: tastytrade "The Wheel" strategy.
"""
from __future__ import annotations

import json
import logging
from typing import List, Optional

from strategy_lab.core.signals import Signal
from strategy_lab.strategies._options_helpers import realized_vol_pctile, sma

logger = logging.getLogger(__name__)
STRATEGY_NAME = "wheel_strategy"

MARKET_IVR_MIN = 10     # 2026-07-01 Brock aggressive: 25 → 10
SYMBOL_IVR_MIN = 10     # 25 → 10
PULLBACK_MIN   = 0.002  # 2026-07-01: 0.02 → 0.002 fire on tiny dip too
PULLBACK_MAX   = 0.15   # 2026-07-01: 0.08 → 0.15 tolerate deeper dips
BASE_SIZE      = 0.06


def _entry_conditions(
    symbol: str,
    closes: list[float],
    regime: dict,
) -> tuple[bool, float, str]:
    vix_regime   = regime.get("vix_regime", "mid")
    trend_regime = regime.get("trend_regime", "chop")
    vol_pctile   = regime.get("vol_pctile") or 50.0
    vix_value    = regime.get("vix_value")

    if vix_regime == "panic":
        return False, 0.0, ""
    if trend_regime == "bear":
        return False, 0.0, ""
    if vol_pctile < MARKET_IVR_MIN:
        return False, 0.0, ""

    sym_ivr = realized_vol_pctile(closes)
    if sym_ivr is None or sym_ivr < SYMBOL_IVR_MIN:
        return False, 0.0, ""

    # Long-term uptrend: higher than 40 bars ago
    if len(closes) < 42:
        return False, 0.0, ""
    in_uptrend = closes[-1] > closes[-41]
    if not in_uptrend:
        return False, 0.0, ""

    sma20 = sma(closes, 20)
    if sma20 is None:
        return False, 0.0, ""

    deviation = (closes[-1] - sma20) / sma20
    if not (-PULLBACK_MAX <= deviation <= -PULLBACK_MIN):
        return False, 0.0, ""

    spot = closes[-1]
    pullback_depth = abs(deviation)
    ivr_bonus  = min(0.10, (sym_ivr - SYMBOL_IVR_MIN) / 300.0)
    pb_bonus   = min(0.10, (pullback_depth - PULLBACK_MIN) / (PULLBACK_MAX - PULLBACK_MIN) * 0.10)
    confidence = round(min(0.86, 0.66 + ivr_bonus + pb_bonus), 4)

    reason = json.dumps({
        "setup":       "wheel_strategy",
        "phase":       "csp_entry",
        "spot":        round(spot, 2),
        "sma20":       round(sma20, 2),
        "deviation":   round(deviation * 100, 1),
        "sym_ivr":     round(sym_ivr, 1),
        "mkt_ivr":     round(vol_pctile, 1),
        "vix":         round(vix_value, 1) if vix_value else None,
        "trend":       trend_regime,
        "strikes":     "20-delta CSP, 30 DTE, willing to own at strike",
        "manage":      "close at 50% credit or 21 DTE; if assigned → sell CC",
    })
    return True, confidence, reason


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    out: List[Signal] = []
    for symbol, bar_list in bars.items():
        if not bar_list:
            continue
        closes = [float(b.get("c", 0)) for b in bar_list if b.get("c")]
        if len(closes) < 42:
            continue
        enter, conf, reason = _entry_conditions(symbol, closes, regime)
        if not enter:
            continue
        out.append(Signal(
            symbol=symbol,
            side="buy",
            confidence=conf,
            size_hint=BASE_SIZE,
            reason=reason,
            strategy=STRATEGY_NAME,
        ))
    return out


def generate_signal(symbol: str, closes: list[float], **kwargs) -> Optional[Signal]:
    regime = kwargs.get("regime", {})
    enter, conf, reason = _entry_conditions(symbol, closes, regime)
    if not enter:
        return None
    return Signal(symbol=symbol, side="buy", confidence=conf,
                  size_hint=BASE_SIZE, reason=reason, strategy=STRATEGY_NAME)
