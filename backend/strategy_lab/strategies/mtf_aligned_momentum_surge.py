"""MTF Aligned Momentum Surge — multi-timeframe trend + ADX-confirmed entry.

Thesis: When 5m, 15m, and 1h timeframes all align in the same trend
direction AND 15m ADX(14) > 25, a momentum surge is in progress.
Enter on a pullback to 5m SMA20 with a reversal candle as confirmation.

Receives 5m bars; resamples to 15m (stride 3) and 1h (stride 12) for
the higher-timeframe trend checks. ADX(14) is computed on the 15m
resampled series — the spec's intended interpretation.

Regime: bull_trending (LONG) / bear_trending (SHORT) — discipline gate
handles enforcement. Active hours: 09:30-16:00 ET, but ONLY for equity
bots. Crypto runs 24/7 (US RTH happens to be peak liquidity but
crypto momentum surges can occur anytime).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import List, Optional

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "mtf_aligned_momentum_surge"

MIN_BARS = 240  # need 240 5m bars = 20 hours for 1h × 20 SMA + ADX history
SMA_PERIOD = 20
ADX_PERIOD = 14
ADX_SURGE_THRESHOLD = 25.0
PULLBACK_MAX_ATR = 0.30
MAX_CONFIDENCE = 0.85


def _et_hour_now() -> int:
    return (datetime.now(timezone.utc).hour - 4) % 24


def _resample(bars: list, stride: int) -> list:
    """Aggregate every `stride` consecutive bars into one (right-aligned)."""
    if stride <= 1 or len(bars) < stride:
        return list(bars)
    out: list = []
    # Right-align so the most recent group ends at the last bar
    n = len(bars)
    start = n % stride
    for i in range(start, n - stride + 1, stride):
        group = bars[i:i + stride]
        if not group:
            continue
        try:
            o = float(group[0].get("o", 0) or 0)
            c = float(group[-1].get("c", 0) or 0)
            h = max(float(b.get("h", 0) or 0) for b in group)
            l_vals = [float(b.get("l", 0) or 0) for b in group if (b.get("l") or 0) > 0]
            l = min(l_vals) if l_vals else 0.0
            v = sum(float(b.get("v", 0) or 0) for b in group)
            ts = group[-1].get("ts")
            out.append({"o": o, "c": c, "h": h, "l": l, "v": v, "ts": ts})
        except Exception:
            continue
    return out


def _sma(closes: list[float], period: int) -> float | None:
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def _atr(bars: list, period: int = 14) -> float:
    if len(bars) < period + 1:
        return 0.0
    trs: list[float] = []
    for i in range(len(bars) - period, len(bars)):
        if i == 0:
            continue
        cur = bars[i]
        prev = bars[i - 1]
        h = float(cur.get("h", 0) or 0)
        l = float(cur.get("l", 0) or 0)
        prev_c = float(prev.get("c", 0) or 0)
        trs.append(max(h - l, abs(h - prev_c), abs(l - prev_c)))
    return (sum(trs) / len(trs)) if trs else 0.0


def _adx(bars: list, period: int = ADX_PERIOD) -> float | None:
    """Wilder ADX. Needs ≥ 2× period + 1 bars for a stable value."""
    n = len(bars)
    if n < period * 2 + 1:
        return None
    plus_dm: list[float] = []
    minus_dm: list[float] = []
    trs: list[float] = []
    for i in range(1, n):
        cur = bars[i]
        prev = bars[i - 1]
        h, l = float(cur.get("h", 0) or 0), float(cur.get("l", 0) or 0)
        prev_h = float(prev.get("h", 0) or 0)
        prev_l = float(prev.get("l", 0) or 0)
        prev_c = float(prev.get("c", 0) or 0)
        up_move = h - prev_h
        down_move = prev_l - l
        plus_dm.append(up_move if up_move > down_move and up_move > 0 else 0.0)
        minus_dm.append(down_move if down_move > up_move and down_move > 0 else 0.0)
        trs.append(max(h - l, abs(h - prev_c), abs(l - prev_c)))

    if len(trs) < period:
        return None

    # Wilder smoothing: first value = simple sum, then EMA-style
    def _smooth(series: list[float]) -> list[float]:
        out_s: list[float] = [sum(series[:period])]
        for i in range(period, len(series)):
            out_s.append(out_s[-1] - (out_s[-1] / period) + series[i])
        return out_s

    s_tr = _smooth(trs)
    s_pdm = _smooth(plus_dm)
    s_mdm = _smooth(minus_dm)

    dx_vals: list[float] = []
    for tr_v, pdm_v, mdm_v in zip(s_tr, s_pdm, s_mdm):
        if tr_v <= 0:
            continue
        plus_di = 100 * pdm_v / tr_v
        minus_di = 100 * mdm_v / tr_v
        denom = plus_di + minus_di
        if denom <= 0:
            continue
        dx_vals.append(100 * abs(plus_di - minus_di) / denom)

    if len(dx_vals) < period:
        return None
    # ADX = simple average of last `period` DX values (Wilder also smooths but this is close enough)
    return sum(dx_vals[-period:]) / period


def _trend_sign(closes: list[float], period: int = SMA_PERIOD) -> int:
    """+1 if last close > SMA(period), -1 if below, 0 if equal or no data."""
    if len(closes) < period:
        return 0
    sma = _sma(closes, period)
    if sma is None or closes[-1] == sma:
        return 0
    return 1 if closes[-1] > sma else -1


def _spy_direction(bars: dict) -> Optional[int]:
    """SPY trend sign on the most recent 5m bar (+1/-1/0)."""
    spy = bars.get("SPY") or bars.get("SPY/USD")
    if not spy or len(spy) < SMA_PERIOD:
        return None
    try:
        closes = [float(b.get("c", 0)) for b in spy]
        return _trend_sign(closes, SMA_PERIOD) or 0
    except Exception:
        return None


def _build_signal_for_symbol(symbol: str, bars_5m: list, spy_sign: Optional[int]) -> Optional[Signal]:
    if not bars_5m or len(bars_5m) < MIN_BARS:
        return None

    bars_15m = _resample(bars_5m, 3)
    bars_1h = _resample(bars_5m, 12)

    if len(bars_15m) < ADX_PERIOD * 2 + 1 or len(bars_1h) < SMA_PERIOD:
        return None

    closes_5m = [float(b.get("c", 0) or 0) for b in bars_5m]
    closes_15m = [float(b.get("c", 0) or 0) for b in bars_15m]
    closes_1h = [float(b.get("c", 0) or 0) for b in bars_1h]

    t5 = _trend_sign(closes_5m)
    t15 = _trend_sign(closes_15m)
    t1h = _trend_sign(closes_1h)

    if t5 == 0 or t5 != t15 or t15 != t1h:
        return None  # all 3 timeframes must agree

    adx = _adx(bars_15m, ADX_PERIOD)
    if adx is None or adx < ADX_SURGE_THRESHOLD:
        return None

    sma20_5m = _sma(closes_5m, SMA_PERIOD)
    atr_5m = _atr(bars_5m, period=14)
    if sma20_5m is None or atr_5m <= 0:
        return None

    last = bars_5m[-1]
    last_c = float(last.get("c", 0) or 0)
    last_o = float(last.get("o", 0) or 0)
    last_h = float(last.get("h", 0) or 0)
    last_l = float(last.get("l", 0) or 0)
    last_v = float(last.get("v", 0) or 0)
    if last_c <= 0:
        return None

    # Pullback to SMA20 — current bar's wick to SMA must be within 0.3 ATR
    if t5 > 0:
        pullback_distance = abs(last_l - sma20_5m) / atr_5m
        # Reversal candle: close > open AND lower wick reaches near SMA20
        is_reversal = last_c > last_o and last_l <= sma20_5m + 0.1 * atr_5m
    else:
        pullback_distance = abs(last_h - sma20_5m) / atr_5m
        is_reversal = last_c < last_o and last_h >= sma20_5m - 0.1 * atr_5m

    if pullback_distance > PULLBACK_MAX_ATR or not is_reversal:
        return None

    # Volume agreement: last bar vol vs 20-bar avg
    recent_vols = [float(b.get("v", 0) or 0) for b in bars_5m[-21:-1]]
    avg_vol = (sum(recent_vols) / len(recent_vols)) if recent_vols else 0.0
    vol_ratio = (last_v / avg_vol) if avg_vol > 0 else 1.0
    volume_agreement = min(1.0, max(0.0, (vol_ratio - 0.8) / 0.8))  # 0.8x→0, 1.6x+→1

    # Cross-asset agreement: SPY sign matches trade direction
    if spy_sign is None:
        cross_agree = False
    else:
        cross_agree = (spy_sign == t5)

    # Confidence: ADX strength + tight pullback + volume
    adx_excess = (adx - ADX_SURGE_THRESHOLD) / 25.0
    pullback_score = (PULLBACK_MAX_ATR - pullback_distance) / PULLBACK_MAX_ATR
    confidence = min(
        MAX_CONFIDENCE,
        0.55 + 0.10 * adx_excess + 0.10 * pullback_score + 0.10 * volume_agreement,
    )

    reason_payload = {
        "setup": "mtf_aligned_momentum_surge",
        "side": "long" if t5 > 0 else "short",
        "trend_5m": t5,
        "trend_15m": t15,
        "trend_1h": t1h,
        "adx_15m": round(adx, 1),
        "pullback_atr": round(pullback_distance, 3),
        "volume_agreement": round(volume_agreement, 2),
        "mtf_alignment": 1.0,  # by definition — gate would have failed otherwise
        "cross_asset_agree": cross_agree,
    }

    return Signal(
        symbol=symbol,
        side="buy" if t5 > 0 else "sell",
        confidence=round(confidence, 3),
        size_hint=0.05,
        strategy=STRATEGY_NAME,
        reason=json.dumps(reason_payload),
    )


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    if not bars:
        return []

    # Active-hours guard: equities only (crypto/quant runs 24/7).
    asset_class = (profile_config.get("asset_class") or "").lower()
    if asset_class in ("equities", "stock", "stocks"):
        h_et = _et_hour_now()
        if not (9 <= h_et < 16):  # 9:30 simplified to 9 — close enough at hour granularity
            return []

    spy_sign = _spy_direction(bars)
    out: List[Signal] = []
    for symbol, bar_list in bars.items():
        try:
            sig = _build_signal_for_symbol(symbol, bar_list, spy_sign)
            if sig is not None:
                out.append(sig)
        except Exception as exc:
            logger.warning("[%s] %s failed: %s", STRATEGY_NAME, symbol, exc)
    return out
