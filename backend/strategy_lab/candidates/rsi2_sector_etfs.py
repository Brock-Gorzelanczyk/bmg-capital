"""RSI-2 on Sector ETFs — Connors & Alvarez applied to the SPDR sector universe.

Buy when RSI(2) < 10 AND sector ETF is above its 200-day MA.
Exit when RSI(2) > 70 or after 5 trading days.
Universe: XLK, XLF, XLE, XLV, XLI, XLP, XLY, XLU, XLB, XLRE, XLC
"""
from __future__ import annotations

from typing import List, Optional

from strategy_lab.core.signals import Signal

CANDIDATE_CONFIG = {
    "id":             "rsi2_sector_etfs",
    "name":           "RSI-2 Sector ETFs",
    "asset_class":    "stocks",
    "strategy_type":  "mean_reversion",
    "universe":       ["XLK", "XLF", "XLE", "XLV", "XLI", "XLP", "XLY", "XLU", "XLB", "XLRE", "XLC"],
    "cadence":        "daily",
    "claimed_sharpe": 1.2,
    "evidence_tier":  1,
    "complexity":     "low",
    "description":    "RSI(2) < 10 oversold entry on sector ETFs above 200MA; exit RSI > 70 or 5 days",
    "max_hold_days":  5,
}

STRATEGY_NAME = "rsi2_sector_etfs"
_UNIVERSE = set(CANDIDATE_CONFIG["universe"])
_RSI_PERIOD = 2
_MA_PERIOD = 200
_ENTRY_RSI = 10.0
_EXIT_RSI  = 70.0


def _rsi(closes: list[float]) -> float | None:
    if len(closes) < _RSI_PERIOD + 1:
        return None
    gains, losses = [], []
    for i in range(1, _RSI_PERIOD + 1):
        d = closes[-_RSI_PERIOD + i - 1] - closes[-_RSI_PERIOD + i - 2]
        (gains if d >= 0 else losses).append(abs(d))
    avg_g = sum(gains) / _RSI_PERIOD if gains else 0.0
    avg_l = sum(losses) / _RSI_PERIOD if losses else 0.0
    if avg_l == 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + avg_g / avg_l)


def _sma(closes: list[float], n: int) -> float | None:
    if len(closes) < n:
        return None
    return sum(closes[-n:]) / n


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    out: List[Signal] = []
    for symbol, bar_list in bars.items():
        if symbol not in _UNIVERSE or not bar_list:
            continue
        closes = [float(b.get("c", 0)) for b in bar_list]
        if len(closes) < _MA_PERIOD + 1:
            continue
        ma200 = _sma(closes, _MA_PERIOD)
        rsi = _rsi(closes)
        if ma200 is None or rsi is None:
            continue
        price = closes[-1]
        if price > ma200 and rsi < _ENTRY_RSI:
            depth = _ENTRY_RSI - rsi
            conf = min(0.82, 0.60 + depth * 0.015)
            out.append(Signal(
                symbol=symbol, side="buy", confidence=conf, size_hint=0.60,
                reason=f"RSI2={rsi:.1f} oversold in {symbol}, above MA200",
                strategy=STRATEGY_NAME,
            ))
        elif rsi > _EXIT_RSI:
            out.append(Signal(
                symbol=symbol, side="sell", confidence=0.70, size_hint=1.0,
                reason=f"RSI2={rsi:.1f} overbought exit",
                strategy=STRATEGY_NAME,
            ))
    return out
