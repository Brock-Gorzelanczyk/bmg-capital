"""BTC/ETH 50/200 MA Cross — simple trend following on crypto.

Long when 50-day MA > 200-day MA (golden cross).
Exit to cash when 50-day MA < 200-day MA (death cross).
"""
from __future__ import annotations

from typing import List

from strategy_lab.core.signals import Signal

CANDIDATE_CONFIG = {
    "id":             "btc_eth_50_200_cross",
    "name":           "BTC/ETH 50/200 Cross",
    "asset_class":    "crypto",
    "strategy_type":  "trend_following",
    "universe":       ["BTC/USD", "ETH/USD"],
    "cadence":        "daily",
    "claimed_sharpe": 0.80,
    "evidence_tier":  1,
    "complexity":     "low",
    "description":    "Long BTC/ETH when 50d > 200d MA (golden cross), cash otherwise",
}

STRATEGY_NAME = "btc_eth_50_200_cross"
_UNIVERSE = set(CANDIDATE_CONFIG["universe"])


def _sma(closes: list[float], n: int) -> float | None:
    if len(closes) < n:
        return None
    return sum(closes[-n:]) / n


def _was_death_cross(closes: list[float]) -> bool:
    """True if previous bar had 50MA < 200MA."""
    if len(closes) < 201:
        return False
    prev = closes[:-1]
    return (_sma(prev, 50) or 0) < (_sma(prev, 200) or 0)


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    out: List[Signal] = []
    for symbol, bar_list in bars.items():
        if symbol not in _UNIVERSE or not bar_list:
            continue
        closes = [float(b.get("c", 0)) for b in bar_list]
        if len(closes) < 200:
            continue
        ma50  = _sma(closes, 50)
        ma200 = _sma(closes, 200)
        if ma50 is None or ma200 is None:
            continue

        golden = ma50 > ma200
        prev_death = _was_death_cross(closes)

        if golden and prev_death:
            # Fresh golden cross — buy signal
            out.append(Signal(
                symbol=symbol, side="buy", confidence=0.72, size_hint=0.50,
                reason=f"{symbol}: golden cross 50MA({ma50:.0f}) > 200MA({ma200:.0f})",
                strategy=STRATEGY_NAME,
            ))
        elif not golden and not prev_death:
            # Fresh death cross — exit signal
            out.append(Signal(
                symbol=symbol, side="sell", confidence=0.72, size_hint=1.0,
                reason=f"{symbol}: death cross 50MA({ma50:.0f}) < 200MA({ma200:.0f}) — exit to cash",
                strategy=STRATEGY_NAME,
            ))
    return out
