"""
Post-Earnings Iron Condor — sell IC after earnings event collapses IV crush.

Entry: earnings reported in last 24h AND IVR was > 50 pre-event (proxy: current IVR still > 35 post-crush)
Universe: NVDA, TSLA, META, NFLX, COIN, AMD, MU
Target: sell 16-delta IC, 10-wide wings, 30 DTE
Exit: 25% credit captured | 21 DTE

Rationale: IV crush post-earnings compresses option prices rapidly —
selling the remaining IV after the event captures residual premium.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import List

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

CANDIDATE_CONFIG = {
    "id":             "options_post_earnings_ic",
    "name":           "Post-Earnings IV Crush IC",
    "asset_class":    "options",
    "strategy_type":  "options_income",
    "universe":       ["NVDA", "TSLA", "META", "NFLX", "COIN", "AMD", "MU"],
    "cadence":        "daily",
    "claimed_sharpe": 1.4,
    "evidence_tier":  2,
    "complexity":     "medium",
    "description":    "Sell 16-delta IC post-earnings IV crush, 30 DTE, 25% profit target",
    "risk_per_trade_pct": 0.02,
    "paper_only":     True,
    "data_source":    "Alpaca options chain (paid tier) or synthetic via Black-Scholes",
    "exit_rules":     "25% credit captured | 21 DTE time stop",
    "edge":           "IV mean-reverts rapidly post-earnings — residual premium decays fast",
}
STRATEGY_NAME = "options_post_earnings_ic"

_EARNINGS_UNIVERSE = ["NVDA", "TSLA", "META", "NFLX", "COIN", "AMD", "MU"]
_PRE_EVENT_IVR_MIN = 50.0  # IVR must have been > 50 pre-event (proxy: vol expansion)
_POST_IVR_MIN      = 35.0  # post-crush IVR still elevated (proxy: worthwhile premium)
_TARGET_DELTA      = 0.16
_WING_WIDTH        = 10.0
_DTE_TARGET        = 30
_PROFIT_TARGET_PCT = 25.0  # 25% credit


def _ivr_proxy(bars: dict) -> float | None:
    vix_bars = bars.get("VIX", []) or bars.get("^VIX", [])
    if len(vix_bars) < 20:
        return None
    closes = [float(b.get("c", 0)) for b in vix_bars]
    window = closes[-252:] if len(closes) >= 252 else closes
    current = closes[-1]
    return sum(1 for v in window if v <= current) / len(window) * 100


def _had_earnings_move(sym_bars: list[dict]) -> bool:
    """
    Proxy for 'earnings in last 24h': look for a single-day gap > 3% on above-avg volume.
    This is a simplified proxy — real implementation should use earnings calendar API.
    """
    if len(sym_bars) < 3:
        return False
    # Check if yesterday's open-to-open gap exceeded 3%
    prev_c = float(sym_bars[-2].get("c", 0))
    curr_o = float(sym_bars[-1].get("o", 0))
    if prev_c <= 0 or curr_o <= 0:
        return False
    gap_pct = abs(curr_o - prev_c) / prev_c
    # Volume spike proxy
    vols = [float(b.get("v", 0)) for b in sym_bars[-20:] if float(b.get("v", 0)) > 0]
    avg_vol = sum(vols[:-1]) / len(vols[:-1]) if len(vols) > 1 else 0
    curr_vol = float(sym_bars[-1].get("v", 0))
    vol_spike = curr_vol > avg_vol * 1.5 if avg_vol > 0 else False
    return gap_pct > 0.03 and vol_spike


def _realized_vol_spike(sym_bars: list[dict]) -> bool:
    """
    Check if the symbol had a volatility spike recently (proxy for high pre-earnings IVR).
    5-day realized vol > 20-day realized vol by > 50% → likely had an event.
    """
    if len(sym_bars) < 22:
        return False
    closes = [float(b.get("c", 0)) for b in sym_bars]
    rets = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes)) if closes[i-1] > 0]
    if len(rets) < 21:
        return False
    rv5  = (sum(r**2 for r in rets[-5:]) / 5) ** 0.5 * (252 ** 0.5)
    rv20 = (sum(r**2 for r in rets[-20:]) / 20) ** 0.5 * (252 ** 0.5)
    return rv5 > rv20 * 1.5


def _signals_for(symbol: str, sym_bars: list[dict], ivr: float) -> list[Signal]:
    if len(sym_bars) < 22:
        return []
    if not _had_earnings_move(sym_bars):
        return []
    if not _realized_vol_spike(sym_bars):
        return []
    if ivr < _POST_IVR_MIN:
        return []
    price = float(sym_bars[-1].get("c", 0))
    confidence = min(0.78, 0.55 + (ivr - _POST_IVR_MIN) / 100)
    return [Signal(
        symbol=symbol,
        side="sell",
        confidence=round(confidence, 3),
        size_hint=0.02,
        reason=(
            f"Post-earnings IC — IVR proxy={ivr:.1f}% (post-crush), "
            f"earnings gap detected (proxy). "
            f"Target: sell {int(_TARGET_DELTA*100)}-delta IC, {int(_WING_WIDTH)}-wide wings, ~{_DTE_TARGET} DTE. "
            f"Exit: {_PROFIT_TARGET_PCT:.0f}% credit | 21 DTE. "
            f"Price={price:.2f}. paper_only=True. "
            f"NOTE: Confirm earnings date via calendar API before live execution."
        ),
        strategy=STRATEGY_NAME,
    )]


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    if regime.get("playbook_regime") == "CRISIS" or regime.get("vix_regime") == "panic":
        return []

    ivr = _ivr_proxy(bars)
    if ivr is None or ivr < _POST_IVR_MIN:
        return []

    _u = profile_config.get("universe", _EARNINGS_UNIVERSE)
    universe = _u.get("symbols", _EARNINGS_UNIVERSE) if isinstance(_u, dict) else list(_u)
    out: List[Signal] = []
    for symbol in universe:
        sym_bars = bars.get(symbol, [])
        if sym_bars:
            out.extend(_signals_for(symbol, sym_bars, ivr))
    return out


def generate_signal(symbol: str, closes: list[float], **kwargs) -> Signal | None:
    fake_bars = {symbol: [{"c": c, "h": c, "l": c, "o": c, "v": 0} for c in closes]}
    sigs = generate_signals(fake_bars, {}, {})
    return sigs[0] if sigs else None
