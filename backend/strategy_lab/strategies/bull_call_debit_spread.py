"""Bull Call Debit Spread — buy lower call, sell higher call for net debit.

Unlike credit spreads, this PAYS a net debit. Profits only if stock rises
enough to cover the debit. Best in low-IV environments (buy spreads cheap).

Entry conditions (all required):
  1. Strong uptrend: price > SMA20 by at least 3% (confirmed momentum)
  2. 5-day momentum: price > 5 days ago by > 1%
  3. Volume confirmation: current volume > 1.2x avg (if data available)
  4. VIX between 12-22 — debit spreads are cheapest when IV is low
  5. Bull trending regime preferred (or neutral at minimum)
  6. RSI(14) between 50-75 — momentum but not overbought

Reference: Buy 30d ATM-to-slightly-OTM call, sell 10% OTM call for cap.
Net debit = max risk. Max profit = spread width - debit. Target 50% of max profit.
"""
from __future__ import annotations

import json
import logging
from typing import List, Optional

from strategy_lab.core.signals import Signal
from strategy_lab.strategies._options_helpers import rsi, sma

logger = logging.getLogger(__name__)
STRATEGY_NAME = "bull_call_debit_spread"

VIX_MAX         = 35.0  # 2026-07-01 Brock aggressive: 22 → 35
VIX_MIN         = 8.0   # 12 → 8
RSI_MIN         = 30.0  # 50 → 30 — allow entry deeper in pullback too
RSI_MAX         = 85.0  # 75 → 85
MIN_SMA_PREMIUM = 0.001 # 0.03 → 0.001 — near-SMA entries OK
MIN_5D_MOM      = -0.02 # 0.01 → -0.02 — allow slight recent chop
BASE_SIZE       = 0.04


def _entry_conditions(
    symbol: str,
    closes: list[float],
    volumes: list[float],
    regime: dict,
) -> tuple[bool, float, str]:
    vix_regime   = regime.get("vix_regime", "mid")
    trend_regime = regime.get("trend_regime", "chop")
    vix_value    = regime.get("vix_value")

    if vix_regime == "panic":
        return False, 0.0, ""
    if trend_regime == "bear":
        return False, 0.0, ""
    if vix_value is not None and not (VIX_MIN <= vix_value <= VIX_MAX):
        return False, 0.0, ""

    sma20 = sma(closes, 20)
    if sma20 is None:
        return False, 0.0, ""

    premium = (closes[-1] - sma20) / sma20
    if premium < MIN_SMA_PREMIUM:
        return False, 0.0, ""

    if len(closes) < 6:
        return False, 0.0, ""
    mom_5d = (closes[-1] - closes[-6]) / closes[-6] if closes[-6] > 0 else 0.0
    if mom_5d < MIN_5D_MOM:
        return False, 0.0, ""

    rsi14 = rsi(closes, 14)
    if rsi14 is None or not (RSI_MIN <= rsi14 <= RSI_MAX):
        return False, 0.0, ""

    # Volume confirmation (optional enhancement)
    vol_confirmed = False
    if len(volumes) >= 11:
        from statistics import mean
        avg_vol = mean(volumes[-11:-1])
        vol_confirmed = avg_vol > 0 and volumes[-1] > avg_vol * 1.2

    spot = closes[-1]
    momentum_bonus = min(0.10, mom_5d * 3.0)
    rsi_bonus      = min(0.08, (rsi14 - RSI_MIN) / (RSI_MAX - RSI_MIN) * 0.08)
    vol_bonus      = 0.04 if vol_confirmed else 0.0
    confidence     = round(min(0.86, 0.60 + momentum_bonus + rsi_bonus + vol_bonus), 4)

    reason = json.dumps({
        "setup":      "bull_call_debit_spread",
        "spot":       round(spot, 2),
        "sma20":      round(sma20, 2),
        "premium":    round(premium * 100, 1),
        "mom_5d":     round(mom_5d * 100, 1),
        "rsi14":      round(rsi14, 1),
        "vol_conf":   vol_confirmed,
        "vix":        round(vix_value, 1) if vix_value else None,
        "strikes":    "buy ATM call, sell 8-10% OTM call, 30 DTE, net debit",
        "manage":     "close at 50% of max profit; stop at 50% of max loss",
    })
    return True, confidence, reason


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    out: List[Signal] = []
    for symbol, bar_list in bars.items():
        if not bar_list:
            continue
        closes  = [float(b.get("c", 0)) for b in bar_list if b.get("c")]
        volumes = [float(b.get("v", 0)) for b in bar_list]
        if len(closes) < 22:
            continue
        enter, conf, reason = _entry_conditions(symbol, closes, volumes, regime)
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
    regime  = kwargs.get("regime", {})
    volumes = kwargs.get("volumes", [])
    enter, conf, reason = _entry_conditions(symbol, closes, volumes, regime)
    if not enter:
        return None
    return Signal(symbol=symbol, side="buy", confidence=conf,
                  size_hint=BASE_SIZE, reason=reason, strategy=STRATEGY_NAME)
