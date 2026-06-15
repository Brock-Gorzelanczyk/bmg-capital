"""Short Strangle 45 DTE — sell 16-delta call + put on liquid ETFs when IVR > 50."""
from __future__ import annotations

import logging
from typing import List

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

CANDIDATE_CONFIG = {
    "id":             "options_short_strangle_45d",
    "name":           "Short Strangle 45 DTE",
    "asset_class":    "options",
    "strategy_type":  "options_income",
    "universe":       ["SPY", "QQQ", "IWM", "EEM", "GLD", "TLT"],
    "cadence":        "daily",
    "claimed_sharpe": 1.3,
    "evidence_tier":  2,
    "complexity":     "medium",
    "description":    "Sell 16-delta strangle on 6 liquid ETFs when IVR proxy > 50 and market is range-bound",
    "risk_per_trade_pct": 0.03,
    "paper_only":     True,
    "data_source":    "Alpaca options chain (paid tier) or synthetic via Black-Scholes",
    "exit_rules":     "50% credit captured | 21 DTE time stop | short strike breach → close",
}
STRATEGY_NAME = "options_short_strangle_45d"

_IVR_THRESHOLD   = 50.0
_RANGE_THRESHOLD = 0.10   # 20-day price range < 10% = range-bound
_TARGET_DELTA    = 0.16
_DTE_TARGET      = 45


def _ivr_proxy(bars: dict) -> float | None:
    """VIX percentile over trailing 252 days as IVR proxy."""
    vix_bars = bars.get("VIX", []) or bars.get("^VIX", [])
    if len(vix_bars) < 20:
        return None
    closes = [float(b.get("c", 0)) for b in vix_bars]
    window = closes[-252:] if len(closes) >= 252 else closes
    current = closes[-1]
    return sum(1 for v in window if v <= current) / len(window) * 100


def _is_range_bound(closes: list[float], window: int = 20) -> bool:
    if len(closes) < window:
        return False
    hi = max(closes[-window:])
    lo = min(closes[-window:])
    rng = (hi - lo) / lo if lo > 0 else 1.0
    return rng < _RANGE_THRESHOLD


def _signals_for(symbol: str, sym_bars: list[dict], ivr: float) -> list[Signal]:
    if len(sym_bars) < 20:
        return []
    closes = [float(b.get("c", 0)) for b in sym_bars]
    if not _is_range_bound(closes):
        return []
    price = closes[-1]
    rng_pct = (max(closes[-20:]) - min(closes[-20:])) / min(closes[-20:]) * 100

    confidence = min(0.85, 0.55 + (ivr - _IVR_THRESHOLD) / 100)
    return [Signal(
        symbol=symbol,
        side="sell",
        confidence=round(confidence, 3),
        size_hint=0.03,
        reason=(
            f"Short strangle 45 DTE — IVR proxy={ivr:.1f}% > {_IVR_THRESHOLD}, "
            f"20d range={rng_pct:.1f}% (range-bound). "
            f"Target: sell {int(_TARGET_DELTA*100)}-delta call+put ~{_DTE_TARGET} DTE. "
            f"Exit: 50% credit | 21 DTE | strike breach. "
            f"Underlying price={price:.2f}. paper_only=True"
        ),
        strategy=STRATEGY_NAME,
    )]


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    if regime.get("playbook_regime") == "CRISIS" or regime.get("vix_regime") == "panic":
        return []

    ivr = _ivr_proxy(bars)
    if ivr is None or ivr < _IVR_THRESHOLD:
        return []

    universe = profile_config.get("universe", {}).get("symbols", list(CANDIDATE_CONFIG["universe"]))
    out: List[Signal] = []
    for symbol in universe:
        sym_bars = bars.get(symbol, [])
        if sym_bars:
            out.extend(_signals_for(symbol, sym_bars, ivr))
    return out


def generate_signal(symbol: str, closes: list[float], **kwargs) -> Signal | None:
    """Legacy shim."""
    fake_bars = {symbol: [{"c": c, "h": c, "l": c, "o": c, "v": 0} for c in closes]}
    sigs = generate_signals(fake_bars, {}, {})
    return sigs[0] if sigs else None
