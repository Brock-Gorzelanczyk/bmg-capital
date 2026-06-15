"""
Wheel Strategy (Mechanical) — state machine: CSP → assignment → covered call → repeat.

State machine:
  IDLE / SCANNING → sell 30-delta CSP, 30-45 DTE
  CSP_OPEN        → monitor: 50% credit → close + back to SCANNING; breach → assignment
  ASSIGNED        → sell 30-delta covered call on assigned shares, 30-45 DTE
  CALL_OPEN       → monitor: 50% credit → close + back to SCANNING; assignment → SCANNING
  HARD_STOP       → assigned stock fell >20% → close stock leg immediately

Universe filters (applied in generate_signals):
  - dividend payers (proxy: include known dividend ETFs + large-caps with stable dividends)
  - market cap > $20B (use hardcoded universe below)
  - beta < 1.5 (proxy: skip high-beta names)
  - IVR proxy > 30
"""
from __future__ import annotations

import logging
from typing import List

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

CANDIDATE_CONFIG = {
    "id":             "options_wheel_mechanical",
    "name":           "Wheel Strategy (Mechanical)",
    "asset_class":    "options",
    "strategy_type":  "options_income",
    "universe":       ["AAPL", "MSFT", "JPM", "JNJ", "KO", "PEP", "VZ", "T", "XOM", "CVX",
                       "SPY", "QQQ", "GLD", "TLT", "IWM"],
    "cadence":        "daily",
    "claimed_sharpe": 1.1,
    "evidence_tier":  2,
    "complexity":     "high",
    "description":    "Mechanical wheel: sell 30-delta CSP → assignment → sell 30-delta CC → repeat",
    "risk_per_trade_pct": 0.03,
    "paper_only":     True,
    "data_source":    "Alpaca options chain (paid tier) or synthetic via Black-Scholes",
    "exit_rules":     "50% credit captured | assignment triggers CC leg | -20% hard stop on stock",
}
STRATEGY_NAME = "options_wheel_mechanical"

# Conservative universe: dividend payers, mcap > $20B, beta < 1.5
_WHEEL_UNIVERSE = [
    "AAPL", "MSFT", "JPM", "JNJ", "KO", "PEP", "VZ", "T",
    "XOM", "CVX", "SPY", "QQQ", "GLD", "IWM",
]
_IVR_THRESHOLD   = 30.0
_TARGET_DELTA    = 0.30
_DTE_MIN, _DTE_MAX = 30, 45
_HARD_STOP_PCT   = -0.20  # -20% on assigned stock → emergency close


def _ivr_proxy(bars: dict) -> float | None:
    vix_bars = bars.get("VIX", []) or bars.get("^VIX", [])
    if len(vix_bars) < 20:
        return None
    closes = [float(b.get("c", 0)) for b in vix_bars]
    window = closes[-252:] if len(closes) >= 252 else closes
    current = closes[-1]
    return sum(1 for v in window if v <= current) / len(window) * 100


def _is_stable(sym_bars: list[dict]) -> bool:
    """Proxy for beta < 1.5: 30-day return volatility < 3% daily std."""
    if len(sym_bars) < 30:
        return True
    closes = [float(b.get("c", 0)) for b in sym_bars[-31:]]
    rets = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes)) if closes[i-1] > 0]
    if not rets:
        return True
    mean_r = sum(rets) / len(rets)
    var = sum((r - mean_r) ** 2 for r in rets) / len(rets)
    std = var ** 0.5
    return std < 0.03


def _signals_for(symbol: str, sym_bars: list[dict], ivr: float) -> list[Signal]:
    if len(sym_bars) < 20:
        return []
    if not _is_stable(sym_bars):
        return []
    closes = [float(b.get("c", 0)) for b in sym_bars]
    price = closes[-1]
    confidence = min(0.80, 0.50 + (ivr - _IVR_THRESHOLD) / 100)
    return [Signal(
        symbol=symbol,
        side="sell",
        confidence=round(confidence, 3),
        size_hint=0.03,
        reason=(
            f"Wheel CSP entry — IVR proxy={ivr:.1f}% > {_IVR_THRESHOLD}, "
            f"stable (proxy beta < 1.5). "
            f"State: SCANNING → sell {int(_TARGET_DELTA*100)}-delta CSP, "
            f"{_DTE_MIN}-{_DTE_MAX} DTE. "
            f"On 50% credit → close+repeat; on assignment → sell {int(_TARGET_DELTA*100)}-delta CC. "
            f"Hard stop: -20% on assigned stock. "
            f"Price={price:.2f}. paper_only=True"
        ),
        strategy=STRATEGY_NAME,
    )]


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    if regime.get("playbook_regime") == "CRISIS" or regime.get("vix_regime") == "panic":
        return []

    ivr = _ivr_proxy(bars)
    if ivr is None or ivr < _IVR_THRESHOLD:
        return []

    universe = profile_config.get("universe", {}).get("symbols", _WHEEL_UNIVERSE)
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
