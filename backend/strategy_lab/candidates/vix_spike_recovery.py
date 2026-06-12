"""VIX Spike Recovery — buy SPY when VIX drops back below 30 after a spike.

Entry: VIX closes BELOW 30 after having been ABOVE 30 in the previous 5 days.
Exit: +5% profit OR 20 trading days, whichever first.
"""
from __future__ import annotations

from typing import List

from strategy_lab.core.signals import Signal

CANDIDATE_CONFIG = {
    "id":             "vix_spike_recovery",
    "name":           "VIX Spike Recovery",
    "asset_class":    "stocks",
    "strategy_type":  "mean_reversion",
    "universe":       ["SPY"],
    "cadence":        "daily",
    "claimed_sharpe": 0.95,
    "evidence_tier":  1,
    "complexity":     "low",
    "description":    "Buy SPY when VIX closes below 30 after spiking above; exit +5% or 20 days",
    "max_hold_days":  20,
    "profit_target":  0.05,
}

STRATEGY_NAME = "vix_spike_recovery"

_VIX_SPIKE_THRESHOLD = 30.0
_LOOKBACK_DAYS = 5


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    vix_bars = bars.get("VIX", []) or bars.get("^VIX", [])
    spy_bars = bars.get("SPY", [])

    if not vix_bars or not spy_bars or len(vix_bars) < _LOOKBACK_DAYS + 1:
        return []

    vix_closes = [float(b.get("c", 0)) for b in vix_bars]
    current_vix = vix_closes[-1]
    recent_vix  = vix_closes[-(1 + _LOOKBACK_DAYS):-1]

    was_above = any(v > _VIX_SPIKE_THRESHOLD for v in recent_vix)
    now_below = current_vix < _VIX_SPIKE_THRESHOLD

    if not (was_above and now_below):
        return []

    max_spike = max(recent_vix)
    conf = min(0.80, 0.55 + (max_spike - _VIX_SPIKE_THRESHOLD) / 60.0)

    return [Signal(
        symbol="SPY", side="buy", confidence=conf, size_hint=0.50,
        reason=f"VIX spike recovery: peaked {max_spike:.1f}, now {current_vix:.1f} (<30) — mean-revert entry",
        strategy=STRATEGY_NAME,
    )]
