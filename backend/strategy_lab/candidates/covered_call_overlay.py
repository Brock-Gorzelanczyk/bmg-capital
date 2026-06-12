"""Covered Call Overlay — writes calls against THIS BOT's long stock positions only.

IMPORTANT: This bot buys the stock itself and writes calls against those shares.
It does NOT touch any other bot's positions or the live portfolio.

Entry: buys stock (quality/value screen), then writes 20-25 delta calls 30-45 DTE.
Roll at 21 DTE. Exit: called away or stock drops below 200MA (sell stock).
Universe: SPY for simplicity (broad market exposure with covered call income layer).
"""
from __future__ import annotations

from typing import List

from strategy_lab.core.signals import Signal

CANDIDATE_CONFIG = {
    "id":             "covered_call_overlay",
    "name":           "Covered Call Overlay",
    "asset_class":    "options",
    "strategy_type":  "options_income",
    "universe":       ["SPY", "QQQ", "IWM"],
    "cadence":        "weekly",
    "claimed_sharpe": 0.85,
    "evidence_tier":  1,
    "complexity":     "medium",
    "description":    "Buys ETF, writes 20-25 delta calls 30-45 DTE. Rolls at 21 DTE. Independent positions only.",
    "note":           "Bot buys its own stock; does NOT interact with other bots' positions",
}

STRATEGY_NAME = "covered_call_overlay"
_UNIVERSE = set(CANDIDATE_CONFIG["universe"])
_MA_PERIOD = 50


def _sma(closes: list[float], n: int) -> float | None:
    if len(closes) < n:
        return None
    return sum(closes[-n:]) / n


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    if regime.get("playbook_regime") == "CRISIS":
        return []

    out: List[Signal] = []
    for symbol, bar_list in bars.items():
        if symbol not in _UNIVERSE or not bar_list:
            continue
        closes = [float(b.get("c", 0)) for b in bar_list]
        ma50 = _sma(closes, _MA_PERIOD)
        if ma50 is None:
            continue
        price = closes[-1]
        if price > ma50:
            out.append(Signal(
                symbol=symbol, side="buy_write", confidence=0.68, size_hint=0.33,
                reason=f"CC overlay: {symbol} above MA50 — buy + write 20-25 delta call 30-45 DTE",
                strategy=STRATEGY_NAME,
            ))
    return out
