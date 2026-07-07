"""Faber GTAA — 10-month SMA rule across 5 asset-class ETFs.

Reference: Faber 2007, "A Quantitative Approach to Tactical Asset
Allocation" (SSRN 962461). Published Sharpe 1.19, CAGR 7.6%,
max drawdown -16.8% on the 5-asset ETF version 1972-2012.

Rule (per ETF, monthly):
  IF month_end_close > 10-month simple moving average of month_end closes:
    → hold the ETF (BUY signal if not currently held)
  ELSE:
    → go to cash (SELL signal if currently held)

The 5 canonical Faber asset classes, mapped to Alpaca-tradeable ETFs:
  VTI    US equities (or SPY)
  EFA    Foreign developed equities
  VNQ    US real estate
  DBC    Commodities (or GSG)
  IEF    US 7-10y Treasuries

Simplifications for BMG framework:
  - Uses daily closes (not month-end); trades the signal transition
    on any daily bar. This produces slightly more signals than pure
    monthly, but the 10-month window smooths the trigger heavily.
  - Long-only. Cash means no position (not short).
  - Confidence = distance from SMA / 10% (capped at 0.9).

Data: daily bars for VTI, EFA, VNQ, DBC, IEF from the runner's
bar cache.
"""
from __future__ import annotations

import logging
from statistics import mean
from typing import List

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "faber_gtaa"
SMA_WINDOW_DAYS = 210  # ~10 months of trading days
MIN_BARS_REQUIRED = 210


def _faber_signal_for_symbol(symbol: str, closes: list[float]) -> List[Signal]:
    if len(closes) < MIN_BARS_REQUIRED:
        return []

    sma = mean(closes[-SMA_WINDOW_DAYS:])
    last_close = closes[-1]

    if sma <= 0:
        return []

    distance_pct = (last_close - sma) / sma

    if last_close > sma:
        # BUY / hold — trend is up
        confidence = min(0.9, 0.55 + abs(distance_pct) * 4.0)
        return [Signal(
            symbol=symbol,
            side="buy",
            confidence=round(confidence, 4),
            size_hint=0.2,  # 20% of allocation per ETF (5 ETFs = 100% invested when all trending)
            reason=(
                f"faber_gtaa: close={last_close:.2f} > SMA210={sma:.2f} "
                f"(dist={distance_pct:.2%}). Long trend."
            ),
            strategy=STRATEGY_NAME,
        )]
    else:
        # SELL / cash — trend is down
        confidence = min(0.9, 0.55 + abs(distance_pct) * 4.0)
        return [Signal(
            symbol=symbol,
            side="sell",
            confidence=round(confidence, 4),
            size_hint=0.2,
            reason=(
                f"faber_gtaa: close={last_close:.2f} <= SMA210={sma:.2f} "
                f"(dist={distance_pct:.2%}). Exit to cash."
            ),
            strategy=STRATEGY_NAME,
        )]


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    out: List[Signal] = []
    for symbol, bar_list in bars.items():
        if not bar_list:
            continue
        try:
            closes = [float(b.get("c", 0)) for b in bar_list if b.get("c") is not None]
            out.extend(_faber_signal_for_symbol(symbol, closes))
        except Exception as exc:
            logger.warning("[faber_gtaa] %s: signal gen failed: %s", symbol, exc)
    return out
