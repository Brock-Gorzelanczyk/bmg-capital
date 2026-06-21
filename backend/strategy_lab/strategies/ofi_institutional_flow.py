"""OFI Institutional Flow — trade aggressive-flow extremes.

Thesis: When aggressive buy volume significantly outweighs aggressive
sell volume (or vice versa) by ≥ 2 standard deviations of the rolling
60-minute window AND the absolute flow is non-trivial (|OFI| > 0.3)
AND volume is above average, institutional pressure is detected. Trade
in the flow direction.

Per-bar OFI computed from the close-position proxy (trade tape isn't
piped through the bars dict):
    typical_range  = high - low
    buy_volume     = volume × (close - low)  / typical_range
    sell_volume    = volume × (high - close) / typical_range
    ofi = (buy_volume - sell_volume) / (buy_volume + sell_volume)

Per-symbol cooldown: max ONE OFI signal per 30 minutes per symbol.
OFI extremes can persist for many consecutive bars; without cooldown
the same level fires repeated duplicate signals.

Regime: any. Active hours: 09:30-16:00 ET (RTH only).

composite_threshold: 70 (set in stock_day.yaml strategy_thresholds map)
so the discipline filter throttles by quality, not by signal cap.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import List, Optional

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "ofi_institutional_flow"

ROLLING_WINDOW_BARS = 12       # at 5m bars = 60 minutes
MIN_BARS = ROLLING_WINDOW_BARS + 5
Z_SCORE_THRESHOLD = 2.0
OFI_MIN_ABS = 0.30
VOLUME_RATIO_REQUIRED = 1.2
COOLDOWN_SECONDS = 30 * 60     # 30 minutes per symbol
MAX_CONFIDENCE = 0.80

# Per-process state (lost on restart — acceptable for a cooldown)
_last_signal_at: dict[str, float] = {}
_cooldown_lock = threading.Lock()


def _et_hour_now() -> int:
    return (datetime.now(timezone.utc).hour - 4) % 24


def _check_cooldown(symbol: str) -> bool:
    """True if the symbol is still in cooldown (skip signal).

    Returns False for symbols never seen before — must NOT use a default of 0.0
    because time.monotonic() also starts near 0 at process boot, which would
    incorrectly treat every first call as "just fired".
    """
    with _cooldown_lock:
        last = _last_signal_at.get(symbol)
        if last is None:
            return False
        return (time.monotonic() - last) < COOLDOWN_SECONDS


def _mark_signal(symbol: str) -> None:
    with _cooldown_lock:
        _last_signal_at[symbol] = time.monotonic()


def _bar_ofi(bar: dict) -> Optional[tuple[float, float, float]]:
    """Return (ofi, buy_volume, sell_volume) for one bar, or None on degenerate input."""
    h = float(bar.get("h", 0) or 0)
    l = float(bar.get("l", 0) or 0)
    c = float(bar.get("c", 0) or 0)
    v = float(bar.get("v", 0) or 0)
    if h <= 0 or l <= 0 or c <= 0 or v <= 0 or h <= l:
        return None  # halt / 0-range / zero-volume bar
    rng = h - l
    buy_v = v * (c - l) / rng
    sell_v = v * (h - c) / rng
    denom = buy_v + sell_v
    if denom <= 0:
        return None
    return ((buy_v - sell_v) / denom, buy_v, sell_v)


def _rolling_stats(values: list[float]) -> tuple[float, float]:
    n = len(values)
    if n == 0:
        return 0.0, 0.0
    mean = sum(values) / n
    if n < 2:
        return mean, 0.0
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    return mean, var ** 0.5


def _short_term_trend(closes: list[float], lookback: int = 3) -> int:
    """+1 if last close > close N bars ago, -1 if lower, 0 if equal."""
    if len(closes) < lookback + 1:
        return 0
    if closes[-1] > closes[-1 - lookback]:
        return 1
    if closes[-1] < closes[-1 - lookback]:
        return -1
    return 0


def _spy_5m_trend(bars: dict) -> Optional[int]:
    spy = bars.get("SPY") or bars.get("SPY/USD")
    if not spy or len(spy) < 4:
        return None
    try:
        closes = [float(b.get("c", 0)) for b in spy[-4:]]
        if any(c <= 0 for c in closes):
            return None
        return _short_term_trend(closes, lookback=3)
    except Exception:
        return None


def _build_signal_for_symbol(symbol: str, bar_list: list, spy_trend: Optional[int]) -> Optional[Signal]:
    if not bar_list or len(bar_list) < MIN_BARS:
        return None

    # Compute per-bar OFI for the last (ROLLING_WINDOW_BARS + 1) bars
    window = bar_list[-(ROLLING_WINDOW_BARS + 1):]
    ofi_series: list[float] = []
    for b in window:
        r = _bar_ofi(b)
        if r is None:
            continue
        ofi_series.append(r[0])

    if len(ofi_series) < ROLLING_WINDOW_BARS // 2:
        return None  # too many degenerate bars

    current_ofi = ofi_series[-1]
    rolling = ofi_series[:-1]  # exclude current from mean/std
    mean_ofi, std_ofi = _rolling_stats(rolling)
    if std_ofi <= 0:
        return None

    z = (current_ofi - mean_ofi) / std_ofi

    # Direction filter
    if abs(z) < Z_SCORE_THRESHOLD or abs(current_ofi) < OFI_MIN_ABS:
        return None
    side_long = (z > 0 and current_ofi > 0)
    side_short = (z < 0 and current_ofi < 0)
    if not (side_long or side_short):
        return None

    # Volume confirmation — current vs 60-min avg
    recent_vols = [float(b.get("v", 0) or 0) for b in window]
    avg_vol = (sum(recent_vols[:-1]) / max(1, len(recent_vols) - 1)) if len(recent_vols) > 1 else 0.0
    last_v = recent_vols[-1] if recent_vols else 0.0
    if avg_vol <= 0:
        return None
    vol_ratio = last_v / avg_vol
    if vol_ratio < VOLUME_RATIO_REQUIRED:
        return None

    # Cooldown gate — checked AFTER all other conditions to avoid useless work
    if _check_cooldown(symbol):
        logger.debug("[%s] %s in cooldown — skipping", STRATEGY_NAME, symbol)
        return None

    # MTF: short-term 5m direction matches the OFI side
    closes = [float(b.get("c", 0) or 0) for b in bar_list[-15:]]
    s_trend = _short_term_trend(closes, lookback=3)
    if side_long:
        mtf_score = 1.0 if s_trend == 1 else 0.5 if s_trend == 0 else 0.2
    else:
        mtf_score = 1.0 if s_trend == -1 else 0.5 if s_trend == 0 else 0.2

    # Cross-asset
    if spy_trend is None:
        cross_agree = False
    else:
        cross_agree = (spy_trend == 1 and side_long) or (spy_trend == -1 and side_short)

    # Confidence: z-score magnitude + volume + mtf
    z_excess = (abs(z) - Z_SCORE_THRESHOLD) / 2.0  # 2→0, 4→1
    vol_excess = (vol_ratio - VOLUME_RATIO_REQUIRED) / 0.8  # 1.2→0, 2.0→1
    confidence = min(
        MAX_CONFIDENCE,
        0.55 + 0.10 * min(1.0, z_excess) + 0.08 * min(1.0, vol_excess) + 0.07 * mtf_score,
    )

    reason_payload = {
        "setup": "ofi_institutional_flow",
        "side": "long" if side_long else "short",
        "ofi_current": round(current_ofi, 3),
        "z_score": round(z, 2),
        "rolling_mean": round(mean_ofi, 3),
        "rolling_std": round(std_ofi, 3),
        "volume_ratio": round(vol_ratio, 2),
        "volume_agreement": round(min(1.0, max(0.0, (vol_ratio - 1.0) / 1.0)), 2),
        "mtf_alignment": round(mtf_score, 2),
        "cross_asset_agree": cross_agree,
    }

    _mark_signal(symbol)

    return Signal(
        symbol=symbol,
        side="buy" if side_long else "sell",
        confidence=round(confidence, 3),
        size_hint=0.04,
        strategy=STRATEGY_NAME,
        reason=json.dumps(reason_payload),
    )


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    if not bars:
        return []

    # Active hours guard — RTH 09:30-16:00 ET only
    h_et = _et_hour_now()
    if not (9 <= h_et < 16):
        return []

    spy_trend = _spy_5m_trend(bars)
    out: List[Signal] = []
    for symbol, bar_list in bars.items():
        try:
            sig = _build_signal_for_symbol(symbol, bar_list, spy_trend)
            if sig is not None:
                out.append(sig)
        except Exception as exc:
            logger.warning("[%s] %s failed: %s", STRATEGY_NAME, symbol, exc)
    return out


# Test-only: clear cooldown state (used by smoke tests)
def _reset_cooldown_for_tests() -> None:
    with _cooldown_lock:
        _last_signal_at.clear()
