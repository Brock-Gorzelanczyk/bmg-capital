"""Iron Condor SPY — sell 16-delta condor with 10-wide wings when IVR > 30 and ATR contracting."""
from __future__ import annotations

import logging
from typing import List

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

CANDIDATE_CONFIG = {
    "id":             "options_iron_condor_spy",
    "name":           "Iron Condor SPY",
    "asset_class":    "options",
    "strategy_type":  "options_income",
    "universe":       ["SPY"],
    "cadence":        "daily",
    "claimed_sharpe": 1.2,
    "evidence_tier":  2,
    "complexity":     "medium",
    "description":    "SPY-only IC — sell 16-delta strangle, buy 10-wide wings, 45 DTE, IVR > 30 + ATR contracting",
    "risk_per_trade_pct": 0.02,
    "paper_only":     True,
    "data_source":    "Alpaca options chain (paid tier) or synthetic via Black-Scholes",
    "exit_rules":     "50% credit captured | 21 DTE time stop | short strike breach → close",
}
STRATEGY_NAME = "options_iron_condor_spy"

_IVR_THRESHOLD = 30.0
_WING_WIDTH    = 10.0
_TARGET_DELTA  = 0.16
_DTE_TARGET    = 45


def _ivr_proxy(bars: dict) -> float | None:
    vix_bars = bars.get("VIX", []) or bars.get("^VIX", [])
    if len(vix_bars) < 20:
        return None
    closes = [float(b.get("c", 0)) for b in vix_bars]
    window = closes[-252:] if len(closes) >= 252 else closes
    current = closes[-1]
    return sum(1 for v in window if v <= current) / len(window) * 100


def _atr(bars: list[dict], period: int) -> float:
    if len(bars) < period + 1:
        return 0.0
    trs = []
    for i in range(-period, 0):
        h = float(bars[i].get("h", 0))
        l = float(bars[i].get("l", 0))
        pc = float(bars[i - 1].get("c", 0))
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / len(trs) if trs else 0.0


def _atr_contracting(bars: list[dict]) -> bool:
    """5-day ATR is below 20-day ATR — volatility compressing."""
    atr5  = _atr(bars, 5)
    atr20 = _atr(bars, 20)
    return atr5 < atr20 and atr20 > 0


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    if regime.get("playbook_regime") == "CRISIS" or regime.get("vix_regime") == "panic":
        return []

    ivr = _ivr_proxy(bars)
    if ivr is None or ivr < _IVR_THRESHOLD:
        return []

    spy_bars = bars.get("SPY", [])
    if len(spy_bars) < 25:
        return []

    if not _atr_contracting(spy_bars):
        return []

    price = float(spy_bars[-1].get("c", 0))
    atr5  = _atr(spy_bars, 5)
    atr20 = _atr(spy_bars, 20)
    confidence = min(0.82, 0.50 + (ivr - _IVR_THRESHOLD) / 100)

    return [Signal(
        symbol="SPY",
        side="sell",
        confidence=round(confidence, 3),
        size_hint=0.02,
        reason=(
            f"Iron Condor SPY 45 DTE — IVR proxy={ivr:.1f}% > {_IVR_THRESHOLD}, "
            f"ATR5={atr5:.2f} < ATR20={atr20:.2f} (contracting). "
            f"Target: sell {int(_TARGET_DELTA*100)}-delta strangle, {int(_WING_WIDTH)}-wide wings, ~{_DTE_TARGET} DTE. "
            f"Exit: 50% credit | 21 DTE | strike breach. "
            f"SPY={price:.2f}. paper_only=True"
        ),
        strategy=STRATEGY_NAME,
    )]


def generate_signal(symbol: str, closes: list[float], **kwargs) -> Signal | None:
    fake_bars = {"SPY": [{"c": c, "h": c, "l": c, "o": c, "v": 0} for c in closes]}
    sigs = generate_signals(fake_bars, {}, {})
    return sigs[0] if sigs else None
