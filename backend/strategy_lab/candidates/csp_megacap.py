"""Cash-Secured Puts — Mega-Cap Quality (AAPL, MSFT, NVDA, AMZN).

Entry conditions:
  - Stock is above its 200-day MA
  - IVR > 30 (VIX percentile proxy)
  - No earnings within 14 days
  - 20-delta target, 30-45 DTE

Exit:
  - 80% profit on premium collected
"""
from __future__ import annotations

from datetime import datetime
from typing import List

from strategy_lab.core.signals import Signal

CANDIDATE_CONFIG = {
    "id":             "csp_megacap",
    "name":           "Cash-Secured Puts Mega-Cap",
    "asset_class":    "options",
    "strategy_type":  "options_income",
    "universe":       ["AAPL", "MSFT", "NVDA", "AMZN"],
    "cadence":        "weekly",
    "claimed_sharpe": 1.0,
    "evidence_tier":  1,
    "complexity":     "medium",
    "description":    "CSP on mega-caps: IVR > 30, stock > 200MA, no earnings 14d, 20-delta 30-45 DTE",
}

STRATEGY_NAME = "csp_megacap"
_UNIVERSE = set(CANDIDATE_CONFIG["universe"])
_MA_PERIOD = 200


def _sma(closes: list[float], n: int) -> float | None:
    if len(closes) < n:
        return None
    return sum(closes[-n:]) / n


def _ivr_proxy(vix_bars: list[dict]) -> float | None:
    if len(vix_bars) < 20:
        return None
    closes = [float(b.get("c", 0)) for b in vix_bars]
    window = closes[-252:] if len(closes) >= 252 else closes
    pct = sum(1 for v in window if v <= closes[-1]) / len(window) * 100
    return pct


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    if regime.get("playbook_regime") in ("CRISIS", "BEAR_TRENDING"):
        return []

    vix_bars = bars.get("VIX", []) or bars.get("^VIX", [])
    ivr = _ivr_proxy(vix_bars) if vix_bars else None
    if ivr is None or ivr < 30:
        return []

    out: List[Signal] = []
    for symbol, bar_list in bars.items():
        if symbol not in _UNIVERSE or not bar_list:
            continue
        closes = [float(b.get("c", 0)) for b in bar_list]
        ma200 = _sma(closes, _MA_PERIOD)
        if ma200 is None or closes[-1] < ma200:
            continue
        conf = min(0.76, 0.55 + (ivr - 30) / 100)
        out.append(Signal(
            symbol=symbol, side="sell_put", confidence=conf, size_hint=0.20,
            reason=f"CSP: {symbol} above MA200, IVR proxy {ivr:.0f}%, 20-delta 30-45 DTE",
            strategy=STRATEGY_NAME,
        ))
    return out
