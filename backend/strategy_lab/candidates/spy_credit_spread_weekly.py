"""SPY Weekly Credit Spread — 7 DTE directional income.

Direction: determined by 20-day MA (bull = sell put spread, bear = sell call spread).
Structure: 30-delta short / 5-point wide spread, 7 DTE.
Exit: 50% profit OR Thursday close (whichever first).
"""
from __future__ import annotations

from datetime import datetime
from typing import List

from strategy_lab.core.signals import Signal

CANDIDATE_CONFIG = {
    "id":             "spy_credit_spread_weekly",
    "name":           "SPY Weekly Credit Spread",
    "asset_class":    "options",
    "strategy_type":  "options_income",
    "universe":       ["SPY"],
    "cadence":        "weekly",
    "claimed_sharpe": 0.85,
    "evidence_tier":  1,
    "complexity":     "medium",
    "description":    "7 DTE 30-delta credit spread on SPY, direction by 20MA, exit 50% or Thursday",
}

STRATEGY_NAME = "spy_credit_spread_weekly"
_MA_PERIOD = 20


def _sma(closes: list[float], n: int) -> float | None:
    if len(closes) < n:
        return None
    return sum(closes[-n:]) / n


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    if regime.get("playbook_regime") == "CRISIS":
        return []

    # Only enter on Monday (weekday 0)
    today = datetime.utcnow()
    if today.weekday() != 0:
        return []

    spy_bars = bars.get("SPY", [])
    if not spy_bars:
        return []

    closes = [float(b.get("c", 0)) for b in spy_bars]
    ma20 = _sma(closes, _MA_PERIOD)
    if ma20 is None:
        return []

    price = closes[-1]
    is_bull = price > ma20

    vix_bars = bars.get("VIX", []) or bars.get("^VIX", [])
    ivr = None
    if vix_bars:
        vix_c = [float(b.get("c", 0)) for b in vix_bars]
        window = vix_c[-252:] if len(vix_c) >= 252 else vix_c
        ivr = sum(1 for v in window if v <= vix_c[-1]) / len(window) * 100

    if ivr is not None and ivr < 20:
        return []

    side = "sell_put_spread" if is_bull else "sell_call_spread"
    direction = "bullish" if is_bull else "bearish"
    conf = 0.65

    return [Signal(
        symbol="SPY", side=side, confidence=conf, size_hint=0.10,
        reason=f"7 DTE credit spread: SPY {direction} (vs MA20 {ma20:.2f}), 30-delta, 5pt wide",
        strategy=STRATEGY_NAME,
    )]
