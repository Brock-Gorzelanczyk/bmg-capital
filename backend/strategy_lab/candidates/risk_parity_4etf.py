"""Risk Parity 4-ETF — equal volatility contribution, monthly rebalance.

Assets: SPY (stocks), TLT (bonds), GLD (gold), DBC (commodities).
Weight each asset so its 63-day volatility contribution is equal.
Rebalances on the first trading day of each month.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import List

from strategy_lab.core.signals import Signal

CANDIDATE_CONFIG = {
    "id":             "risk_parity_4etf",
    "name":           "Risk Parity 4-ETF",
    "asset_class":    "stocks",
    "strategy_type":  "other",
    "universe":       ["SPY", "TLT", "GLD", "DBC"],
    "cadence":        "monthly",
    "claimed_sharpe": 0.75,
    "evidence_tier":  1,
    "complexity":     "medium",
    "description":    "SPY/TLT/GLD/DBC weighted to equal 63-day vol contribution, monthly rebalance",
    "reference":      "Bridgewater All-Weather concept",
}

STRATEGY_NAME = "risk_parity_4etf"
_UNIVERSE = ["SPY", "TLT", "GLD", "DBC"]
_VOL_WINDOW = 63


def _vol(bar_list: list[dict]) -> float | None:
    if len(bar_list) < _VOL_WINDOW + 1:
        return None
    closes = [float(b.get("c", 1)) for b in bar_list]
    returns = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(-_VOL_WINDOW, 0)]
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / len(returns)
    return math.sqrt(variance * 252)  # annualized


def _risk_parity_weights(vols: dict[str, float]) -> dict[str, float]:
    """Inverse-vol weights normalized to sum to 1."""
    inv_vols = {sym: 1.0 / v for sym, v in vols.items() if v and v > 0}
    total = sum(inv_vols.values())
    if total <= 0:
        n = len(inv_vols)
        return {sym: 1.0 / n for sym in inv_vols}
    return {sym: iv / total for sym, iv in inv_vols.items()}


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    # Only fire on the first trading day of each month
    today = datetime.utcnow()
    if today.day > 5:
        return []

    vols: dict[str, float] = {}
    for symbol in _UNIVERSE:
        bar_list = bars.get(symbol, [])
        v = _vol(bar_list) if bar_list else None
        if v is not None:
            vols[symbol] = v

    if len(vols) < 2:
        return []

    weights = _risk_parity_weights(vols)
    out: List[Signal] = []

    for symbol, weight in weights.items():
        bar_list = bars.get(symbol, [])
        if not bar_list:
            continue
        out.append(Signal(
            symbol=symbol, side="rebalance", confidence=0.70, size_hint=weight,
            reason=f"Risk parity: {symbol} target weight {weight:.1%} (vol={vols.get(symbol, 0):.1%})",
            strategy=STRATEGY_NAME,
        ))

    return out
