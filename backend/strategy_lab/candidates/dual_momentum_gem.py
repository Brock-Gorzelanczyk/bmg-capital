"""Dual Momentum — Global Equity Momentum (GEM) by Gary Antonacci.

Monthly rebalance:
1. Compare SPY vs ACWI (ex-US) on 12-month absolute return.
2. If the winner has positive 12m return: hold it.
3. If the winner has negative 12m return: hold AGG (bonds).

Signals fire once per month on the first trading day.
"""
from __future__ import annotations

from datetime import datetime
from typing import List

from strategy_lab.core.signals import Signal

CANDIDATE_CONFIG = {
    "id":             "dual_momentum_gem",
    "name":           "Dual Momentum GEM",
    "asset_class":    "stocks",
    "strategy_type":  "momentum",
    "universe":       ["SPY", "ACWI", "AGG"],
    "cadence":        "monthly",
    "claimed_sharpe": 0.9,
    "evidence_tier":  1,
    "complexity":     "low",
    "description":    "Monthly: SPY vs ACWI 12m return, hold winner if positive else AGG",
    "reference":      "Antonacci 2014 'Dual Momentum Investing'",
}

STRATEGY_NAME = "dual_momentum_gem"


def _return_12m(bar_list: list[dict]) -> float | None:
    """Compute 12-month return from daily bars (approx 252 trading days)."""
    if len(bar_list) < 252:
        return None
    start = float(bar_list[-252].get("c", 0))
    end   = float(bar_list[-1].get("c", 1))
    if start <= 0:
        return None
    return (end - start) / start


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    # Only fire on the first trading day of each month
    today = datetime.utcnow()
    if today.day > 5:
        return []

    spy_bars  = bars.get("SPY", [])
    acwi_bars = bars.get("ACWI", [])
    agg_bars  = bars.get("AGG", [])

    spy_ret  = _return_12m(spy_bars)
    acwi_ret = _return_12m(acwi_bars)

    if spy_ret is None or acwi_ret is None:
        return []

    out: List[Signal] = []

    if spy_ret > acwi_ret:
        winner_sym, winner_ret = "SPY", spy_ret
    else:
        winner_sym, winner_ret = "ACWI", acwi_ret

    if winner_ret > 0:
        out.append(Signal(
            symbol=winner_sym, side="buy", confidence=0.72, size_hint=1.0,
            reason=f"GEM: {winner_sym} wins 12m ({winner_ret:+.1%}), positive absolute — go equities",
            strategy=STRATEGY_NAME,
        ))
    else:
        out.append(Signal(
            symbol="AGG", side="buy", confidence=0.68, size_hint=1.0,
            reason=f"GEM: {winner_sym} 12m={winner_ret:+.1%} negative — rotate to bonds (AGG)",
            strategy=STRATEGY_NAME,
        ))

    return out
