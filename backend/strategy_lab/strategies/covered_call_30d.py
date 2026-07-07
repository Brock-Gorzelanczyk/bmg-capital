"""Covered Call 30d — sell OTM call against long stock position for income.

Entry conditions (all required):
  1. Market IVR proxy (vol_pctile) >= 30 — elevated premium environment
  2. Per-symbol realized vol pctile >= 25 — worth collecting
  3. Stock range-bound over 5 days (avg daily return -0.5% to +1.5%)
  4. Price within 5% of 20-day SMA — not in a rocket or in freefall
  5. Not in panic VIX regime

Reference: Covered call income strategy — 30 DTE, 5-7% OTM call.
Profit target: 50% of premium received or expiration. Roll at 21 DTE.
"""
from __future__ import annotations

import json
import logging
from statistics import mean
from typing import List, Optional

from strategy_lab.core.signals import Signal
from strategy_lab.strategies._options_helpers import realized_vol_pctile, sma

logger = logging.getLogger(__name__)
STRATEGY_NAME = "covered_call_30d"

MARKET_IVR_MIN   = 10      # 2026-07-01 Brock aggressive: 30 → 10
SYMBOL_IVR_MIN   = 10      # 25 → 10
MAX_DEVIATION    = 0.12    # 2026-07-01: 0.05 → 0.12 — 12% band around SMA20
BASE_SIZE        = 0.04


def _entry_conditions(
    symbol: str,
    closes: list[float],
    regime: dict,
) -> tuple[bool, float, str]:
    vix_regime = regime.get("vix_regime", "mid")
    vol_pctile = regime.get("vol_pctile") or 50.0
    vix_value  = regime.get("vix_value")

    if vix_regime == "panic":
        return False, 0.0, ""
    if vol_pctile < MARKET_IVR_MIN:
        return False, 0.0, ""

    sym_ivr = realized_vol_pctile(closes)
    if sym_ivr is None or sym_ivr < SYMBOL_IVR_MIN:
        return False, 0.0, ""

    if len(closes) < 6:
        return False, 0.0, ""

    returns_5d = [
        (closes[i] - closes[i - 1]) / closes[i - 1]
        for i in range(-5, 0)
        if closes[i - 1] > 0
    ]
    if not returns_5d:
        return False, 0.0, ""
    avg_5d = mean(returns_5d)

    # Range-bound: average daily move between -0.5% and +1.5%
    if not (-0.005 <= avg_5d <= 0.015):
        return False, 0.0, ""

    sma20 = sma(closes, 20)
    if sma20 is None:
        return False, 0.0, ""
    deviation = abs(closes[-1] - sma20) / sma20
    if deviation > MAX_DEVIATION:
        return False, 0.0, ""

    spot = closes[-1]
    ivr_bonus  = min(0.12, (sym_ivr - SYMBOL_IVR_MIN) / 250.0)
    confidence = round(min(0.82, 0.62 + ivr_bonus), 4)

    reason = json.dumps({
        "setup":     "covered_call_30d",
        "spot":      round(spot, 2),
        "sma20":     round(sma20, 2),
        "avg_5d":    round(avg_5d * 100, 2),
        "sym_ivr":   round(sym_ivr, 1),
        "mkt_ivr":   round(vol_pctile, 1),
        "vix":       round(vix_value, 1) if vix_value else None,
        "strikes":   "30 DTE call, 5-7% OTM",
        "manage":    "close at 50% premium or roll at 21 DTE",
    })
    return True, confidence, reason


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    out: List[Signal] = []
    for symbol, bar_list in bars.items():
        if not bar_list:
            continue
        closes = [float(b.get("c", 0)) for b in bar_list if b.get("c")]
        if len(closes) < 22:
            continue
        enter, conf, reason = _entry_conditions(symbol, closes, regime)
        if not enter:
            continue
        out.append(Signal(
            symbol=symbol,
            side="sell",
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
    return Signal(symbol=symbol, side="sell", confidence=conf,
                  size_hint=BASE_SIZE, reason=reason, strategy=STRATEGY_NAME)
