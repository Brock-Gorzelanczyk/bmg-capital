"""Adapter layer for the Scout strategy screener.

Each adapter accepts a list of OHLCV bar dicts and returns a standardised
result dict.  No adapter imports from or modifies any trading-bot file
(runner.py, scan_and_execute.py, etc.).

Bar dict shape (all keys optional except 'close'):
    {
        "open":   float,
        "high":   float,
        "low":    float,
        "close":  float,
        "volume": float,
    }

Return shape:
    {
        "fires":         bool,
        "direction":     "LONG" | "SHORT" | None,
        "confidence":    float,          # 0.30-0.95 when fires=True
        "setup_quality": float,          # 0.0-1.0
        "key_metrics":   dict,
        "summary":       str,
        "reason":        str,            # populated when fires=False
    }
"""

from __future__ import annotations

import math
from typing import Callable

# ---------------------------------------------------------------------------
# Type alias
# ---------------------------------------------------------------------------
Bar = dict  # {"open", "high", "low", "close", "volume"}
AdapterResult = dict


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _clamp(value: float, lo: float, hi: float) -> float:
    """Clamp *value* to the closed interval [lo, hi]."""
    return max(lo, min(hi, value))


def _mean(arr: list[float]) -> float:
    """Arithmetic mean of a non-empty sequence."""
    if not arr:
        raise ValueError("_mean: empty sequence")
    return sum(arr) / len(arr)


def _std(arr: list[float]) -> float:
    """Population standard deviation (ddof=0)."""
    if len(arr) < 2:
        return 0.0
    mu = _mean(arr)
    variance = sum((x - mu) ** 2 for x in arr) / len(arr)
    return math.sqrt(variance)


def _sma_series(closes: list[float], period: int) -> list[float]:
    """Return the full SMA series for *closes* using *period*.

    The first (period-1) values are ``float('nan')``.
    The length of the output equals the length of the input.
    """
    out: list[float] = []
    for i in range(len(closes)):
        if i < period - 1:
            out.append(float("nan"))
        else:
            out.append(_mean(closes[i - period + 1 : i + 1]))
    return out


def _ema(closes: list[float], period: int) -> float:
    """Compute the final EMA value for *closes* using standard exponential
    smoothing (multiplier = 2/(period+1)).

    Initialises with a simple average of the first *period* values.
    """
    if len(closes) < period:
        return _mean(closes)
    k = 2.0 / (period + 1)
    ema = _mean(closes[:period])
    for price in closes[period:]:
        ema = price * k + ema * (1.0 - k)
    return ema


def _ema_series(closes: list[float], period: int) -> list[float]:
    """Return the full EMA series (same length as closes).

    First (period-1) values are seeded as NaN; from index period-1 onward the
    running EMA is tracked.
    """
    if len(closes) < period:
        return [float("nan")] * len(closes)
    k = 2.0 / (period + 1)
    out: list[float] = [float("nan")] * (period - 1)
    seed = _mean(closes[:period])
    out.append(seed)
    ema = seed
    for price in closes[period:]:
        ema = price * k + ema * (1.0 - k)
        out.append(ema)
    return out


def _rsi(closes: list[float], period: int = 14) -> float:
    """Wilder RSI.  Returns 50.0 if not enough bars."""
    if len(closes) < period + 1:
        return 50.0
    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    # seed with simple average of first *period* changes
    avg_gain = _mean(gains[:period])
    avg_loss = _mean(losses[:period])
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _atr(bars: list[Bar], period: int = 14) -> float:
    """Average True Range using Wilder smoothing.

    Falls back to a simple range of the last bar if not enough data.
    """
    if len(bars) < 2:
        b = bars[-1]
        return b.get("high", b["close"]) - b.get("low", b["close"])

    tr_list: list[float] = []
    for i in range(1, len(bars)):
        high = bars[i].get("high", bars[i]["close"])
        low = bars[i].get("low", bars[i]["close"])
        prev_close = bars[i - 1]["close"]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        tr_list.append(tr)

    if len(tr_list) < period:
        return _mean(tr_list)

    # Wilder smoothing
    atr = _mean(tr_list[:period])
    for tr in tr_list[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


def _closes(bars: list[Bar]) -> list[float]:
    return [b["close"] for b in bars]


def _highs(bars: list[Bar]) -> list[float]:
    return [b.get("high", b["close"]) for b in bars]


def _lows(bars: list[Bar]) -> list[float]:
    return [b.get("low", b["close"]) for b in bars]


def _volumes(bars: list[Bar]) -> list[float]:
    return [b.get("volume", 0.0) for b in bars]


def _no_fire(reason: str) -> AdapterResult:
    return {
        "fires": False,
        "direction": None,
        "confidence": 0.0,
        "setup_quality": 0.0,
        "key_metrics": {},
        "summary": "",
        "reason": reason,
    }


def _fire(
    direction: str,
    confidence: float,
    setup_quality: float,
    key_metrics: dict,
    summary: str,
) -> AdapterResult:
    return {
        "fires": True,
        "direction": direction,
        "confidence": _clamp(confidence, 0.30, 0.95),
        "setup_quality": _clamp(setup_quality, 0.0, 1.0),
        "key_metrics": key_metrics,
        "summary": summary,
        "reason": "",
    }


# ---------------------------------------------------------------------------
# Trend adapters
# ---------------------------------------------------------------------------

def _adapt_golden_cross(bars: list[Bar]) -> AdapterResult:
    """SMA50 / SMA200 crossover."""
    if len(bars) < 210:
        return _no_fire("insufficient_bars")

    closes = _closes(bars)
    sma50_series = _sma_series(closes, 50)
    sma200_series = _sma_series(closes, 200)

    sma50 = sma50_series[-1]
    sma200 = sma200_series[-1]
    spread_pct = (sma50 - sma200) / sma200 * 100.0 if sma200 else 0.0
    direction = "LONG" if sma50 > sma200 else "SHORT"

    # Find actual crossover (scan backward through history)
    cross_days_ago: int | None = None
    for i in range(len(sma50_series) - 1, 0, -1):
        s50_curr = sma50_series[i]
        s200_curr = sma200_series[i]
        s50_prev = sma50_series[i - 1]
        s200_prev = sma200_series[i - 1]
        if math.isnan(s50_curr) or math.isnan(s200_curr):
            continue
        if math.isnan(s50_prev) or math.isnan(s200_prev):
            continue
        cross_occurred = (s50_curr > s200_curr) != (s50_prev > s200_prev)
        if cross_occurred:
            cross_days_ago = len(sma50_series) - 1 - i
            break

    if cross_days_ago is None:
        return _no_fire("no_crossover_found")

    # Confidence tiers by recency
    if cross_days_ago <= 5:
        confidence = 0.90
    elif cross_days_ago <= 15:
        confidence = 0.78
    elif cross_days_ago <= 30:
        confidence = 0.65
    elif cross_days_ago <= 63:
        confidence = 0.52
    else:
        return _no_fire(f"crossover_too_old:{cross_days_ago}d")

    key_metrics = {
        "sma50": round(sma50, 4),
        "sma200": round(sma200, 4),
        "spread_pct": round(spread_pct, 3),
        "cross_days_ago": cross_days_ago,
    }
    summary = (
        f"Golden cross {cross_days_ago} day{'s' if cross_days_ago != 1 else ''} ago, "
        f"spread {spread_pct:.2f}%"
    )
    return _fire(direction, confidence, confidence - 0.05, key_metrics, summary)


def _adapt_seykota_weekly_breakout(bars: list[Bar]) -> AdapterResult:
    """4-week high breakout on weekly bars derived from daily."""
    if len(bars) < 60:
        return _no_fire("insufficient_bars")

    closes = _closes(bars)
    # Approximate weekly bars: every 5th close
    weekly = closes[::5]
    if len(weekly) < 5:
        return _no_fire("insufficient_weekly_bars")

    four_week_high = max(weekly[-5:-1]) if len(weekly) >= 5 else max(weekly[:-1])
    current_close = closes[-1]

    if current_close <= four_week_high:
        return _no_fire("no_4w_breakout")

    breakout_pct = (current_close / four_week_high - 1.0) * 100.0
    confidence = _clamp(breakout_pct * 10.0 / 100.0, 0.35, 0.85)
    key_metrics = {
        "four_week_high": round(four_week_high, 4),
        "breakout_pct": round(breakout_pct, 3),
    }
    summary = f"4-week high breakout +{breakout_pct:.2f}%"
    return _fire("LONG", confidence, confidence - 0.05, key_metrics, summary)


def _donchian_channel(bars: list[Bar], period: int) -> AdapterResult:
    """Shared Donchian channel logic (S1=20d, S2=55d)."""
    if len(bars) < period + 1:
        return _no_fire("insufficient_bars")

    highs = _highs(bars)
    lows = _lows(bars)
    closes = _closes(bars)

    channel_high = max(highs[-(period + 1):-1])
    channel_low = min(lows[-(period + 1):-1])
    current_close = closes[-1]
    atr = _atr(bars)

    if current_close > channel_high:
        direction = "LONG"
        raw_dev = (current_close - channel_high) / atr if atr else 0.0
        confidence = _clamp(0.50 + raw_dev * 0.12, 0.50, 0.85)
        breakout_pct = (current_close / channel_high - 1.0) * 100.0
        summary = f"Donchian {period}d long breakout +{breakout_pct:.2f}%"
    elif current_close < channel_low:
        direction = "SHORT"
        raw_dev = (channel_low - current_close) / atr if atr else 0.0
        confidence = _clamp(0.50 + raw_dev * 0.12, 0.50, 0.85)
        breakout_pct = (channel_low / current_close - 1.0) * 100.0
        summary = f"Donchian {period}d short breakout -{breakout_pct:.2f}%"
    else:
        return _no_fire("inside_channel")

    key_metrics = {
        "channel_high": round(channel_high, 4),
        "channel_low": round(channel_low, 4),
        "close": round(current_close, 4),
        "atr": round(atr, 4),
    }
    return _fire(direction, confidence, confidence - 0.05, key_metrics, summary)


def _adapt_turtle_donchian_s1(bars: list[Bar]) -> AdapterResult:
    """Turtle System 1: 20-day Donchian channel breakout."""
    if len(bars) < 25:
        return _no_fire("insufficient_bars")
    return _donchian_channel(bars, 20)


def _adapt_turtle_donchian_s2(bars: list[Bar]) -> AdapterResult:
    """Turtle System 2: 55-day Donchian channel breakout."""
    if len(bars) < 60:
        return _no_fire("insufficient_bars")
    return _donchian_channel(bars, 55)


def _adapt_weinstein_stage2_breakout(bars: list[Bar]) -> AdapterResult:
    """Weinstein Stage 2 / Stage 4 detection using 30-week SMA proxy."""
    if len(bars) < 165:
        return _no_fire("insufficient_bars")

    closes = _closes(bars)
    volumes = _volumes(bars)

    sma30w = _mean(closes[-150:])         # current 30-week SMA proxy
    sma30w_prev = _mean(closes[-165:-15]) # prior 30-week SMA proxy
    current_close = closes[-1]

    vol_21d_avg = _mean(volumes[-21:]) if volumes[-1] > 0 else 1.0
    vol_ratio = volumes[-1] / vol_21d_avg if vol_21d_avg > 0 else 1.0
    spread_pct = (current_close - sma30w) / sma30w * 100.0 if sma30w else 0.0

    above_sma = current_close > sma30w
    rising_sma = sma30w > sma30w_prev

    key_metrics = {
        "sma30w": round(sma30w, 4),
        "above_sma": above_sma,
        "rising_sma": rising_sma,
        "vol_ratio": round(vol_ratio, 3),
        "spread_pct": round(spread_pct, 3),
    }

    # Stage 2: uptrend
    if above_sma and rising_sma and vol_ratio >= 1.2:
        confidence = 0.70
        if vol_ratio > 1.5:
            confidence += 0.10
        if spread_pct > 3.0:
            confidence += 0.08
        confidence = _clamp(confidence, 0.35, 0.88)
        summary = (
            f"Weinstein Stage 2: close {spread_pct:+.1f}% above rising SMA30w, "
            f"vol {vol_ratio:.1f}x avg"
        )
        return _fire("LONG", confidence, confidence - 0.05, key_metrics, summary)

    # Stage 4: downtrend
    if not above_sma and not rising_sma:
        confidence = 0.60
        if vol_ratio > 1.5:
            confidence += 0.08
        confidence = _clamp(confidence, 0.35, 0.85)
        summary = (
            f"Weinstein Stage 4: close below declining SMA30w ({spread_pct:+.1f}%), "
            f"vol {vol_ratio:.1f}x"
        )
        return _fire("SHORT", confidence, confidence - 0.05, key_metrics, summary)

    return _no_fire("not_stage2_or_stage4")


# ---------------------------------------------------------------------------
# Mean reversion adapters
# ---------------------------------------------------------------------------

def _adapt_bollinger_squeeze(bars: list[Bar]) -> AdapterResult:
    """Bollinger Band squeeze with oversold/overbought signal."""
    if len(bars) < 25:
        return _no_fire("insufficient_bars")

    closes = _closes(bars)
    window = closes[-20:]
    middle = _mean(window)
    sd = _std(window)
    upper = middle + 2.0 * sd
    lower = middle - 2.0 * sd
    bandwidth = (upper - lower) / middle if middle else 0.0
    current_close = closes[-1]

    # Bandwidth percentile over last 50 bars
    bw_history: list[float] = []
    ref_closes = closes[-50:] if len(closes) >= 50 else closes
    for i in range(20, len(ref_closes) + 1):
        w = ref_closes[max(0, i - 20):i]
        if len(w) >= 10:
            m = _mean(w)
            bw_history.append((max(w) - min(w)) / m if m else 0.0)

    if bw_history:
        bw_sorted = sorted(bw_history)
        pct_rank = sum(1 for bw in bw_sorted if bw <= bandwidth) / len(bw_sorted) * 100.0
    else:
        pct_rank = 50.0

    squeeze = pct_rank <= 20.0

    key_metrics = {
        "bb_upper": round(upper, 4),
        "bb_lower": round(lower, 4),
        "bandwidth": round(bandwidth, 5),
        "squeeze_pct": round(pct_rank, 1),
    }

    if current_close < lower:
        if not squeeze:
            return _no_fire("no_squeeze")
        dev_std = (lower - current_close) / sd if sd else 0.0
        confidence = _clamp(dev_std * 0.25, 0.35, 0.85)
        return _fire(
            "LONG", confidence, confidence,
            key_metrics,
            f"BB squeeze LONG: close {dev_std:.2f}σ below lower band",
        )
    elif current_close > upper:
        if not squeeze:
            return _no_fire("no_squeeze")
        dev_std = (current_close - upper) / sd if sd else 0.0
        confidence = _clamp(dev_std * 0.25, 0.35, 0.85)
        return _fire(
            "SHORT", confidence, confidence,
            key_metrics,
            f"BB squeeze SHORT: close {dev_std:.2f}σ above upper band",
        )

    return _no_fire("inside_bands")


def _adapt_rsi_bands(bars: list[Bar]) -> AdapterResult:
    """Classic RSI oversold/overbought (14-period)."""
    if len(bars) < 30:
        return _no_fire("insufficient_bars")

    closes = _closes(bars)
    rsi = _rsi(closes, 14)
    key_metrics = {"rsi_14": round(rsi, 2), "oversold": rsi < 30}

    if rsi < 30:
        confidence = _clamp(max(0.40, (30.0 - rsi) / 30.0 * 1.5), 0.40, 0.88)
        return _fire(
            "LONG", confidence, confidence,
            key_metrics,
            f"RSI(14) oversold at {rsi:.1f}",
        )
    elif rsi > 70:
        confidence = _clamp(max(0.40, (rsi - 70.0) / 30.0 * 1.5), 0.40, 0.88)
        return _fire(
            "SHORT", confidence, confidence,
            key_metrics,
            f"RSI(14) overbought at {rsi:.1f}",
        )

    return _no_fire(f"rsi_neutral:{rsi:.1f}")


def _adapt_rsi2_mean_reversion(bars: list[Bar], crypto: bool = False) -> AdapterResult:
    """RSI(2) mean reversion with optional 200d MA trend filter."""
    if len(bars) < 3:
        return _no_fire("insufficient_bars")

    closes = _closes(bars)
    rsi2 = _rsi(closes, 2)

    # Trend filter (equity only)
    sma200: float | None = None
    above_200ma: bool | None = None
    if not crypto and len(closes) >= 200:
        sma200 = _mean(closes[-200:])
        above_200ma = closes[-1] > sma200

    key_metrics: dict = {"rsi_2": round(rsi2, 2)}
    if sma200 is not None:
        key_metrics["above_200ma"] = above_200ma
        key_metrics["sma200"] = round(sma200, 4)

    trend_ok_long = crypto or above_200ma is None or above_200ma
    trend_ok_short = True  # no trend filter on shorts for simplicity

    trend_label = ""
    if not crypto and above_200ma is not None:
        trend_label = f", {'above' if above_200ma else 'below'} SMA200"

    if rsi2 < 10 and trend_ok_long:
        if rsi2 < 2:
            confidence = 0.88
        elif rsi2 < 5:
            confidence = 0.72
        else:
            confidence = 0.52
        return _fire(
            "LONG", confidence, confidence,
            key_metrics,
            f"RSI(2) = {rsi2:.1f} (extreme oversold){trend_label}",
        )
    elif rsi2 > 65 and trend_ok_short:
        if rsi2 > 95:
            confidence = 0.86
        elif rsi2 > 90:
            confidence = 0.72
        else:
            confidence = 0.48
        return _fire(
            "SHORT", confidence, confidence,
            key_metrics,
            f"RSI(2) = {rsi2:.1f} (overbought){trend_label}",
        )

    reason = "rsi2_neutral"
    if rsi2 < 10 and not trend_ok_long:
        reason = "rsi2_oversold_but_below_200ma"
    return _no_fire(reason)


def _adapt_vwap_reversion(bars: list[Bar]) -> AdapterResult:
    """Rolling 20-bar VWAP deviation mean reversion."""
    if len(bars) < 20:
        return _no_fire("insufficient_bars")

    window = bars[-20:]
    closes_w = _closes(window)
    vols_w = _volumes(window)

    total_vol = sum(vols_w)
    if total_vol == 0:
        # Fallback: simple average if volume data absent
        vwap = _mean(closes_w)
    else:
        vwap = sum(c * v for c, v in zip(closes_w, vols_w)) / total_vol

    current_close = closes_w[-1]
    atr = _atr(bars)
    deviation = current_close - vwap
    dev_atrs = abs(deviation) / atr if atr else 0.0
    deviation_pct = deviation / vwap * 100.0 if vwap else 0.0

    key_metrics = {
        "vwap_20d": round(vwap, 4),
        "deviation_pct": round(deviation_pct, 3),
        "atr": round(atr, 4),
        "dev_atrs": round(dev_atrs, 3),
    }

    if dev_atrs < 1.5:
        return _no_fire(f"deviation_too_small:{dev_atrs:.2f}_atrs")

    confidence = _clamp(0.50 + dev_atrs * 0.10, 0.35, 0.88)
    direction = "LONG" if deviation < 0 else "SHORT"
    summary = (
        f"VWAP reversion {'LONG' if direction == 'LONG' else 'SHORT'}: "
        f"{dev_atrs:.1f}x ATR from 20d VWAP ({deviation_pct:+.2f}%)"
    )
    return _fire(direction, confidence, confidence - 0.05, key_metrics, summary)


def _adapt_camarilla_pivot_reversion(bars: list[Bar]) -> AdapterResult:
    """Camarilla pivot H3/L3 reversion."""
    if len(bars) < 5:
        return _no_fire("insufficient_bars")

    yesterday = bars[-2]
    prev_high = yesterday.get("high", yesterday["close"])
    prev_low = yesterday.get("low", yesterday["close"])
    prev_close = yesterday["close"]
    hl_range = prev_high - prev_low

    h3 = prev_close + hl_range * 1.1 / 4.0
    l3 = prev_close - hl_range * 1.1 / 4.0
    current_close = bars[-1]["close"]

    key_metrics = {
        "h3": round(h3, 4),
        "l3": round(l3, 4),
        "current_close": round(current_close, 4),
    }

    if current_close < l3:
        distance = (l3 - current_close) / hl_range if hl_range else 0.0
        confidence = _clamp(0.50 + distance * 2.0, 0.50, 0.80)
        return _fire(
            "LONG", confidence, confidence,
            key_metrics,
            f"Camarilla LONG: close {current_close:.4f} below L3 {l3:.4f}",
        )
    elif current_close > h3:
        distance = (current_close - h3) / hl_range if hl_range else 0.0
        confidence = _clamp(0.50 + distance * 2.0, 0.50, 0.80)
        return _fire(
            "SHORT", confidence, confidence,
            key_metrics,
            f"Camarilla SHORT: close {current_close:.4f} above H3 {h3:.4f}",
        )

    return _no_fire("inside_camarilla_range")


# ---------------------------------------------------------------------------
# Momentum adapters
# ---------------------------------------------------------------------------

def _adapt_fifty_two_week_high_momentum(bars: list[Bar]) -> AdapterResult:
    """52-week high proximity momentum."""
    if len(bars) < 252:
        return _no_fire("insufficient_bars")

    closes = _closes(bars)
    week52_high = max(closes[-252:])
    current_close = closes[-1]
    distance_pct = (week52_high - current_close) / week52_high

    key_metrics = {
        "week52_high": round(week52_high, 4),
        "distance_pct": round(distance_pct * 100.0, 3),
    }

    if distance_pct > 0.05:
        return _no_fire(f"not_near_52w_high:{distance_pct*100:.1f}%_away")

    # Scale: 0% away → 0.85, 5% away → 0.50
    confidence = _clamp(0.85 - (distance_pct / 0.05) * 0.35, 0.50, 0.85)
    return _fire(
        "LONG", confidence, confidence,
        key_metrics,
        f"Within {distance_pct*100:.1f}% of 52-week high",
    )


def _adapt_relative_strength_leaders(bars: list[Bar]) -> AdapterResult:
    """60-day relative return leader."""
    if len(bars) < 60:
        return _no_fire("insufficient_bars")

    closes = _closes(bars)
    return_60d = closes[-1] / closes[-61] - 1.0 if len(closes) >= 61 else closes[-1] / closes[0] - 1.0
    return_20d = closes[-1] / closes[-21] - 1.0 if len(closes) >= 21 else closes[-1] / closes[0] - 1.0

    key_metrics = {
        "return_60d": round(return_60d * 100.0, 3),
        "return_20d": round(return_20d * 100.0, 3),
    }

    if return_60d <= 0.15:
        return _no_fire(f"60d_return_insufficient:{return_60d*100:.1f}%")

    confidence = _clamp(0.50 + return_60d * 1.5, 0.35, 0.85)
    return _fire(
        "LONG", confidence, confidence,
        key_metrics,
        f"RS leader: 60d return +{return_60d*100:.1f}%",
    )


def _adapt_factor_momentum_value(bars: list[Bar]) -> AdapterResult:
    """12-month momentum with 20d extension filter."""
    if len(bars) < 100:
        return _no_fire("insufficient_bars")

    closes = _closes(bars)
    if len(closes) >= 252:
        momentum_12m = closes[-1] / closes[-252] - 1.0
    else:
        momentum_12m = closes[-1] / closes[0] - 1.0

    sma20 = _mean(closes[-20:])
    price_vs_20ma_pct = (closes[-1] - sma20) / sma20 * 100.0 if sma20 else 0.0

    key_metrics = {
        "momentum_12m": round(momentum_12m * 100.0, 3),
        "price_vs_20ma_pct": round(price_vs_20ma_pct, 3),
    }

    if momentum_12m <= 0.10:
        return _no_fire(f"momentum_weak:{momentum_12m*100:.1f}%")
    if price_vs_20ma_pct > 5.0:
        return _no_fire(f"too_extended_above_20ma:{price_vs_20ma_pct:.1f}%")

    confidence = _clamp(0.45 + momentum_12m * 0.8, 0.35, 0.85)
    return _fire(
        "LONG", confidence, confidence,
        key_metrics,
        f"Factor momentum: 12m +{momentum_12m*100:.1f}%, "
        f"20d extension {price_vs_20ma_pct:+.1f}%",
    )


def _adapt_frog_in_the_pan_momentum(bars: list[Bar]) -> AdapterResult:
    """Frog-in-the-pan: consistent small positive gains."""
    if len(bars) < 21:
        return _no_fire("insufficient_bars")

    closes = _closes(bars)
    window = closes[-22:]
    daily_returns = [
        (window[i] - window[i - 1]) / window[i - 1]
        for i in range(1, len(window))
        if window[i - 1] != 0
    ]
    daily_returns = daily_returns[-21:]

    positive_days = sum(1 for r in daily_returns if r > 0)
    small_positive_days = sum(1 for r in daily_returns if 0 < r < 0.005)
    large_positive_days = sum(1 for r in daily_returns if r >= 0.005)

    consistency_ratio = (
        small_positive_days / positive_days if positive_days > 0 else 0.0
    )

    key_metrics = {
        "consistency_ratio": round(consistency_ratio, 3),
        "positive_days": positive_days,
        "small_positive_days": small_positive_days,
        "large_positive_days": large_positive_days,
    }

    if positive_days == 0 or consistency_ratio < 0.60:
        return _no_fire(
            f"fip_no_signal:consistency={consistency_ratio:.2f}"
        )

    confidence = _clamp(0.45 + consistency_ratio * 0.35, 0.35, 0.80)
    return _fire(
        "LONG", confidence, confidence,
        key_metrics,
        f"FIP: {small_positive_days}/{positive_days} positive days are small "
        f"(consistency {consistency_ratio:.0%})",
    )


def _adapt_dual_momentum_gem(bars: list[Bar]) -> AdapterResult:
    """Dual Momentum (Gary Antonacci): absolute 12-month momentum."""
    if len(bars) < 252:
        return _no_fire("insufficient_bars")

    closes = _closes(bars)
    return_12m = closes[-1] / closes[-252] - 1.0
    return_1m = closes[-1] / closes[-22] - 1.0 if len(closes) >= 22 else 0.0

    key_metrics = {
        "return_12m": round(return_12m * 100.0, 3),
        "return_1m": round(return_1m * 100.0, 3),
    }

    if return_12m <= 0.0:
        return _no_fire(f"negative_12m_momentum:{return_12m*100:.1f}%")

    confidence = _clamp(0.45 + return_12m, 0.35, 0.80)
    return _fire(
        "LONG", confidence, confidence,
        key_metrics,
        f"Dual momentum LONG: 12m +{return_12m*100:.1f}%, 1m {return_1m*100:+.1f}%",
    )


# ---------------------------------------------------------------------------
# Breakout adapters
# ---------------------------------------------------------------------------

def _adapt_cup_and_handle(bars: list[Bar]) -> AdapterResult:
    """Cup-and-handle pattern detection."""
    if len(bars) < 40:
        return _no_fire("insufficient_bars")

    closes = _closes(bars)

    # Cup: 30-day high
    cup_high = max(closes[-40:-10])
    # Handle: 10-day window pullback
    handle_window = closes[-10:]
    handle_low = min(handle_window)
    pullback_pct = (cup_high - handle_low) / cup_high * 100.0 if cup_high else 0.0
    # Recovery: last 5 bars back toward cup high
    recovery_close = closes[-1]
    recovery_pct = (recovery_close - handle_low) / (cup_high - handle_low) * 100.0 if (cup_high - handle_low) else 0.0
    distance_from_cup_high = (cup_high - recovery_close) / cup_high * 100.0

    key_metrics = {
        "cup_high": round(cup_high, 4),
        "handle_low": round(handle_low, 4),
        "recovery_pct": round(recovery_pct, 2),
        "pullback_pct": round(pullback_pct, 2),
        "distance_from_cup_high_pct": round(distance_from_cup_high, 2),
    }

    if pullback_pct < 10.0:
        return _no_fire(f"pullback_too_shallow:{pullback_pct:.1f}%")
    if distance_from_cup_high > 2.0:
        return _no_fire(f"not_near_cup_high:{distance_from_cup_high:.1f}%_away")

    # Confidence based on pullback depth (deeper cup → stronger pattern) and recovery
    depth_score = _clamp((pullback_pct - 10.0) / 30.0, 0.0, 1.0)
    recovery_score = _clamp(recovery_pct / 100.0, 0.0, 1.0)
    confidence = _clamp(0.60 + depth_score * 0.10 + recovery_score * 0.10, 0.60, 0.80)

    return _fire(
        "LONG", confidence, confidence,
        key_metrics,
        f"Cup & handle: {pullback_pct:.1f}% pullback, "
        f"recovery {recovery_pct:.0f}%, within {distance_from_cup_high:.1f}% of high",
    )


def _adapt_darvas_box_breakout(bars: list[Bar]) -> AdapterResult:
    """Darvas box breakout: close above 10-day high."""
    if len(bars) < 20:
        return _no_fire("insufficient_bars")

    highs = _highs(bars)
    current_close = bars[-1]["close"]
    box_top = max(highs[-11:-1])

    key_metrics = {
        "box_top": round(box_top, 4),
        "breakout_pct": round((current_close / box_top - 1.0) * 100.0, 3),
    }

    if current_close <= box_top:
        return _no_fire("inside_darvas_box")

    breakout_pct = (current_close / box_top - 1.0) * 100.0
    confidence = _clamp(breakout_pct * 20.0 / 100.0, 0.30, 0.82)
    return _fire(
        "LONG", confidence, confidence,
        key_metrics,
        f"Darvas breakout: +{breakout_pct:.2f}% above box top {box_top:.4f}",
    )


def _adapt_bull_flag_continuation(bars: list[Bar]) -> AdapterResult:
    """Bull flag: strong pole followed by tight consolidation."""
    if len(bars) < 20:
        return _no_fire("insufficient_bars")

    closes = _closes(bars)

    # Pole: 10% gain in last 10 bars
    pole_start = closes[-11]
    pole_high = max(closes[-10:])
    pole_gain_pct = (pole_high - pole_start) / pole_start * 100.0 if pole_start else 0.0

    # Flag: last 5 bars consolidating (<3% drawdown from pole high)
    flag_low = min(closes[-5:])
    flag_depth_pct = (pole_high - flag_low) / pole_high * 100.0 if pole_high else 0.0

    key_metrics = {
        "pole_gain_pct": round(pole_gain_pct, 3),
        "flag_depth_pct": round(flag_depth_pct, 3),
    }

    if pole_gain_pct < 10.0:
        return _no_fire(f"pole_too_weak:{pole_gain_pct:.1f}%")
    if flag_depth_pct >= 3.0:
        return _no_fire(f"flag_too_deep:{flag_depth_pct:.1f}%")

    # Confidence: stronger pole and shallower flag = higher confidence
    pole_score = _clamp((pole_gain_pct - 10.0) / 20.0, 0.0, 1.0)
    flag_score = _clamp(1.0 - flag_depth_pct / 3.0, 0.0, 1.0)
    confidence = _clamp(0.65 + pole_score * 0.08 + flag_score * 0.07, 0.65, 0.80)

    return _fire(
        "LONG", confidence, confidence,
        key_metrics,
        f"Bull flag: pole +{pole_gain_pct:.1f}%, flag depth {flag_depth_pct:.1f}%",
    )


def _adapt_canslim_pivot_breakout(bars: list[Bar]) -> AdapterResult:
    """CANSLIM: near 10-week high + rising 50d MA + volume expansion."""
    if len(bars) < 50:
        return _no_fire("insufficient_bars")

    closes = _closes(bars)
    volumes = _volumes(bars)
    highs = _highs(bars)

    ten_week_high = max(highs[-50:])
    current_close = closes[-1]
    distance_from_10w_high = (ten_week_high - current_close) / ten_week_high * 100.0

    sma50_now = _mean(closes[-50:])
    sma50_prev = _mean(closes[-60:-10]) if len(closes) >= 60 else sma50_now
    ma50_rising = sma50_now > sma50_prev

    vol_avg = _mean(volumes[-21:]) if len(volumes) >= 21 else _mean(volumes)
    vol_expansion = volumes[-1] / vol_avg if vol_avg > 0 else 1.0

    near_10w_high = distance_from_10w_high <= 5.0

    key_metrics = {
        "near_10w_high": near_10w_high,
        "distance_from_10w_high_pct": round(distance_from_10w_high, 2),
        "ma50_rising": ma50_rising,
        "vol_expansion": round(vol_expansion, 3),
    }

    if not near_10w_high:
        return _no_fire(f"not_near_10w_high:{distance_from_10w_high:.1f}%_away")

    score = 0.55
    if ma50_rising:
        score += 0.12
    if vol_expansion >= 1.5:
        score += 0.12
    elif vol_expansion >= 1.2:
        score += 0.06
    confidence = _clamp(score, 0.35, 0.85)

    return _fire(
        "LONG", confidence, confidence,
        key_metrics,
        f"CANSLIM pivot: {distance_from_10w_high:.1f}% from 10w high, "
        f"MA50 {'rising' if ma50_rising else 'flat'}, vol {vol_expansion:.1f}x",
    )


def _adapt_donchian_breakout(bars: list[Bar]) -> AdapterResult:
    """Donchian 20-day breakout (alias of turtle S1)."""
    return _adapt_turtle_donchian_s1(bars)


# ---------------------------------------------------------------------------
# Technical adapters
# ---------------------------------------------------------------------------

def _adapt_aroon_breakout(bars: list[Bar]) -> AdapterResult:
    """Aroon oscillator trend strength."""
    if len(bars) < 30:
        return _no_fire("insufficient_bars")

    highs = _highs(bars)
    lows = _lows(bars)
    period = 30

    window_highs = highs[-period:]
    window_lows = lows[-period:]

    # Days since 30-day high/low (0 = today is the high/low)
    max_val = max(window_highs)
    min_val = min(window_lows)
    days_since_high = period - 1 - window_highs[::-1].index(max_val)
    days_since_low = period - 1 - window_lows[::-1].index(min_val)

    aroon_up = (period - days_since_high) / period * 100.0
    aroon_down = (period - days_since_low) / period * 100.0

    key_metrics = {
        "aroon_up": round(aroon_up, 2),
        "aroon_down": round(aroon_down, 2),
    }

    if aroon_up > 70 and aroon_down < 30:
        confidence = _clamp((aroon_up - aroon_down) / 100.0, 0.35, 0.85)
        return _fire(
            "LONG", confidence, confidence,
            key_metrics,
            f"Aroon LONG: up={aroon_up:.0f}, down={aroon_down:.0f}",
        )
    elif aroon_down > 70 and aroon_up < 30:
        confidence = _clamp((aroon_down - aroon_up) / 100.0, 0.35, 0.85)
        return _fire(
            "SHORT", confidence, confidence,
            key_metrics,
            f"Aroon SHORT: down={aroon_down:.0f}, up={aroon_up:.0f}",
        )

    return _no_fire(f"aroon_neutral:up={aroon_up:.0f},down={aroon_down:.0f}")


def _adapt_hammer_at_support(bars: list[Bar]) -> AdapterResult:
    """Hammer candle at 20-day support."""
    if len(bars) < 30:
        return _no_fire("insufficient_bars")

    last = bars[-1]
    o = last.get("open", last["close"])
    h = last.get("high", last["close"])
    lo = last.get("low", last["close"])
    c = last["close"]

    body = abs(c - o)
    upper_shadow = h - max(c, o)
    lower_shadow = min(c, o) - lo
    candle_range = h - lo

    is_hammer = (
        candle_range > 0
        and lower_shadow >= 2.0 * body
        and upper_shadow <= 0.1 * candle_range
    )

    closes = _closes(bars)
    support_level = min(closes[-20:])
    near_support = closes[-1] <= support_level * 1.03

    key_metrics = {
        "is_hammer": is_hammer,
        "near_support": near_support,
        "support_level": round(support_level, 4),
        "lower_shadow": round(lower_shadow, 4),
        "body": round(body, 4),
    }

    if not is_hammer or not near_support:
        reason = []
        if not is_hammer:
            reason.append("no_hammer")
        if not near_support:
            reason.append("not_near_support")
        return _no_fire("+".join(reason))

    # Confidence based on shadow-to-body ratio and proximity to support
    shadow_ratio = lower_shadow / body if body > 0 else 0.0
    proximity = (support_level * 1.03 - closes[-1]) / (support_level * 0.03) if support_level else 0.0
    confidence = _clamp(0.55 + min(shadow_ratio - 2.0, 3.0) * 0.05 + proximity * 0.05, 0.55, 0.75)

    return _fire(
        "LONG", confidence, confidence,
        key_metrics,
        f"Hammer at support ({support_level:.4f}): "
        f"shadow/body ratio {shadow_ratio:.1f}x",
    )


def _adapt_three_white_soldiers(bars: list[Bar]) -> AdapterResult:
    """Three White Soldiers candlestick pattern."""
    if len(bars) < 5:
        return _no_fire("insufficient_bars")

    last3 = bars[-3:]
    opens = [b.get("open", b["close"]) for b in last3]
    closes = [b["close"] for b in last3]
    prev_open = bars[-4].get("open", bars[-4]["close"])
    prev_close = bars[-4]["close"]

    body_sizes = [abs(c - o) / o * 100.0 for c, o in zip(closes, opens) if o != 0]

    # All three must be bullish
    all_bullish = all(c > o for c, o in zip(closes, opens))
    # Each closes higher than previous
    ascending = closes[0] > prev_close and closes[1] > closes[0] and closes[2] > closes[1]
    # Each opens within prior candle's body
    open_in_body = (
        prev_open <= opens[0] <= prev_close
        and opens[0] <= opens[1] <= closes[0]
        and opens[1] <= opens[2] <= closes[1]
    )
    # All bodies > 0.3%
    significant_bodies = all(bs > 0.3 for bs in body_sizes)

    key_metrics = {
        "body_sizes": [round(bs, 3) for bs in body_sizes],
        "all_bullish": all_bullish,
        "ascending_closes": ascending,
        "opens_in_body": open_in_body,
    }

    if not (all_bullish and ascending and open_in_body and significant_bodies):
        reasons = []
        if not all_bullish:
            reasons.append("not_all_bullish")
        if not ascending:
            reasons.append("not_ascending")
        if not open_in_body:
            reasons.append("opens_outside_body")
        if not significant_bodies:
            reasons.append("bodies_too_small")
        return _no_fire("+".join(reasons) if reasons else "pattern_incomplete")

    avg_body = _mean(body_sizes)
    confidence = _clamp(0.65 + min(avg_body / 1.0, 1.0) * 0.15, 0.65, 0.80)
    return _fire(
        "LONG", confidence, confidence,
        key_metrics,
        f"Three White Soldiers: avg body {avg_body:.2f}%",
    )


def _adapt_ultimate_oscillator(bars: list[Bar]) -> AdapterResult:
    """Williams Ultimate Oscillator (7/14/28 periods)."""
    if len(bars) < 40:
        return _no_fire("insufficient_bars")

    def _bp_tr_series(
        b: list[Bar],
    ) -> tuple[list[float], list[float]]:
        bp_list: list[float] = []
        tr_list: list[float] = []
        for i in range(1, len(b)):
            high = b[i].get("high", b[i]["close"])
            low = b[i].get("low", b[i]["close"])
            prev_c = b[i - 1]["close"]
            true_low = min(low, prev_c)
            true_high = max(high, prev_c)
            bp_list.append(b[i]["close"] - true_low)
            tr_list.append(true_high - true_low)
        return bp_list, tr_list

    bp, tr = _bp_tr_series(bars)

    def _ratio(bp_: list[float], tr_: list[float], n: int) -> float:
        s_bp = sum(bp_[-n:])
        s_tr = sum(tr_[-n:])
        return s_bp / s_tr if s_tr else 0.0

    r7 = _ratio(bp, tr, 7)
    r14 = _ratio(bp, tr, 14)
    r28 = _ratio(bp, tr, 28)
    uo = 100.0 * (4.0 * r7 + 2.0 * r14 + r28) / 7.0

    key_metrics = {"ultimate_oscillator": round(uo, 2)}

    if uo < 30:
        confidence = _clamp((30.0 - uo) / 30.0, 0.35, 0.85)
        return _fire(
            "LONG", confidence, confidence,
            key_metrics,
            f"Ultimate Oscillator oversold: {uo:.1f}",
        )
    elif uo > 70:
        confidence = _clamp((uo - 70.0) / 30.0, 0.35, 0.85)
        return _fire(
            "SHORT", confidence, confidence,
            key_metrics,
            f"Ultimate Oscillator overbought: {uo:.1f}",
        )

    return _no_fire(f"uo_neutral:{uo:.1f}")


def _adapt_chaikin_money_flow(bars: list[Bar]) -> AdapterResult:
    """Chaikin Money Flow (21 periods)."""
    if len(bars) < 21:
        return _no_fire("insufficient_bars")

    window = bars[-21:]
    mf_vol_sum = 0.0
    vol_sum = 0.0
    for b in window:
        high = b.get("high", b["close"])
        low = b.get("low", b["close"])
        close = b["close"]
        vol = b.get("volume", 0.0)
        hl_range = high - low
        if hl_range > 0:
            mfm = ((close - low) - (high - close)) / hl_range
        else:
            mfm = 0.0
        mf_vol_sum += mfm * vol
        vol_sum += vol

    cmf = mf_vol_sum / vol_sum if vol_sum > 0 else 0.0
    key_metrics = {
        "cmf": round(cmf, 4),
        "positive_flow": cmf > 0,
    }

    if cmf > 0.05:
        confidence = _clamp(abs(cmf) * 4.0, 0.35, 0.85)
        return _fire(
            "LONG", confidence, confidence,
            key_metrics,
            f"CMF LONG: {cmf:.3f} (positive money flow)",
        )
    elif cmf < -0.05:
        confidence = _clamp(abs(cmf) * 4.0, 0.35, 0.85)
        return _fire(
            "SHORT", confidence, confidence,
            key_metrics,
            f"CMF SHORT: {cmf:.3f} (negative money flow)",
        )

    return _no_fire(f"cmf_neutral:{cmf:.3f}")


def _adapt_macd_crossover(bars: list[Bar]) -> AdapterResult:
    """MACD line crossing Signal line (EMA12/26/9)."""
    if len(bars) < 35:
        return _no_fire("insufficient_bars")

    closes = _closes(bars)

    ema12_series = _ema_series(closes, 12)
    ema26_series = _ema_series(closes, 26)
    macd_series = [
        (e12 - e26)
        for e12, e26 in zip(ema12_series, ema26_series)
        if not (math.isnan(e12) or math.isnan(e26))
    ]
    if len(macd_series) < 9:
        return _no_fire("insufficient_macd_bars")

    signal_series = _ema_series(macd_series, 9)
    macd_val = macd_series[-1]
    signal_val = signal_series[-1]
    if math.isnan(signal_val):
        return _no_fire("signal_nan")

    histogram = macd_val - signal_val

    # Find crossover in last 3 bars
    cross_bars_ago: int | None = None
    for lookback in range(1, min(4, len(macd_series))):
        m_curr = macd_series[-lookback]
        s_curr = signal_series[-lookback]
        m_prev = macd_series[-lookback - 1]
        s_prev = signal_series[-lookback - 1]
        if math.isnan(s_curr) or math.isnan(s_prev):
            continue
        if (m_curr > s_curr) != (m_prev > s_prev):
            cross_bars_ago = lookback - 1
            break

    key_metrics = {
        "macd": round(macd_val, 6),
        "signal": round(signal_val, 6),
        "histogram": round(histogram, 6),
        "cross_bars_ago": cross_bars_ago if cross_bars_ago is not None else -1,
    }

    if cross_bars_ago is None:
        return _no_fire("no_recent_cross")

    direction = "LONG" if macd_val > signal_val else "SHORT"
    price = closes[-1]
    confidence = _clamp(abs(histogram) / price * 1000.0, 0.30, 0.82)

    return _fire(
        direction, confidence, confidence,
        key_metrics,
        f"MACD {'bullish' if direction == 'LONG' else 'bearish'} cross "
        f"{cross_bars_ago} bar{'s' if cross_bars_ago != 1 else ''} ago, "
        f"hist={histogram:.6f}",
    )


def _adapt_earnings_drift_post(bars: list[Bar]) -> AdapterResult:
    """Post-earnings drift: price above 20d MA + volume surge."""
    if len(bars) < 60:
        return _no_fire("insufficient_bars")

    closes = _closes(bars)
    volumes = _volumes(bars)

    sma20 = _mean(closes[-20:])
    current_close = closes[-1]
    above_20ma_pct = (current_close - sma20) / sma20 * 100.0 if sma20 else 0.0

    vol_avg_20d = _mean(volumes[-21:-1]) if len(volumes) >= 21 else _mean(volumes[:-1])
    vol_ratio = volumes[-1] / vol_avg_20d if vol_avg_20d > 0 else 1.0

    key_metrics = {
        "above_20ma_pct": round(above_20ma_pct, 3),
        "vol_ratio": round(vol_ratio, 3),
    }

    if above_20ma_pct < 5.0:
        return _no_fire(f"not_above_20ma_enough:{above_20ma_pct:.1f}%")
    if vol_ratio < 1.5:
        return _no_fire(f"vol_insufficient:{vol_ratio:.2f}x")

    ma_score = _clamp((above_20ma_pct - 5.0) / 15.0, 0.0, 1.0)
    vol_score = _clamp((vol_ratio - 1.5) / 2.0, 0.0, 1.0)
    confidence = _clamp(0.50 + ma_score * 0.20 + vol_score * 0.15, 0.35, 0.85)

    return _fire(
        "LONG", confidence, confidence,
        key_metrics,
        f"Post-earnings drift: {above_20ma_pct:.1f}% above 20d MA, "
        f"vol {vol_ratio:.1f}x avg",
    )


# ---------------------------------------------------------------------------
# Crypto adapters
# ---------------------------------------------------------------------------

def _adapt_crypto_ema_cross(bars: list[Bar]) -> AdapterResult:
    """EMA20 / EMA50 crossover (crypto variant)."""
    if len(bars) < 50:
        return _no_fire("insufficient_bars")

    closes = _closes(bars)
    ema20_series = _ema_series(closes, 20)
    ema50_series = _ema_series(closes, 50)

    ema20 = ema20_series[-1]
    ema50 = ema50_series[-1]
    if math.isnan(ema20) or math.isnan(ema50):
        return _no_fire("ema_nan")

    direction = "LONG" if ema20 > ema50 else "SHORT"

    # Find crossover
    cross_days_ago: int | None = None
    for i in range(len(ema20_series) - 1, 0, -1):
        e20_curr = ema20_series[i]
        e50_curr = ema50_series[i]
        e20_prev = ema20_series[i - 1]
        e50_prev = ema50_series[i - 1]
        if any(math.isnan(v) for v in [e20_curr, e50_curr, e20_prev, e50_prev]):
            continue
        if (e20_curr > e50_curr) != (e20_prev > e50_prev):
            cross_days_ago = len(ema20_series) - 1 - i
            break

    if cross_days_ago is None:
        return _no_fire("no_crossover_found")

    # Recency confidence (same tiers as golden_cross)
    if cross_days_ago <= 5:
        confidence = 0.90
    elif cross_days_ago <= 15:
        confidence = 0.78
    elif cross_days_ago <= 30:
        confidence = 0.65
    elif cross_days_ago <= 63:
        confidence = 0.52
    else:
        return _no_fire(f"crossover_too_old:{cross_days_ago}d")

    spread_pct = (ema20 - ema50) / ema50 * 100.0 if ema50 else 0.0
    key_metrics = {
        "ema20": round(ema20, 6),
        "ema50": round(ema50, 6),
        "spread_pct": round(spread_pct, 3),
        "cross_days_ago": cross_days_ago,
    }
    summary = (
        f"EMA20/50 {'bullish' if direction == 'LONG' else 'bearish'} cross "
        f"{cross_days_ago}d ago, spread {spread_pct:+.2f}%"
    )
    return _fire(direction, confidence, confidence - 0.05, key_metrics, summary)


def _adapt_crypto_momentum_breakout(bars: list[Bar]) -> AdapterResult:
    """Crypto 20-day high breakout with volume confirmation."""
    if len(bars) < 30:
        return _no_fire("insufficient_bars")

    highs = _highs(bars)
    volumes = _volumes(bars)
    current_close = bars[-1]["close"]

    channel_high = max(highs[-21:-1])
    vol_avg = _mean(volumes[-21:-1]) if len(volumes) >= 21 else _mean(volumes[:-1])
    vol_ratio = volumes[-1] / vol_avg if vol_avg > 0 else 1.0

    key_metrics = {
        "channel_high": round(channel_high, 6),
        "breakout_pct": round((current_close / channel_high - 1.0) * 100.0, 3) if current_close > channel_high else 0.0,
        "vol_ratio": round(vol_ratio, 3),
    }

    if current_close <= channel_high:
        return _no_fire("no_breakout")

    breakout_pct = (current_close / channel_high - 1.0) * 100.0
    confidence = _clamp(0.45 + breakout_pct * 0.08 + (vol_ratio - 1.0) * 0.05, 0.35, 0.85)
    return _fire(
        "LONG", confidence, confidence,
        key_metrics,
        f"Crypto momentum breakout: +{breakout_pct:.2f}% above 20d high, "
        f"vol {vol_ratio:.1f}x",
    )


def _adapt_crypto_rsi_mean_reversion(bars: list[Bar]) -> AdapterResult:
    """RSI(2) mean reversion for crypto (no 200d MA filter)."""
    return _adapt_rsi2_mean_reversion(bars, crypto=True)


def _adapt_crypto_macd_swing(bars: list[Bar]) -> AdapterResult:
    """MACD crossover for crypto swing trades."""
    return _adapt_macd_crossover(bars)


def _adapt_crypto_volatility_breakout(bars: list[Bar]) -> AdapterResult:
    """ATR-based volatility breakout above/below 10-bar range."""
    if len(bars) < 20:
        return _no_fire("insufficient_bars")

    highs = _highs(bars)
    lows = _lows(bars)
    atr = _atr(bars)
    current_close = bars[-1]["close"]

    ten_bar_high = max(highs[-11:-1])
    ten_bar_low = min(lows[-11:-1])

    breakout_level_up = ten_bar_high + atr
    breakout_level_dn = ten_bar_low - atr

    key_metrics = {
        "atr": round(atr, 6),
        "breakout_level_up": round(breakout_level_up, 6),
        "breakout_level_dn": round(breakout_level_dn, 6),
    }

    if current_close > breakout_level_up:
        excess_atrs = (current_close - breakout_level_up) / atr if atr else 0.0
        confidence = _clamp(0.40 + excess_atrs * 0.25, 0.35, 0.85)
        key_metrics["breakout_level"] = round(breakout_level_up, 6)
        return _fire(
            "LONG", confidence, confidence,
            key_metrics,
            f"Crypto vol breakout LONG: {excess_atrs:.2f}x ATR above threshold",
        )
    elif current_close < breakout_level_dn:
        excess_atrs = (breakout_level_dn - current_close) / atr if atr else 0.0
        confidence = _clamp(0.40 + excess_atrs * 0.25, 0.35, 0.85)
        key_metrics["breakout_level"] = round(breakout_level_dn, 6)
        return _fire(
            "SHORT", confidence, confidence,
            key_metrics,
            f"Crypto vol breakout SHORT: {excess_atrs:.2f}x ATR below threshold",
        )

    return _no_fire("no_volatility_breakout")


# ---------------------------------------------------------------------------
# Registry & entry point
# ---------------------------------------------------------------------------

STRATEGY_ADAPTERS: dict[str, Callable[[list[Bar]], AdapterResult]] = {
    # Trend
    "golden_cross":               _adapt_golden_cross,
    "seykota_weekly_breakout":    _adapt_seykota_weekly_breakout,
    "turtle_donchian_s1":         _adapt_turtle_donchian_s1,
    "turtle_donchian_s2":         _adapt_turtle_donchian_s2,
    "weinstein_stage2_breakout":  _adapt_weinstein_stage2_breakout,
    # Mean reversion
    "bollinger_squeeze":          _adapt_bollinger_squeeze,
    "rsi_bands":                  _adapt_rsi_bands,
    "rsi2_mean_reversion":        _adapt_rsi2_mean_reversion,
    "vwap_reversion":             _adapt_vwap_reversion,
    "camarilla_pivot_reversion":  _adapt_camarilla_pivot_reversion,
    # Momentum
    "fifty_two_week_high_momentum": _adapt_fifty_two_week_high_momentum,
    "relative_strength_leaders":  _adapt_relative_strength_leaders,
    "factor_momentum_value":      _adapt_factor_momentum_value,
    "frog_in_the_pan_momentum":   _adapt_frog_in_the_pan_momentum,
    "dual_momentum_gem":          _adapt_dual_momentum_gem,
    # Breakout
    "cup_and_handle":             _adapt_cup_and_handle,
    "darvas_box_breakout":        _adapt_darvas_box_breakout,
    "bull_flag_continuation":     _adapt_bull_flag_continuation,
    "canslim_pivot_breakout":     _adapt_canslim_pivot_breakout,
    "donchian_breakout":          _adapt_donchian_breakout,
    # Technical
    "aroon_breakout":             _adapt_aroon_breakout,
    "hammer_at_support":          _adapt_hammer_at_support,
    "three_white_soldiers":       _adapt_three_white_soldiers,
    "ultimate_oscillator":        _adapt_ultimate_oscillator,
    "chaikin_money_flow":         _adapt_chaikin_money_flow,
    "macd_crossover":             _adapt_macd_crossover,
    "earnings_drift_post":        _adapt_earnings_drift_post,
    # Crypto
    "crypto_ema_cross":           _adapt_crypto_ema_cross,
    "crypto_momentum_breakout":   _adapt_crypto_momentum_breakout,
    "crypto_rsi_mean_reversion":  _adapt_crypto_rsi_mean_reversion,
    "crypto_macd_swing":          _adapt_crypto_macd_swing,
    "crypto_volatility_breakout": _adapt_crypto_volatility_breakout,
}


def evaluate_ticker(strategy_id: str, bars: list[Bar]) -> AdapterResult:
    """Main entry point for strategy evaluation.

    Args:
        strategy_id: Key in STRATEGY_ADAPTERS registry.
        bars: List of OHLCV bar dicts, oldest first.

    Returns:
        Standardised result dict.  Always returns a dict — never raises.
    """
    adapter = STRATEGY_ADAPTERS.get(strategy_id)
    if not adapter:
        return {
            "fires": False,
            "direction": None,
            "confidence": 0.0,
            "setup_quality": 0.0,
            "key_metrics": {},
            "summary": "",
            "reason": "no_adapter",
        }
    try:
        return adapter(bars)
    except Exception as exc:  # noqa: BLE001
        return {
            "fires": False,
            "direction": None,
            "confidence": 0.0,
            "setup_quality": 0.0,
            "key_metrics": {},
            "summary": "",
            "reason": f"error: {exc}",
        }
