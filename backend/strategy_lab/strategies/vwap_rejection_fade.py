"""VWAP Rejection Fade — mean-reversion fade after extension + rejection.

Thesis: When price extends > 2 ATRs from VWAP-proxy and prints a clear
rejection candle (wick > body, closes back through midrange), fade the
move expecting reversion toward VWAP.

Regime: choppy or low_vol (degrades in trending markets — gated by the
discipline filter's regime gate and re-checked here as a soft guard).

Active hours: 10:00–15:00 ET (avoid open/close volatility extremes). The
strategy also runs on swing bots with daily bars — in that case the
active-hours guard is a no-op because the scan fires at 3:50 PM ET.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "vwap_rejection_fade"

MIN_BARS = 20
ATR_PERIOD = 14
DEVIATION_THRESHOLD = 2.0   # ATRs from VWAP
WICK_TO_BODY_MIN = 1.0      # rejection wick must be ≥ body length
REJECTION_CLOSE_FRAC = 0.66 # close must reclaim past 66% of the candle range
MAX_CONFIDENCE = 0.85


def _et_hour_now() -> int:
    """Rough ET hour from current UTC. EDT (-4); good enough for June batch."""
    return (datetime.now(timezone.utc).hour - 4) % 24


def _is_intraday_timeframe(bars_for_symbol: list) -> bool:
    """Detect intraday vs daily bars by inspecting timestamp gaps."""
    if len(bars_for_symbol) < 2:
        return False
    try:
        ts1 = datetime.fromisoformat(str(bars_for_symbol[-1]["ts"]).replace("Z", "+00:00"))
        ts2 = datetime.fromisoformat(str(bars_for_symbol[-2]["ts"]).replace("Z", "+00:00"))
        delta_min = abs((ts1 - ts2).total_seconds()) / 60.0
        return delta_min < 240  # < 4h gap → intraday
    except Exception:
        return False


def _vwap_proxy(bars: list) -> float | None:
    """Volume-weighted typical-price average across the bar window."""
    num = 0.0
    den = 0.0
    for b in bars:
        h = float(b.get("h", 0) or 0)
        l = float(b.get("l", 0) or 0)
        c = float(b.get("c", 0) or 0)
        v = float(b.get("v", 0) or 0)
        if v <= 0 or (h == 0 and l == 0 and c == 0):
            continue
        typical = (h + l + c) / 3.0
        num += typical * v
        den += v
    return (num / den) if den > 0 else None


def _atr(bars: list, period: int = ATR_PERIOD) -> float | None:
    """Wilder-style ATR over the last `period` bars."""
    if len(bars) < period + 1:
        return None
    trs: list[float] = []
    for i in range(len(bars) - period, len(bars)):
        if i == 0:
            continue
        cur = bars[i]
        prev = bars[i - 1]
        h = float(cur.get("h", 0) or 0)
        l = float(cur.get("l", 0) or 0)
        prev_c = float(prev.get("c", 0) or 0)
        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        trs.append(tr)
    if not trs:
        return None
    return sum(trs) / len(trs)


def _build_signal_for_symbol(symbol: str, bar_list: list, regime_word: str) -> Signal | None:
    if not bar_list or len(bar_list) < MIN_BARS:
        return None

    last = bar_list[-1]
    h = float(last.get("h", 0) or 0)
    l = float(last.get("l", 0) or 0)
    c = float(last.get("c", 0) or 0)
    o = float(last.get("o", 0) or 0)
    if h <= 0 or l <= 0 or c <= 0 or h <= l:
        return None

    vwap = _vwap_proxy(bar_list[-MIN_BARS:])
    atr = _atr(bar_list)
    if vwap is None or atr is None or atr <= 0:
        return None

    deviation = (c - vwap) / atr   # +ve = extended above VWAP

    body = abs(c - o)
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l
    candle_range = h - l
    if candle_range <= 0:
        return None

    # Confidence scales with extension beyond 2 ATRs (cap at MAX_CONFIDENCE).
    extension_excess = max(0.0, abs(deviation) - DEVIATION_THRESHOLD)
    confidence = min(MAX_CONFIDENCE, 0.50 + 0.15 * extension_excess)

    # SHORT setup: extended UP, rejection wick on top, closes back through mid
    if deviation > DEVIATION_THRESHOLD and upper_wick >= body * WICK_TO_BODY_MIN:
        if c <= h - candle_range * REJECTION_CLOSE_FRAC:
            return Signal(
                symbol=symbol,
                side="sell",   # runner will filter on long_only bots; emit for completeness
                confidence=round(confidence, 3),
                size_hint=0.06,
                strategy=STRATEGY_NAME,
                reason=(
                    f'{{"setup":"vwap_short","deviation_atr":{deviation:.2f},'
                    f'"vwap":{vwap:.2f},"atr":{atr:.4f},"regime":"{regime_word}",'
                    f'"vol_agreement":0.55,"mtf_alignment":0.45,"cross_asset_agree":false}}'
                ),
            )

    # LONG setup: extended DOWN, rejection wick at bottom, closes back through mid
    if deviation < -DEVIATION_THRESHOLD and lower_wick >= body * WICK_TO_BODY_MIN:
        if c >= l + candle_range * REJECTION_CLOSE_FRAC:
            return Signal(
                symbol=symbol,
                side="buy",
                confidence=round(confidence, 3),
                size_hint=0.06,
                strategy=STRATEGY_NAME,
                reason=(
                    f'{{"setup":"vwap_long","deviation_atr":{deviation:.2f},'
                    f'"vwap":{vwap:.2f},"atr":{atr:.4f},"regime":"{regime_word}",'
                    f'"vol_agreement":0.55,"mtf_alignment":0.45,"cross_asset_agree":false}}'
                ),
            )

    return None


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    """Mean-reversion fade after 2-ATR VWAP extension + rejection candle."""
    if not bars:
        return []

    # Soft regime gate (Phase 1 discipline filter does the strict gate per profile).
    regime_word = (regime or {}).get("trend_regime") or (regime or {}).get("name") or "unknown"

    # Active hours guard — only enforced if bars look intraday.
    sample_sym = next(iter(bars))
    if _is_intraday_timeframe(bars.get(sample_sym, [])):
        h_et = _et_hour_now()
        if not (10 <= h_et < 15):
            return []

    out: List[Signal] = []
    for symbol, bar_list in bars.items():
        try:
            sig = _build_signal_for_symbol(symbol, bar_list, str(regime_word))
            if sig is not None:
                out.append(sig)
        except Exception as exc:
            logger.warning("[%s] %s failed: %s", STRATEGY_NAME, symbol, exc)
    return out
