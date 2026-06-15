"""
0DTE SPX Iron Condor — entry at 9:35 ET, sell 10-delta condor with 25-point wings.

Entry: 9:35 AM ET only (not an intraday scanner — daily scheduler fires once)
Universe: SPX or XSP (index options, no assignment risk)
Exit: 50% credit | 3:00 PM ET time stop | short strike breach
Size: 0.75% account per trade (high frequency but small size)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, time as dtime
from typing import List
from zoneinfo import ZoneInfo

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")

CANDIDATE_CONFIG = {
    "id":             "options_0dte_spx_condor",
    "name":           "0DTE SPX Iron Condor",
    "asset_class":    "options",
    "strategy_type":  "options_income",
    "universe":       ["SPY"],  # SPX/XSP — using SPY as proxy for bar data
    "cadence":        "35 9 * * 1-5",  # Fire at 9:35 ET on weekdays
    "claimed_sharpe": 0.9,
    "evidence_tier":  2,
    "complexity":     "high",
    "description":    "0DTE SPX iron condor — 10-delta, 25-point wings, entry 9:35 ET, exit by 3 PM",
    "risk_per_trade_pct": 0.0075,
    "paper_only":     True,
    "data_source":    "Alpaca options chain (paid tier) or synthetic via Black-Scholes",
    "exit_rules":     "50% credit | 3:00 PM ET time stop | strike breach → close immediately",
    "caution":        "0DTE gamma risk is extreme near expiry — position size is strictly limited",
}
STRATEGY_NAME = "options_0dte_spx_condor"

_TARGET_DELTA   = 0.10   # 10-delta short strikes
_WING_POINTS    = 25.0   # 25-point wings
_ENTRY_TIME_ET  = dtime(9, 35)
_CUTOFF_TIME_ET = dtime(15, 0)


def _within_entry_window() -> bool:
    """Only enter between 9:35 and 9:50 ET."""
    now_et = datetime.now(ET).time()
    return _ENTRY_TIME_ET <= now_et <= dtime(9, 50)


def _avoid_fomc_cpi_day(now_et: datetime) -> bool:
    """Skip 3rd Wednesday of month (proxy for FOMC/CPI week) — simplified heuristic."""
    if now_et.weekday() == 2 and 14 <= now_et.day <= 22:
        return True
    return False


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    if regime.get("playbook_regime") == "CRISIS" or regime.get("vix_regime") == "panic":
        return []

    now_et = datetime.now(ET)
    if _avoid_fomc_cpi_day(now_et):
        logger.info("[0dte_spx] skipping — likely FOMC/CPI week")
        return []

    if not _within_entry_window():
        logger.debug("[0dte_spx] outside 9:35–9:50 ET entry window")
        return []

    spy_bars = bars.get("SPY", [])
    if not spy_bars:
        return []

    price = float(spy_bars[-1].get("c", 0))
    if price <= 0:
        return []

    # VIX as regime filter — skip if VIX > 30 (too volatile for 0DTE)
    vix_bars = bars.get("VIX", []) or bars.get("^VIX", [])
    if vix_bars:
        vix_now = float(vix_bars[-1].get("c", 0))
        if vix_now > 30:
            logger.info("[0dte_spx] VIX=%.1f > 30 — skipping 0DTE condor", vix_now)
            return []

    confidence = 0.65  # Fixed — 0DTE is probabilistic, not directional

    return [Signal(
        symbol="SPY",  # SPX/XSP proxy — execution layer maps to actual index options
        side="sell",
        confidence=confidence,
        size_hint=0.0075,
        reason=(
            f"0DTE SPX condor — entry window 9:35 ET. "
            f"Target: sell {int(_TARGET_DELTA*100)}-delta call+put, {int(_WING_POINTS)}-pt wings. "
            f"Exit: 50% credit | 3 PM ET | strike breach. "
            f"SPY={price:.2f}. paper_only=True. "
            f"NOTE: execution layer should route to SPX/XSP, not SPY shares."
        ),
        strategy=STRATEGY_NAME,
    )]


def generate_signal(symbol: str, closes: list[float], **kwargs) -> Signal | None:
    sigs = generate_signals({"SPY": [{"c": c, "h": c, "l": c, "o": c, "v": 0} for c in closes]}, {}, {})
    return sigs[0] if sigs else None
