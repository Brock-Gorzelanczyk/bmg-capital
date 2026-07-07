"""Bear Call Credit Spread — sell lower call, buy higher call for net credit.

Profits when stock stays flat or declines. The inverse of bull put spread.
Only initiate when there is a clear reason to be bearish/neutral.

Entry conditions (all required):
  1. Stock in downtrend or range-bound: price below 20-day SMA
  2. Recent 2-week return < 2% (stock not in strong uptrend)
  3. RSI(14) < 55 — not overbought momentum
  4. Not in bull trending regime (counterproductive to sell calls in bull market)
  5. Market IVR proxy >= 25 — enough premium to collect
  6. VIX not panic (undefined moves in panic crush spreads)

Reference: Bear call spread = bearish/neutral credit strategy.
Target: 30 DTE, sell 30-delta call, buy 5-wide OTM call. Close at 50% credit.
"""
from __future__ import annotations

import json
import logging
from typing import List, Optional

from strategy_lab.core.signals import Signal
from strategy_lab.strategies._options_helpers import rsi, sma

logger = logging.getLogger(__name__)
STRATEGY_NAME = "bear_call_credit_spread"

MARKET_IVR_MIN = 10    # 2026-07-01 Brock aggressive: 25 → 10
RSI_MAX        = 80.0  # 55 → 80 — allow entry even when uptrend cooling
MAX_2W_RETURN  = 0.12  # 0.02 → 0.12
BASE_SIZE      = 0.04


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
    if trend_regime == "bull":
        return False, 0.0, ""
    if vol_pctile < MARKET_IVR_MIN:
        return False, 0.0, ""

    sma20 = sma(closes, 20)
    if sma20 is None or closes[-1] > sma20:
        return False, 0.0, ""

    if len(closes) < 11:
        return False, 0.0, ""
    ret_2w = (closes[-1] - closes[-11]) / closes[-11] if closes[-11] > 0 else 0.0
    if ret_2w >= MAX_2W_RETURN:
        logger.debug("[bear_call] %s: 2w return=%.1f%% — too strong for bear call", symbol, ret_2w * 100)
        return False, 0.0, ""

    rsi14 = rsi(closes, 14)
    if rsi14 is None or rsi14 >= RSI_MAX:
        return False, 0.0, ""

    spot = closes[-1]
    weakness_bonus = min(0.10, abs(ret_2w) * 2.0) if ret_2w < 0 else 0.0
    rsi_bonus      = min(0.08, (RSI_MAX - rsi14) / 55.0 * 0.08)
    confidence     = round(min(0.82, 0.60 + weakness_bonus + rsi_bonus), 4)

    reason = json.dumps({
        "setup":    "bear_call_credit_spread",
        "spot":     round(spot, 2),
        "sma20":    round(sma20, 2),
        "ret_2w":   round(ret_2w * 100, 1),
        "rsi14":    round(rsi14, 1),
        "mkt_ivr":  round(vol_pctile, 1),
        "vix":      round(vix_value, 1) if vix_value else None,
        "strikes":  "sell 30-delta OTM call, buy 5-wide higher call, 30 DTE",
        "manage":   "close at 50% credit or 21 DTE; stop at 2x credit",
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
