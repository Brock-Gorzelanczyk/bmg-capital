"""
Expert stop placement: MAX(swing_low, ATR×1.5, 20MA stop).

swing_low: lowest low over last 20 bars (buy) / highest high (sell)
ATR: 14-bar average true range
20MA: 20-period SMA

Stop distance = max of the three methods.
Returns stop price, stop distance in pct, stop method used.
"""
from __future__ import annotations

import logging
import math

logger = logging.getLogger(__name__)


def _atr(bars: list[dict], period: int = 14) -> float | None:
    """Compute ATR over `period` bars. Returns None if insufficient data."""
    if len(bars) < period + 1:
        return None
    true_ranges = []
    for i in range(1, len(bars)):
        high = float(bars[i].get("h") or bars[i].get("high") or 0)
        low = float(bars[i].get("l") or bars[i].get("low") or 0)
        prev_close = float(bars[i - 1].get("c") or bars[i - 1].get("close") or 0)
        if high == 0 and low == 0 and prev_close == 0:
            continue
        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close),
        )
        true_ranges.append(tr)

    if len(true_ranges) < period:
        return None
    return sum(true_ranges[-period:]) / period


def _sma(bars: list[dict], period: int = 20) -> float | None:
    """Compute SMA of close prices."""
    closes = []
    for b in bars:
        c = b.get("c") or b.get("close")
        if c is not None:
            try:
                closes.append(float(c))
            except (TypeError, ValueError):
                pass
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def compute_stop(
    symbol: str,
    side: str,  # "buy" | "sell"
    entry_price: float,
    bars: list[dict],  # [{t, o, h, l, c, v}, ...]
    atr_multiplier: float = 1.5,
) -> dict:
    """Returns: {stop_price, stop_pct, method}"""
    if not bars or entry_price <= 0:
        # Fallback: 2% hard stop
        stop_price = entry_price * (0.98 if side == "buy" else 1.02)
        return {
            "stop_price": round(stop_price, 4),
            "stop_pct": 2.0,
            "method": "fallback_2pct",
        }

    candidates: dict[str, tuple[float, float]] = {}  # method -> (stop_price, stop_distance)

    # ── 1. Swing low / high stop ───────────────────────────────────────────────
    window = bars[-20:] if len(bars) >= 20 else bars
    try:
        if side == "buy":
            swing_level = min(
                float(b.get("l") or b.get("low") or entry_price) for b in window
            )
            swing_dist = entry_price - swing_level
        else:
            swing_level = max(
                float(b.get("h") or b.get("high") or entry_price) for b in window
            )
            swing_dist = swing_level - entry_price

        if swing_dist > 0:
            stop = entry_price - swing_dist if side == "buy" else entry_price + swing_dist
            candidates["swing"] = (stop, swing_dist)
    except Exception as exc:
        logger.debug("[smart_stops:%s] swing calc failed: %s", symbol, exc)

    # ── 2. ATR × multiplier stop ──────────────────────────────────────────────
    atr_val = _atr(bars)
    if atr_val is not None and atr_val > 0:
        atr_dist = atr_val * atr_multiplier
        atr_stop = entry_price - atr_dist if side == "buy" else entry_price + atr_dist
        candidates["atr"] = (atr_stop, atr_dist)

    # ── 3. 20MA stop ──────────────────────────────────────────────────────────
    sma_val = _sma(bars)
    if sma_val is not None and sma_val > 0:
        if side == "buy":
            ma_dist = entry_price - sma_val
        else:
            ma_dist = sma_val - entry_price

        if ma_dist > 0:
            ma_stop = sma_val  # stop at the MA level
            candidates["20ma"] = (ma_stop, ma_dist)

    if not candidates:
        stop_price = entry_price * (0.98 if side == "buy" else 1.02)
        return {
            "stop_price": round(stop_price, 4),
            "stop_pct": 2.0,
            "method": "fallback_2pct",
        }

    # Pick method that gives the widest stop (most conservative / protective)
    best_method = max(candidates, key=lambda m: candidates[m][1])
    best_stop, best_dist = candidates[best_method]

    stop_pct = (best_dist / entry_price) * 100 if entry_price > 0 else 0.0

    logger.debug(
        "[smart_stops:%s] side=%s entry=%.4f stop=%.4f (%.2f%%) method=%s candidates=%s",
        symbol, side, entry_price, best_stop, stop_pct, best_method,
        {m: f"{v[0]:.4f}" for m, v in candidates.items()},
    )

    return {
        "stop_price": round(best_stop, 4),
        "stop_pct": round(stop_pct, 4),
        "method": best_method,
    }
