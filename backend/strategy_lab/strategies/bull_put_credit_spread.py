"""Bull Put Credit Spread — sell higher put, buy lower put for net credit.

Entry conditions (all required):
  1. Stock in uptrend: price above 50-day SMA
  2. Not in sharp decline: 10-day return > -4%
  3. Market IVR proxy (vol_pctile) >= 25 — enough premium to justify spread
  4. RSI(14) between 35 and 70 — not overbought or in freefall
  5. Not bear trending, not panic VIX

Reference: Bull put spread = bullish/neutral credit strategy.
Target: 30 DTE, sell 30-delta put, buy 5-wide protection. Close at 50% credit.
Win rate: ~70-75% in backtests when IVR-filtered.
"""
from __future__ import annotations

import json
import logging
from typing import List, Optional

from strategy_lab.core.signals import Signal
from strategy_lab.strategies._options_helpers import rsi, sma

logger = logging.getLogger(__name__)
STRATEGY_NAME = "bull_put_credit_spread"

MARKET_IVR_MIN  = 25
RSI_MIN         = 35.0
RSI_MAX         = 70.0
MIN_10D_RETURN  = -0.04   # stock can't be in freefall
BASE_SIZE       = 0.04


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

    sma50 = sma(closes, 50)
    if sma50 is None or closes[-1] < sma50:
        return False, 0.0, ""

    # 10-day return: not in freefall
    if len(closes) < 11:
        return False, 0.0, ""
    ret_10d = (closes[-1] - closes[-11]) / closes[-11] if closes[-11] > 0 else 0.0
    if ret_10d < MIN_10D_RETURN:
        logger.debug("[bull_put] %s: 10d return=%.1f%% — too weak", symbol, ret_10d * 100)
        return False, 0.0, ""

    rsi14 = rsi(closes, 14)
    if rsi14 is None or not (RSI_MIN <= rsi14 <= RSI_MAX):
        logger.debug("[bull_put] %s: RSI14=%.1f — outside range", symbol, rsi14 or 0)
        return False, 0.0, ""

    spot = closes[-1]
    # Confidence: higher when RSI is in sweet spot (50-60), not stressed
    rsi_centrality = 1.0 - abs(rsi14 - 52.5) / 30.0
    trend_bonus    = min(0.08, ret_10d * 2) if ret_10d > 0 else 0.0
    confidence     = round(min(0.85, 0.63 + rsi_centrality * 0.10 + trend_bonus), 4)

    reason = json.dumps({
        "setup":      "bull_put_credit_spread",
        "spot":       round(spot, 2),
        "sma50":      round(sma50, 2),
        "ret_10d":    round(ret_10d * 100, 1),
        "rsi14":      round(rsi14, 1),
        "mkt_ivr":    round(vol_pctile, 1),
        "vix":        round(vix_value, 1) if vix_value else None,
        "strikes":    "sell 30-delta put, buy 5-wide protection, 30 DTE",
        "manage":     "close at 50% credit or 21 DTE; stop at 2x credit",
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
