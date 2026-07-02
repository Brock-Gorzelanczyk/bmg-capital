"""Poor Man's Covered Call (PMCC / Diagonal) — long LEAPS + short near-term call.

Structure: buy 12-18 month 70-80 delta call (LEAPS) + sell 30d 30-delta OTM call.
Capital efficient (40-60% of stock replacement cost). Produces weekly/monthly income.

Entry conditions (all required):
  1. Stock in confirmed uptrend: price > SMA50 and SMA20 > SMA50 (bullish alignment)
  2. Price not over-extended: within 8% above SMA20 (avoid chasing)
  3. VIX between 12-30 — needs enough IV for short call premium; not panic
  4. Not bear trending regime
  5. Market IVR proxy >= 20 (even moderate IV works for PMCC since LEAPS are long vega)

Reference: tastytrade PMCC. Long LEAPS = long vega hedge on the short call.
Risk: if stock falls sharply, LEAPS lose value faster than short call credit.
Manage: roll short call up/out monthly; close LEAPS if stock breaks below SMA50.
"""
from __future__ import annotations

import json
import logging
from typing import List, Optional

from strategy_lab.core.signals import Signal
from strategy_lab.strategies._options_helpers import rsi, sma

logger = logging.getLogger(__name__)
STRATEGY_NAME = "pmcc_diagonal"

VIX_MIN        = 10.0  # 2026-07-01 Brock aggressive: 12 → 10
VIX_MAX        = 35.0  # 30 → 35
MARKET_IVR_MIN = 5     # 20 → 5
MAX_EXTENSION  = 0.20  # 0.08 → 0.20 — 20% band above SMA20
BASE_SIZE      = 0.05


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
    if vix_value is not None and (vix_value < VIX_MIN or vix_value > VIX_MAX):
        return False, 0.0, ""

    sma50 = sma(closes, 50)
    sma20 = sma(closes, 20)
    if sma50 is None or sma20 is None:
        return False, 0.0, ""

    if closes[-1] <= sma50:
        return False, 0.0, ""
    if sma20 <= sma50:
        return False, 0.0, ""

    extension = (closes[-1] - sma20) / sma20
    if extension > MAX_EXTENSION:
        logger.debug("[pmcc] %s: over-extended %.1f%% above SMA20 — skip", symbol, extension * 100)
        return False, 0.0, ""

    rsi14 = rsi(closes, 14)
    rsi_ok = rsi14 is not None and 40.0 <= rsi14 <= 75.0

    spot = closes[-1]
    trend_strength = min(0.10, (sma20 - sma50) / sma50 * 5.0)
    confidence     = round(min(0.84, 0.64 + trend_strength + (0.04 if rsi_ok else 0.0)), 4)

    reason = json.dumps({
        "setup":     "pmcc_diagonal",
        "spot":      round(spot, 2),
        "sma20":     round(sma20, 2),
        "sma50":     round(sma50, 2),
        "extension": round(extension * 100, 1),
        "rsi14":     round(rsi14, 1) if rsi14 else None,
        "mkt_ivr":   round(vol_pctile, 1),
        "vix":       round(vix_value, 1) if vix_value else None,
        "structure": "buy 12-18mo 75-delta LEAPS + sell 30d 30-delta OTM call",
        "manage":    "roll short call monthly; close if stock breaks SMA50",
    })
    return True, confidence, reason


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    out: List[Signal] = []
    for symbol, bar_list in bars.items():
        if not bar_list:
            continue
        closes = [float(b.get("c", 0)) for b in bar_list if b.get("c")]
        if len(closes) < 52:
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
