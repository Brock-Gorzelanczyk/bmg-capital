"""Iron Condor — SPX/SPY 45 DTE options income.

Entry conditions:
  - IVR > 50 (proxy: VIX percentile vs 252-day range if no IV history)
  - Skip FOMC, CPI, NFP calendar weeks
  - 16-delta short strikes, 5-delta long strikes (wings)
  - 45 DTE target

Exit:
  - 50% profit on premium collected
  - 21 DTE time stop

Risk: max 5% of bot equity per condor.
"""
from __future__ import annotations

from datetime import datetime
from typing import List

from strategy_lab.core.signals import Signal

CANDIDATE_CONFIG = {
    "id":             "iron_condor_45dte",
    "name":           "Iron Condor 45 DTE",
    "asset_class":    "options",
    "strategy_type":  "options_income",
    "universe":       ["SPY"],
    "cadence":        "weekly",
    "claimed_sharpe": 1.1,
    "evidence_tier":  1,
    "complexity":     "medium",
    "description":    "SPY 45 DTE iron condor, 16/5 delta, IVR > 50, skip event weeks",
    "risk_per_trade_pct": 0.05,
}

STRATEGY_NAME = "iron_condor_45dte"

# Weeks with high-impact macro events — skip condor entries
_SKIP_MONTHS_DAYS: list[tuple[int, int]] = []  # populated by calendar integration


def _ivr_proxy(vix_bars: list[dict]) -> float | None:
    """VIX percentile over trailing 252 days as IVR proxy."""
    if len(vix_bars) < 20:
        return None
    closes = [float(b.get("c", 0)) for b in vix_bars]
    window = closes[-252:] if len(closes) >= 252 else closes
    current = closes[-1]
    pct = sum(1 for v in window if v <= current) / len(window) * 100
    return pct


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    # Crisis regime — never sell premium
    if regime.get("playbook_regime") == "CRISIS":
        return []

    vix_bars = bars.get("VIX", []) or bars.get("^VIX", [])
    ivr = _ivr_proxy(vix_bars) if vix_bars else None

    if ivr is None or ivr < 50:
        return []

    # Check for event week (stub — full implementation requires macro calendar)
    today = datetime.utcnow()
    # Skip week if FOMC/CPI/NFP is within this week (simplified: skip 3rd week of month)
    if 14 <= today.day <= 22:
        return []

    # Signal: open condor on SPY
    conf = min(0.78, 0.55 + (ivr - 50) / 100)
    return [Signal(
        symbol="SPY", side="sell_condor", confidence=conf, size_hint=0.05,
        reason=f"IVR proxy {ivr:.0f}% > 50 — open 45 DTE iron condor, 16/5 delta",
        strategy=STRATEGY_NAME,
    )]
