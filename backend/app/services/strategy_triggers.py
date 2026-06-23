"""Per-strategy trigger-condition spec used by the Scout "Setup Checklist".

Each strategy declares an ordered list of TriggerCondition. A condition has a
weight (primary | secondary | info) and an `evaluate` callable that consumes the
recent OHLCV bar list (most-recent last; same shape as /api/bars returns:
{"t","o","h","l","c","v"}) and returns a TriggerResult.

The Scout endpoint surfaces the per-condition pass/fail + a human-readable
display string + distance-to-trigger so the UI can render an
"ARMED / NOT ARMED" checklist instead of an opaque ACTIVE badge.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import mean, stdev
from typing import Callable, Dict, List, Literal, Optional

Weight = Literal["primary", "secondary", "info"]


@dataclass
class TriggerResult:
    passed: bool
    display: str
    distance_pct: Optional[float] = None  # signed % gap to trigger (None for info or pass)
    value: Optional[float] = None         # raw current value, for downstream sorting


@dataclass
class TriggerCondition:
    name: str
    weight: Weight
    evaluate: Callable[[List[dict]], TriggerResult]


# ── Tiny indicator helpers (stdlib only) ──────────────────────────────────────

def _closes(bars: List[dict]) -> List[float]:
    return [float(b.get("c", b.get("close", 0.0))) for b in bars]


def _highs(bars: List[dict]) -> List[float]:
    return [float(b.get("h", b.get("high", 0.0))) for b in bars]


def _lows(bars: List[dict]) -> List[float]:
    return [float(b.get("l", b.get("low", 0.0))) for b in bars]


def _vols(bars: List[dict]) -> List[float]:
    return [float(b.get("v", b.get("volume", 0.0))) for b in bars]


def _sma(values: List[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    return mean(values[-period:])


def _slope_pct(values: List[float], period: int, window: int) -> Optional[float]:
    """% change of an SMA(period) over `window` bars (current vs `window` bars ago)."""
    if len(values) < period + window:
        return None
    now = mean(values[-period:])
    then = mean(values[-period - window:-window])
    if then == 0:
        return None
    return (now - then) / then * 100.0


def _ema(values: List[float], period: int) -> List[float]:
    if not values:
        return []
    k = 2.0 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def _rsi(values: List[float], period: int = 14) -> Optional[float]:
    if len(values) < period + 1:
        return None
    gains, losses = 0.0, 0.0
    for i in range(-period, 0):
        delta = values[i] - values[i - 1]
        if delta >= 0:
            gains += delta
        else:
            losses -= delta
    if losses == 0:
        return 100.0
    rs = (gains / period) / (losses / period)
    return 100.0 - 100.0 / (1.0 + rs)


def _atr(bars: List[dict], period: int = 14) -> Optional[float]:
    if len(bars) < period + 1:
        return None
    trs = []
    for i in range(-period, 0):
        h = float(bars[i].get("h", bars[i].get("high", 0)))
        l = float(bars[i].get("l", bars[i].get("low", 0)))
        prev_c = float(bars[i - 1].get("c", bars[i - 1].get("close", 0)))
        trs.append(max(h - l, abs(h - prev_c), abs(l - prev_c)))
    return mean(trs)


def _bb_width(closes: List[float], period: int = 20, mult: float = 2.0) -> Optional[float]:
    if len(closes) < period:
        return None
    window = closes[-period:]
    mid = mean(window)
    if mid == 0:
        return None
    sd = stdev(window) if len(window) > 1 else 0.0
    return (2 * mult * sd) / mid  # width as % of mid


# ── Condition factories (each returns a TriggerCondition) ─────────────────────

def _cond_price_gt_donchian_high(period: int) -> TriggerCondition:
    def ev(bars: List[dict]) -> TriggerResult:
        highs = _highs(bars)
        closes = _closes(bars)
        if len(highs) < period + 1 or not closes:
            return TriggerResult(False, f"Need {period + 1}+ bars", None, None)
        high_n = max(highs[-period - 1:-1])
        cur = closes[-1]
        gap = (cur - high_n) / high_n * 100.0
        passed = cur > high_n
        if passed:
            display = f"Current ${cur:.2f} > {period}d high ${high_n:.2f} ({gap:+.2f}%)"
            return TriggerResult(True, display, None, cur)
        display = f"Current ${cur:.2f} vs {period}d high ${high_n:.2f} ({abs(gap):.2f}% below)"
        return TriggerResult(False, display, gap, cur)
    return TriggerCondition(f"Price > {period}d high", "primary", ev)


def _cond_sma_slope(period: int, window: int) -> TriggerCondition:
    def ev(bars: List[dict]) -> TriggerResult:
        closes = _closes(bars)
        slope = _slope_pct(closes, period, window)
        if slope is None:
            return TriggerResult(False, f"Need {period + window}+ bars", None, None)
        passed = slope > 0
        display = f"{period}d SMA slope over {window}d: {slope:+.2f}%"
        return TriggerResult(passed, display, None if passed else slope, slope)
    return TriggerCondition(f"{period}d SMA slope > 0 over {window}d", "primary", ev)


def _cond_volume_multiple(mult: float, period: int = 20) -> TriggerCondition:
    def ev(bars: List[dict]) -> TriggerResult:
        vols = _vols(bars)
        if len(vols) < period + 1:
            return TriggerResult(False, f"Need {period + 1}+ bars", None, None)
        avg = mean(vols[-period - 1:-1])
        cur = vols[-1]
        if avg == 0:
            return TriggerResult(False, "Avg volume = 0", None, cur)
        ratio = cur / avg
        passed = ratio > mult
        display = f"Volume {cur:,.0f} vs {period}d avg {avg:,.0f} ({ratio:.2f}×)"
        dist = (mult - ratio) / mult * 100.0 if not passed else None
        return TriggerResult(passed, display, dist, ratio)
    return TriggerCondition(f"Volume > {mult}× {period}d avg", "secondary", ev)


def _cond_atr_threshold(threshold: float, period: int = 14) -> TriggerCondition:
    def ev(bars: List[dict]) -> TriggerResult:
        atr = _atr(bars, period)
        if atr is None:
            return TriggerResult(False, f"Need {period + 1}+ bars", None, None)
        display = f"ATR({period}) = {atr:.2f} (threshold {threshold:.2f})"
        return TriggerResult(True, display, None, atr)
    return TriggerCondition(f"ATR({period}) > {threshold}", "info", ev)


def _cond_sma_above(fast: int, slow: int) -> TriggerCondition:
    def ev(bars: List[dict]) -> TriggerResult:
        closes = _closes(bars)
        fma = _sma(closes, fast)
        sma = _sma(closes, slow)
        if fma is None or sma is None or sma == 0:
            return TriggerResult(False, f"Need {slow}+ bars", None, None)
        spread = (fma - sma) / sma * 100.0
        passed = fma > sma
        display = f"{fast}d SMA ${fma:.2f} vs {slow}d SMA ${sma:.2f} ({spread:+.2f}%)"
        return TriggerResult(passed, display, None if passed else spread, spread)
    return TriggerCondition(f"{fast}d SMA > {slow}d SMA", "primary", ev)


def _cond_recent_crossover(fast: int, slow: int, max_bars: int) -> TriggerCondition:
    def ev(bars: List[dict]) -> TriggerResult:
        closes = _closes(bars)
        if len(closes) < slow + max_bars + 1:
            return TriggerResult(False, f"Need {slow + max_bars + 1}+ bars", None, None)
        # Walk back: find the most recent bar where fast crossed above slow
        found_bars_ago = None
        for i in range(1, max_bars + 2):
            f_now = mean(closes[-i - fast + 1:len(closes) - i + 1]) if (len(closes) - i + 1) > 0 else None
            f_prev = mean(closes[-i - fast:len(closes) - i]) if (len(closes) - i) > 0 else None
            s_now = mean(closes[-i - slow + 1:len(closes) - i + 1]) if (len(closes) - i + 1) > 0 else None
            s_prev = mean(closes[-i - slow:len(closes) - i]) if (len(closes) - i) > 0 else None
            if None in (f_now, f_prev, s_now, s_prev):
                continue
            if f_prev <= s_prev and f_now > s_now:
                found_bars_ago = i
                break
        if found_bars_ago is not None and found_bars_ago <= max_bars:
            return TriggerResult(True, f"Crossover {found_bars_ago} bars ago (≤{max_bars})", None, float(found_bars_ago))
        return TriggerResult(False, f"No crossover within last {max_bars} bars", None, None)
    return TriggerCondition(f"Most recent crossover within {max_bars} bars", "secondary", ev)


def _cond_rsi_below(threshold: float, period: int = 14) -> TriggerCondition:
    def ev(bars: List[dict]) -> TriggerResult:
        rsi = _rsi(_closes(bars), period)
        if rsi is None:
            return TriggerResult(False, f"Need {period + 1}+ bars", None, None)
        passed = rsi < threshold
        display = f"RSI({period}) = {rsi:.1f} (threshold < {threshold:.0f})"
        dist = (rsi - threshold) / threshold * 100.0 if not passed else None
        return TriggerResult(passed, display, dist, rsi)
    return TriggerCondition(f"RSI({period}) < {int(threshold)}", "primary", ev)


def _cond_price_near_high(period: int, within_pct: float) -> TriggerCondition:
    def ev(bars: List[dict]) -> TriggerResult:
        highs = _highs(bars)
        closes = _closes(bars)
        if len(highs) < period or not closes:
            return TriggerResult(False, f"Need {period}+ bars", None, None)
        high_n = max(highs[-period:])
        cur = closes[-1]
        gap = (high_n - cur) / high_n * 100.0
        passed = gap <= within_pct
        display = f"Current ${cur:.2f} vs {period}d high ${high_n:.2f} ({gap:.2f}% below)"
        dist = -(gap - within_pct) if not passed else None
        return TriggerResult(passed, display, dist, cur)
    return TriggerCondition(f"Price within {within_pct:.0f}% of {period}d high", "secondary", ev)


def _cond_macd_above_signal() -> TriggerCondition:
    def ev(bars: List[dict]) -> TriggerResult:
        closes = _closes(bars)
        if len(closes) < 36:
            return TriggerResult(False, "Need 36+ bars", None, None)
        e12, e26 = _ema(closes, 12), _ema(closes, 26)
        macd_series = [a - b for a, b in zip(e12, e26)]
        sig_series = _ema(macd_series, 9)
        macd, sig = macd_series[-1], sig_series[-1]
        passed = macd > sig
        display = f"MACD {macd:+.4f} vs signal {sig:+.4f}"
        dist = (sig - macd) / abs(sig) * 100.0 if not passed and sig != 0 else None
        return TriggerResult(passed, display, dist, macd)
    return TriggerCondition("MACD line > Signal line", "primary", ev)


def _cond_macd_hist_positive() -> TriggerCondition:
    def ev(bars: List[dict]) -> TriggerResult:
        closes = _closes(bars)
        if len(closes) < 36:
            return TriggerResult(False, "Need 36+ bars", None, None)
        e12, e26 = _ema(closes, 12), _ema(closes, 26)
        macd_series = [a - b for a, b in zip(e12, e26)]
        sig_series = _ema(macd_series, 9)
        hist = macd_series[-1] - sig_series[-1]
        passed = hist > 0
        display = f"MACD histogram = {hist:+.4f}"
        return TriggerResult(passed, display, None if passed else hist, hist)
    return TriggerCondition("MACD histogram positive", "primary", ev)


def _cond_macd_above_zero() -> TriggerCondition:
    def ev(bars: List[dict]) -> TriggerResult:
        closes = _closes(bars)
        if len(closes) < 36:
            return TriggerResult(False, "Need 36+ bars", None, None)
        e12, e26 = _ema(closes, 12), _ema(closes, 26)
        macd = e12[-1] - e26[-1]
        passed = macd > 0
        display = f"MACD = {macd:+.4f}"
        return TriggerResult(passed, display, None if passed else macd, macd)
    return TriggerCondition("MACD > 0", "secondary", ev)


def _cond_bb_width_compressed(lookback: int = 60, threshold_pct: float = 20.0) -> TriggerCondition:
    def ev(bars: List[dict]) -> TriggerResult:
        closes = _closes(bars)
        if len(closes) < lookback + 20:
            return TriggerResult(False, f"Need {lookback + 20}+ bars", None, None)
        cur_bw = _bb_width(closes)
        if cur_bw is None:
            return TriggerResult(False, "BB width unavailable", None, None)
        hist = []
        for offset in range(0, lookback, 1):
            sub = closes[: len(closes) - offset]
            w = _bb_width(sub)
            if w is not None:
                hist.append(w)
        if not hist:
            return TriggerResult(False, "No history", None, cur_bw)
        max_bw = max(hist)
        if max_bw == 0:
            return TriggerResult(False, "Max BB width = 0", None, cur_bw)
        pct_of_max = cur_bw / max_bw * 100.0
        passed = pct_of_max < threshold_pct
        display = f"BB width {cur_bw * 100:.2f}% of price; {pct_of_max:.1f}% of {lookback}d max"
        dist = (pct_of_max - threshold_pct) if not passed else None
        return TriggerResult(passed, display, dist, pct_of_max)
    return TriggerCondition(f"BB width at <{int(threshold_pct)}% of trailing {lookback}d max", "primary", ev)


def _cond_price_near_middle_band(sigma_mult: float = 0.5, period: int = 20) -> TriggerCondition:
    def ev(bars: List[dict]) -> TriggerResult:
        closes = _closes(bars)
        if len(closes) < period:
            return TriggerResult(False, f"Need {period}+ bars", None, None)
        window = closes[-period:]
        mid = mean(window)
        sd = stdev(window) if len(window) > 1 else 0.0
        cur = closes[-1]
        band = sigma_mult * sd
        passed = abs(cur - mid) <= band if band > 0 else False
        display = f"Price ${cur:.2f} vs middle band ${mid:.2f} (±{band:.2f})"
        dist = (abs(cur - mid) - band) / mid * 100.0 if not passed and mid > 0 else None
        return TriggerResult(passed, display, dist, cur - mid)
    return TriggerCondition(f"Price near middle band ±{sigma_mult}σ", "primary", ev)


def _cond_placeholder(strategy_id: str) -> TriggerCondition:
    def ev(bars: List[dict]) -> TriggerResult:
        cur = _closes(bars)[-1] if bars else None
        return TriggerResult(
            True,
            f"Logic-specific signal — TODO surface real conditions for {strategy_id}",
            None,
            cur,
        )
    return TriggerCondition("Logic-specific signal", "info", ev)


# ── Per-strategy trigger registry ─────────────────────────────────────────────

_REGISTRY: Dict[str, List[TriggerCondition]] = {
    "turtle_donchian_s2": [
        _cond_price_gt_donchian_high(55),
        _cond_sma_slope(200, 20),
        _cond_volume_multiple(1.5, 20),
        _cond_atr_threshold(1.0, 14),
    ],
    "turtle_donchian_s1": [
        _cond_price_gt_donchian_high(20),
        _cond_sma_slope(50, 10),
        _cond_volume_multiple(1.5, 20),
    ],
    "golden_cross": [
        _cond_sma_above(50, 200),
        _cond_sma_slope(50, 10),
        _cond_recent_crossover(50, 200, 5),
    ],
    "rsi_oversold": [
        _cond_rsi_below(30, 14),
        _cond_price_near_high(50, 5.0),
    ],
    "rsi2_mean_reversion": [
        _cond_rsi_below(10, 2),
        _cond_sma_above(1, 200),  # price > 200d
    ],
    "macd_crossover": [
        _cond_macd_above_signal(),
        _cond_macd_hist_positive(),
        _cond_macd_above_zero(),
    ],
    "bollinger_squeeze": [
        _cond_bb_width_compressed(60, 20.0),
        _cond_price_near_middle_band(0.5, 20),
    ],
    # Inferred defaults for other strategies referenced from the frontend config
    "momentum_breakout": [
        _cond_price_gt_donchian_high(20),
        _cond_volume_multiple(1.5, 20),
    ],
    "fifty_two_week_high_momentum": [
        _cond_price_near_high(252, 2.0),
        _cond_sma_above(50, 200),
    ],
    "cross_sectional_momentum": [
        _cond_sma_above(50, 200),
        _cond_sma_slope(50, 10),
    ],
    "cross_sectional_momentum_12_1": [
        _cond_sma_above(50, 200),
        _cond_sma_slope(50, 10),
    ],
    "crypto_quant_mean_reversion": [
        _cond_rsi_below(30, 14),
    ],
}


def get_trigger_conditions(strategy_id: str) -> List[TriggerCondition]:
    """Return the trigger spec for a strategy, falling back to a placeholder."""
    if strategy_id in _REGISTRY:
        return _REGISTRY[strategy_id]
    return [_cond_placeholder(strategy_id)]


def evaluate_checklist(strategy_id: str, bars: List[dict]) -> dict:
    """Run all conditions for `strategy_id` against `bars`. Returns JSON-ready dict."""
    conds = get_trigger_conditions(strategy_id)
    results = []
    primary_ok = True
    any_primary = False
    for c in conds:
        try:
            r = c.evaluate(bars)
        except Exception as e:
            r = TriggerResult(False, f"Evaluation error: {e}", None, None)
        results.append({
            "name": c.name,
            "weight": c.weight,
            "passed": bool(r.passed),
            "display": r.display,
            "distance_pct": r.distance_pct,
            "value": r.value,
        })
        if c.weight == "primary":
            any_primary = True
            if not r.passed:
                primary_ok = False
    status = "armed" if (any_primary and primary_ok) else "not_armed"
    return {"status": status, "conditions": results}
