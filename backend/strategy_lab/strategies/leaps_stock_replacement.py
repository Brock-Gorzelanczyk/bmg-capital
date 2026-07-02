"""LEAPS Stock Replacement — buy 12-18 month deep ITM call as capital-efficient stock proxy.

Buy 70-80 delta LEAPS call instead of 100 shares. Requires 40-60% of stock capital.
Provides leverage-like exposure with defined max loss = option premium paid.

Entry conditions (all required):
  1. Consistent uptrend: price > SMA50 AND SMA20 > SMA50 (golden cross alignment)
  2. Not over-extended: price within 10% of SMA20 (avoid buying tops)
  3. RSI(14) between 45-70 — healthy trend, not overbought
  4. Bull trending regime OR neutral (bearish regime invalidates LEAPS thesis)
  5. VIX < 28 — very high VIX inflates LEAPS premiums (expensive to buy long vol)
  6. 30-day return > 0% (the trend must be working recently)

Reference: tastytrade LEAPS replacement. Capital: ~45-55% vs 100% for shares.
Effective delta: 70-80 (moves nearly like stock above that threshold).
Exit: roll up if deep ITM; close if SMA50 broken or 6 months to expiry.
"""
from __future__ import annotations

import json
import logging
from typing import List, Optional

from strategy_lab.core.signals import Signal
from strategy_lab.strategies._options_helpers import rsi, sma

logger = logging.getLogger(__name__)
STRATEGY_NAME = "leaps_stock_replacement"

VIX_MAX        = 40.0  # 2026-07-01 Brock aggressive: 28 → 40
RSI_MIN        = 25.0  # 45 → 25
RSI_MAX        = 85.0  # 70 → 85
MAX_EXTENSION  = 0.30  # 0.10 → 0.30 — 30% above SMA20 still OK
BASE_SIZE      = 0.05


def _entry_conditions(
    symbol: str,
    closes: list[float],
    regime: dict,
) -> tuple[bool, float, str]:
    vix_regime   = regime.get("vix_regime", "mid")
    trend_regime = regime.get("trend_regime", "chop")
    vix_value    = regime.get("vix_value")

    if vix_regime == "panic":
        return False, 0.0, ""
    if trend_regime == "bear":
        return False, 0.0, ""
    if vix_value is not None and vix_value > VIX_MAX:
        return False, 0.0, ""

    sma50 = sma(closes, 50)
    sma20 = sma(closes, 20)
    if sma50 is None or sma20 is None:
        return False, 0.0, ""

    if closes[-1] <= sma50 or closes[-1] <= sma20:
        return False, 0.0, ""
    if sma20 <= sma50:
        return False, 0.0, ""

    extension = (closes[-1] - sma20) / sma20
    if extension > MAX_EXTENSION:
        logger.debug("[leaps] %s: price %.1f%% above SMA20 — over-extended", symbol, extension * 100)
        return False, 0.0, ""

    rsi14 = rsi(closes, 14)
    if rsi14 is None or not (RSI_MIN <= rsi14 <= RSI_MAX):
        return False, 0.0, ""

    if len(closes) < 31:
        return False, 0.0, ""
    ret_30d = (closes[-1] - closes[-31]) / closes[-31] if closes[-31] > 0 else 0.0
    if ret_30d <= 0:
        return False, 0.0, ""

    spot = closes[-1]
    trend_quality = min(0.12, (sma20 - sma50) / sma50 * 3.0)
    mom_bonus     = min(0.08, ret_30d * 0.5)
    confidence    = round(min(0.86, 0.64 + trend_quality + mom_bonus), 4)

    reason = json.dumps({
        "setup":       "leaps_stock_replacement",
        "spot":        round(spot, 2),
        "sma20":       round(sma20, 2),
        "sma50":       round(sma50, 2),
        "extension":   round(extension * 100, 1),
        "ret_30d":     round(ret_30d * 100, 1),
        "rsi14":       round(rsi14, 1),
        "vix":         round(vix_value, 1) if vix_value else None,
        "structure":   "buy 12-18mo 70-80 delta call; ~45-55% of stock cost",
        "manage":      "roll up if delta > 90; close if SMA50 breaks below spot",
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
