"""Crypto DCA — dumb weekly accumulation of BTC and ETH.

Zero technical filters. Every scan window (weekly Monday 10 AM UTC per the
crypto_dca_btc_eth profile) this fires a buy signal on both symbols. The
profile-level cooldown_minutes keeps it from double-buying on retries.

This is the "always-in" baseline — its role is to give the fund guaranteed
BTC/ETH exposure and to provide a clean benchmark to measure the discretionary
bots against ("how much of Quant Aggressive's alpha would we get by just
buying-and-holding?"). No strategy alpha claimed.
"""
from __future__ import annotations

import json
import logging
from typing import List

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "crypto_dca_weekly"


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    """Always emit a buy on any symbol we have bars for.

    The 'confidence' is deliberately mid-range (0.55) — the DCA thesis is not
    "high conviction, this dip is the bottom" but "we're accumulating steadily
    regardless of the tape." Combined with the profile-level confidence
    threshold of 0.30 this always passes and always executes.
    """
    signals: List[Signal] = []

    # Panic regime — skip. Even DCA shouldn't buy into a full crypto crash
    # (2022 FTX contagion pattern); wait for the next window.
    if regime.get("vix_regime") == "panic":
        return signals

    for symbol, bar_list in bars.items():
        if not bar_list:
            continue
        try:
            spot = float(bar_list[-1].get("c") or bar_list[-1].get("close") or 0)
        except (TypeError, ValueError):
            spot = 0
        if spot <= 0:
            continue
        reason = json.dumps({
            "setup": "dca_weekly",
            "spot": round(spot, 2),
            "sizing": "fixed 4% of allocation per weekly buy",
            "manage": "hold long horizon; no stop; 100% take-profit or 180d hard exit",
        })
        signals.append(Signal(
            symbol=symbol,
            side="buy",
            confidence=0.55,
            size_hint=0.04,
            reason=reason,
            strategy=STRATEGY_NAME,
        ))
    return signals
