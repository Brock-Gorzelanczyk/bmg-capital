"""Cash-Secured Put — sell 30-day OTM put at strike you'd accept assignment on.

Entry conditions (all required):
  1. Market IVR proxy (vol_pctile) >= 30 — elevated premium environment
  2. Per-symbol realized vol pctile >= 25 — symbol-specific IV elevated
  3. Price above 20-day SMA — long-term uptrend (own-ability filter)
  4. Pullback 1-8% below 20-day SMA or from recent 20d high — better entry
  5. Not in bear trending regime
  6. VIX < 40 (crash-risk exclusion)

Reference: Karen the Supertrader / Tastytrade CSP mechanics.
Target: 20-delta strike (~5-8% OTM), 30 DTE, 50% profit close or 21 DTE roll.
"""
from __future__ import annotations

import json
import logging
from typing import List, Optional

from strategy_lab.core.signals import Signal
from strategy_lab.strategies._options_helpers import realized_vol_pctile, sma

logger = logging.getLogger(__name__)
STRATEGY_NAME = "cash_secured_put"

MARKET_IVR_MIN = 10   # 2026-07-01 (Brock aggressive): 30 → 10, fire in low-vol
SYMBOL_IVR_MIN = 10   # 30 → 10
VIX_MAX        = 40.0
BASE_SIZE      = 0.05
PULLBACK_MIN   = 0.001  # 2026-07-01: 0.01 → 0.001 fire on tiny pullbacks too
PULLBACK_MAX   = 0.15   # 2026-07-01: 0.09 → 0.15 tolerate deeper dips


def _entry_conditions(
    symbol: str,
    closes: list[float],
    regime: dict,
) -> tuple[bool, float, str]:
    trend_regime = regime.get("trend_regime", "chop")
    vix_regime   = regime.get("vix_regime", "mid")
    vol_pctile   = regime.get("vol_pctile") or 50.0
    vix_value    = regime.get("vix_value")

    if vix_regime == "panic":
        return False, 0.0, ""
    if trend_regime == "bear":
        return False, 0.0, ""
    if vix_value is not None and vix_value > VIX_MAX:
        return False, 0.0, ""
    if vol_pctile < MARKET_IVR_MIN:
        return False, 0.0, ""

    sym_ivr = realized_vol_pctile(closes)
    if sym_ivr is None or sym_ivr < SYMBOL_IVR_MIN:
        return False, 0.0, ""

    sma20 = sma(closes, 20)
    if sma20 is None or closes[-1] < sma20 * (1 - PULLBACK_MAX):
        return False, 0.0, ""

    # Must be in uptrend (above SMA20) OR slight pullback below it
    in_uptrend = closes[-1] >= sma20
    deviation  = (closes[-1] - sma20) / sma20

    # Prefer entries slightly below SMA20 (1-5% pullback) or near it
    if not in_uptrend and abs(deviation) > PULLBACK_MAX:
        return False, 0.0, ""

    # Check pullback from 20d high
    high_20 = max(closes[-20:]) if len(closes) >= 20 else closes[-1]
    pullback_from_high = (high_20 - closes[-1]) / high_20 if high_20 > 0 else 0.0

    if pullback_from_high < PULLBACK_MIN:
        return False, 0.0, ""

    spot = closes[-1]

    # Confidence higher for deeper pullback (better entry) + higher IVR
    pullback_bonus = min(0.12, pullback_from_high * 2.0)
    ivr_bonus      = min(0.10, (sym_ivr - SYMBOL_IVR_MIN) / 250.0)
    confidence     = round(min(0.88, 0.65 + pullback_bonus + ivr_bonus), 4)

    reason = json.dumps({
        "setup":       "cash_secured_put",
        "spot":        round(spot, 2),
        "sma20":       round(sma20, 2),
        "deviation":   round(deviation * 100, 1),
        "pullback_pct": round(pullback_from_high * 100, 1),
        "sym_ivr":     round(sym_ivr, 1),
        "mkt_ivr":     round(vol_pctile, 1),
        "vix":         round(vix_value, 1) if vix_value else None,
        "strikes":     "20-delta put ~5-8% OTM, 30 DTE",
        "manage":      "close at 50% credit or 21 DTE; roll down if assigned",
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
