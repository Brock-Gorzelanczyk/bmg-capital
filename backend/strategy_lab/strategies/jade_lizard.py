"""Jade Lizard — sell OTM put + OTM call spread for no upside risk.

Structure: sell 1 OTM put + sell 1 OTM call spread (bear call spread).
When total credit received > call spread width → zero upside risk.

Entry conditions (all required):
  1. Market IVR proxy (vol_pctile) >= 35 — jade lizard needs elevated IV
  2. Per-symbol realized vol pctile >= 30
  3. Slightly bullish bias: 5d return > 0% but < 5% (not overbought)
  4. RSI(14) between 45 and 65 — neutral-to-mildly-bullish
  5. Price within 3% of 20-day SMA — not extended
  6. Not panic VIX

Reference: tastytrade Jade Lizard. Best in slightly-bullish, elevated-IV environments.
Net credit must exceed call spread width to achieve zero upside risk.
Manage: close at 50% credit, max loss is put strike minus credit.
"""
from __future__ import annotations

import json
import logging
from typing import List, Optional

from strategy_lab.core.signals import Signal
from strategy_lab.strategies._options_helpers import realized_vol_pctile, rsi, sma

logger = logging.getLogger(__name__)
STRATEGY_NAME = "jade_lizard"

MARKET_IVR_MIN = 10    # 2026-07-01 Brock aggressive: 35 → 10
SYMBOL_IVR_MIN = 10    # 30 → 10
RSI_MIN        = 25.0  # 45 → 25 — allow more oversold entries
RSI_MAX        = 80.0  # 65 → 80 — allow more overbought entries
MAX_5D_RETURN  = 0.15  # 0.05 → 0.15
MAX_DEVIATION  = 0.15  # 0.03 → 0.15
BASE_SIZE      = 0.04


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

    if len(closes) < 16:
        return False, 0.0, ""

    ret_5d = (closes[-1] - closes[-6]) / closes[-6] if closes[-6] > 0 else 0.0
    if not (0.0 < ret_5d < MAX_5D_RETURN):
        return False, 0.0, ""

    rsi14 = rsi(closes, 14)
    if rsi14 is None or not (RSI_MIN <= rsi14 <= RSI_MAX):
        return False, 0.0, ""

    sma20 = sma(closes, 20)
    if sma20 is None:
        return False, 0.0, ""
    deviation = abs(closes[-1] - sma20) / sma20
    if deviation > MAX_DEVIATION:
        return False, 0.0, ""

    spot = closes[-1]
    ivr_bonus  = min(0.10, (sym_ivr - SYMBOL_IVR_MIN) / 350.0)
    confidence = round(min(0.84, 0.64 + ivr_bonus), 4)

    reason = json.dumps({
        "setup":     "jade_lizard",
        "spot":      round(spot, 2),
        "sma20":     round(sma20, 2),
        "ret_5d":    round(ret_5d * 100, 1),
        "rsi14":     round(rsi14, 1),
        "sym_ivr":   round(sym_ivr, 1),
        "mkt_ivr":   round(vol_pctile, 1),
        "vix":       round(vix_value, 1) if vix_value else None,
        "structure": "sell OTM put + sell OTM call spread; total credit > spread width = no upside risk",
        "manage":    "close at 50% credit; max loss on put side",
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
