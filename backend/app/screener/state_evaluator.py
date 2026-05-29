from __future__ import annotations

"""
Per-strategy state evaluator for the ticker scanner.

evaluate_all(symbol, df, trade_map) → list of StrategyStateResult

States:
  active         — signal firing now OR open position still valid
  forming        — within ~5% / ~5 indicator units of triggering
  idle           — no signal, not close
  exit_triggered — open position where stop/target has been breached
"""

from dataclasses import dataclass
from typing import Dict, List, Literal, Optional, Any

import pandas as pd
import ta

from app.screener.entry_triggers import TRIGGER_MAP
from app.screener.daily_runner import PRESET_LABELS

ALL_PRESETS: List[str] = list(TRIGGER_MAP.keys())

State = Literal["active", "forming", "idle", "exit_triggered"]

STATE_ORDER = {"exit_triggered": 0, "active": 1, "forming": 2, "idle": 3}


@dataclass
class StrategyStateResult:
    preset_key: str
    preset_label: str
    state: State
    distance_pct: Optional[float]
    days_to_trigger: Optional[int]
    status_message: str
    key_value: Optional[float]
    key_label: Optional[str]
    # Trade fields (only when open/candidate trade exists)
    trade_id: Optional[int]
    entry_price: Optional[float]
    current_price: Optional[float]
    stop_price: Optional[float]
    target_price: Optional[float]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_rsi(df: pd.DataFrame) -> Optional[pd.Series]:
    if len(df) < 16:
        return None
    return ta.momentum.RSIIndicator(df["close"], window=14).rsi()


def _ema(df: pd.DataFrame, span: int) -> pd.Series:
    return df["close"].ewm(span=span, adjust=False).mean()


def _sma(df: pd.DataFrame, window: int) -> pd.Series:
    return df["close"].rolling(window).mean()


def _project_days(distance: float, daily_rate: float, cap: int = 14) -> Optional[int]:
    """Project trading days to close a gap given daily rate of change."""
    if daily_rate <= 0 or distance <= 0:
        return None
    days = int(distance / daily_rate) + 1
    return days if days <= cap else None


# ---------------------------------------------------------------------------
# Individual evaluators
# ---------------------------------------------------------------------------

def _eval_breakout(df: pd.DataFrame, lookback: int = 5) -> dict:
    """Used by canslim_leaders, stage2_breakout, momentum_surge, breakout_52w, darvas_box."""
    if len(df) < lookback + 3:
        return {"state": "idle", "distance_pct": None, "days_to_trigger": None,
                "status_message": "Not enough data", "key_value": None, "key_label": None}

    recent_high = df["close"].iloc[-(lookback + 1):-1].max()
    close = float(df["close"].iloc[-1])
    today_vol = float(df["volume"].iloc[-1])
    avg_vol = float(df["volume"].iloc[-22:-1].mean()) if len(df) >= 23 else float(df["volume"].mean())
    vol_ratio = today_vol / avg_vol if avg_vol > 0 else 1.0

    distance_pct = (recent_high - close) / close * 100

    # Active: close above recent high with volume
    if close > recent_high and vol_ratio >= 1.3:
        return {"state": "active", "distance_pct": 0.0, "days_to_trigger": None,
                "status_message": f"Breakout firing · close above {lookback}d high on volume ({vol_ratio:.1f}×)",
                "key_value": round(vol_ratio, 2), "key_label": "Volume ratio"}

    # Forming: within 5%
    if 0 <= distance_pct <= 5.0:
        avg_daily = float(df["close"].pct_change().iloc[-5:].mean() * 100) if len(df) >= 5 else 0.0
        days = _project_days(distance_pct, avg_daily) if avg_daily > 0 else None
        vol_note = f" · volume {vol_ratio:.1f}× avg" if vol_ratio >= 1.0 else ""
        return {"state": "forming", "distance_pct": round(distance_pct, 2), "days_to_trigger": days,
                "status_message": f"{distance_pct:.1f}% from {lookback}d high{vol_note}",
                "key_value": round(distance_pct, 2), "key_label": f"% from {lookback}d high"}

    return {"state": "idle", "distance_pct": round(distance_pct, 2), "days_to_trigger": None,
            "status_message": f"{distance_pct:.1f}% below {lookback}d high",
            "key_value": round(distance_pct, 2), "key_label": f"% from {lookback}d high"}


def _eval_turtle(df: pd.DataFrame) -> dict:
    if len(df) < 60:
        return {"state": "idle", "distance_pct": None, "days_to_trigger": None,
                "status_message": "Not enough data", "key_value": None, "key_label": None}
    channel_high = float(df["high"].iloc[-56:-1].max())
    close = float(df["close"].iloc[-1])
    distance_pct = (channel_high - close) / close * 100

    if close > channel_high:
        return {"state": "active", "distance_pct": 0.0, "days_to_trigger": None,
                "status_message": "55-day channel breakout firing",
                "key_value": 0.0, "key_label": "% from 55d high"}

    if 0 <= distance_pct <= 5.0:
        avg_daily = float(df["close"].pct_change().iloc[-5:].mean() * 100)
        days = _project_days(distance_pct, avg_daily)
        return {"state": "forming", "distance_pct": round(distance_pct, 2), "days_to_trigger": days,
                "status_message": f"{distance_pct:.1f}% from 55d channel high",
                "key_value": round(distance_pct, 2), "key_label": "% from 55d high"}

    return {"state": "idle", "distance_pct": round(distance_pct, 2), "days_to_trigger": None,
            "status_message": f"{distance_pct:.1f}% below 55d channel high",
            "key_value": round(distance_pct, 2), "key_label": "% from 55d high"}


def _eval_rsi_recovery(df: pd.DataFrame, threshold: float, filter_threshold: float) -> dict:
    """Used by mean_reversion_quality (35/40), deep_value_bounce (32/35), rsi_oversold (32/30)."""
    rsi = _safe_rsi(df)
    if rsi is None:
        return {"state": "idle", "distance_pct": None, "days_to_trigger": None,
                "status_message": "Not enough data", "key_value": None, "key_label": None}

    current_rsi = float(rsi.iloc[-1])
    prev_rsi = float(rsi.iloc[-2])

    # Active: RSI just crossed upward through threshold
    if prev_rsi < threshold and current_rsi >= threshold:
        return {"state": "active", "distance_pct": None, "days_to_trigger": None,
                "status_message": f"RSI crossed above {threshold:.0f} — momentum turning up (RSI {current_rsi:.1f})",
                "key_value": round(current_rsi, 1), "key_label": "RSI"}

    # Forming: in the oversold zone (below filter_threshold), approaching trigger
    forming_low = threshold - 10
    if forming_low <= current_rsi < filter_threshold:
        rsi_slope = (float(rsi.iloc[-1]) - float(rsi.iloc[-6])) / 5 if len(rsi) >= 6 else 0.0
        gap = threshold - current_rsi
        days: Optional[int] = None
        if rsi_slope > 0:
            days = _project_days(gap, rsi_slope)
        direction = "↑ rising" if rsi_slope > 0 else ("↓ falling" if rsi_slope < 0 else "→ flat")
        return {"state": "forming", "distance_pct": None, "days_to_trigger": days,
                "status_message": f"RSI {current_rsi:.1f} → needs to cross {threshold:.0f} ({direction})",
                "key_value": round(current_rsi, 1), "key_label": "RSI"}

    # Idle
    return {"state": "idle", "distance_pct": None, "days_to_trigger": None,
            "status_message": f"RSI {current_rsi:.1f} — not in oversold range (needs < {filter_threshold:.0f})",
            "key_value": round(current_rsi, 1), "key_label": "RSI"}


def _eval_ema_pullback(df: pd.DataFrame) -> dict:
    if len(df) < 25:
        return {"state": "idle", "distance_pct": None, "days_to_trigger": None,
                "status_message": "Not enough data", "key_value": None, "key_label": None}

    ema21 = float(_ema(df, 21).iloc[-1])
    close = float(df["close"].iloc[-1])
    low = float(df["low"].iloc[-1])
    open_ = float(df["open"].iloc[-1])

    pct_above = (close - ema21) / ema21 * 100

    # Active: touched EMA21, green candle, closes above
    if low <= ema21 * 1.015 and close > open_ and close > ema21:
        return {"state": "active", "distance_pct": round(pct_above, 2), "days_to_trigger": None,
                "status_message": f"Pulling back to EMA21 · green candle above EMA (EMA21 ${ema21:.2f})",
                "key_value": round(pct_above, 2), "key_label": "% above EMA21"}

    # Forming: within 6% above EMA21
    if 1.5 < pct_above <= 6.0:
        avg_daily_drop = float(-df["close"].pct_change().iloc[-5:].clip(upper=0).mean() * 100)
        days = _project_days(pct_above - 1.5, avg_daily_drop) if avg_daily_drop > 0 else None
        return {"state": "forming", "distance_pct": round(pct_above, 2), "days_to_trigger": days,
                "status_message": f"Price {pct_above:.1f}% above EMA21 — approaching pullback zone",
                "key_value": round(pct_above, 2), "key_label": "% above EMA21"}

    if pct_above <= 1.5:
        return {"state": "idle", "distance_pct": round(pct_above, 2), "days_to_trigger": None,
                "status_message": f"Price at/below EMA21 ({pct_above:.1f}%) — needs uptrend",
                "key_value": round(pct_above, 2), "key_label": "% above EMA21"}

    return {"state": "idle", "distance_pct": round(pct_above, 2), "days_to_trigger": None,
            "status_message": f"Price {pct_above:.1f}% above EMA21 — too extended from pullback zone",
            "key_value": round(pct_above, 2), "key_label": "% above EMA21"}


def _eval_squeeze(df: pd.DataFrame) -> dict:
    if len(df) < 22:
        return {"state": "idle", "distance_pct": None, "days_to_trigger": None,
                "status_message": "Not enough data", "key_value": None, "key_label": None}

    bb = ta.volatility.BollingerBands(df["close"], window=20, window_dev=2)
    bb_width = float((bb.bollinger_hband().iloc[-1] - bb.bollinger_lband().iloc[-1]) / bb.bollinger_mavg().iloc[-1] * 100)
    range_high = float(df["high"].iloc[-11:-1].max())
    close = float(df["close"].iloc[-1])
    gap_pct = (range_high - close) / close * 100

    if bb_width < 5.0 and close > range_high:
        return {"state": "active", "distance_pct": None, "days_to_trigger": None,
                "status_message": f"Squeeze breakout firing · BB width {bb_width:.1f}%",
                "key_value": round(bb_width, 2), "key_label": "BB width %"}

    if bb_width < 8.0 and gap_pct <= 3.0:
        return {"state": "forming", "distance_pct": round(gap_pct, 2), "days_to_trigger": None,
                "status_message": f"Squeeze tightening · BB width {bb_width:.1f}% · {gap_pct:.1f}% from range high",
                "key_value": round(bb_width, 2), "key_label": "BB width %"}

    return {"state": "idle", "distance_pct": None, "days_to_trigger": None,
            "status_message": f"No squeeze · BB width {bb_width:.1f}% (needs < 5%)",
            "key_value": round(bb_width, 2), "key_label": "BB width %"}


def _eval_zscore(df: pd.DataFrame) -> dict:
    if len(df) < 22:
        return {"state": "idle", "distance_pct": None, "days_to_trigger": None,
                "status_message": "Not enough data", "key_value": None, "key_label": None}

    ma = df["close"].rolling(20).mean()
    std = df["close"].rolling(20).std()
    z = (df["close"] - ma) / std

    current_z = float(z.iloc[-1])
    prev_z = float(z.iloc[-2])

    if pd.isna(current_z) or pd.isna(prev_z):
        return {"state": "idle", "distance_pct": None, "days_to_trigger": None,
                "status_message": "Not enough data", "key_value": None, "key_label": None}

    if prev_z < -2.0 and current_z > -1.5:
        return {"state": "active", "distance_pct": None, "days_to_trigger": None,
                "status_message": f"Z-score recovery firing · crossed from {prev_z:.2f} to {current_z:.2f}",
                "key_value": round(current_z, 2), "key_label": "Z-Score"}

    if -2.5 <= current_z <= -1.5:
        return {"state": "forming", "distance_pct": None, "days_to_trigger": None,
                "status_message": f"Z-score {current_z:.2f} — in reversion zone (needs to cross above -1.5)",
                "key_value": round(current_z, 2), "key_label": "Z-Score"}

    return {"state": "idle", "distance_pct": None, "days_to_trigger": None,
            "status_message": f"Z-score {current_z:.2f} — not in extreme oversold range",
            "key_value": round(current_z, 2), "key_label": "Z-Score"}


def _eval_golden_cross(df: pd.DataFrame) -> dict:
    if len(df) < 205:
        return {"state": "idle", "distance_pct": None, "days_to_trigger": None,
                "status_message": "Not enough data (need 200d history)", "key_value": None, "key_label": None}

    sma50 = _sma(df, 50)
    sma200 = _sma(df, 200)
    s50 = float(sma50.iloc[-1])
    s200 = float(sma200.iloc[-1])
    s50_prev = float(sma50.iloc[-2])
    s200_prev = float(sma200.iloc[-2])

    gap_pct = (s200 - s50) / s200 * 100  # positive = 50MA below 200MA

    # Just crossed
    if s50_prev < s200_prev and s50 >= s200:
        return {"state": "active", "distance_pct": 0.0, "days_to_trigger": None,
                "status_message": "Golden Cross firing · 50MA just crossed above 200MA",
                "key_value": 0.0, "key_label": "50MA vs 200MA gap %"}

    # 50MA already above 200MA (cross already happened)
    if s50 >= s200:
        return {"state": "idle", "distance_pct": round(-gap_pct, 2), "days_to_trigger": None,
                "status_message": f"50MA already above 200MA by {abs(gap_pct):.1f}% — cross already confirmed",
                "key_value": round(-gap_pct, 2), "key_label": "50MA vs 200MA gap %"}

    # Forming: 50MA within 3% below 200MA
    if 0 < gap_pct <= 3.0:
        gap_slope = float((sma50 - sma200).diff().iloc[-20:].mean()) if len(df) >= 20 else 0.0
        daily_close_rate = abs(gap_slope / s200 * 100) if s200 > 0 else 0.0
        days = _project_days(gap_pct, daily_close_rate) if daily_close_rate > 0 else None
        return {"state": "forming", "distance_pct": round(gap_pct, 2), "days_to_trigger": days,
                "status_message": f"50MA {gap_pct:.1f}% below 200MA — approaching golden cross",
                "key_value": round(gap_pct, 2), "key_label": "50MA vs 200MA gap %"}

    return {"state": "idle", "distance_pct": round(gap_pct, 2), "days_to_trigger": None,
            "status_message": f"50MA {gap_pct:.1f}% below 200MA — no cross imminent",
            "key_value": round(gap_pct, 2), "key_label": "50MA vs 200MA gap %"}


def _eval_macd(df: pd.DataFrame) -> dict:
    if len(df) < 35:
        return {"state": "idle", "distance_pct": None, "days_to_trigger": None,
                "status_message": "Not enough data", "key_value": None, "key_label": None}

    macd_ind = ta.trend.MACD(df["close"], window_slow=26, window_fast=12, window_sign=9)
    macd_line = macd_ind.macd()
    signal_line = macd_ind.macd_signal()
    m = float(macd_line.iloc[-1])
    s = float(signal_line.iloc[-1])
    m_prev = float(macd_line.iloc[-2])
    s_prev = float(signal_line.iloc[-2])

    if pd.isna(m) or pd.isna(s):
        return {"state": "idle", "distance_pct": None, "days_to_trigger": None,
                "status_message": "Not enough data", "key_value": None, "key_label": None}

    # Just crossed
    if m_prev < s_prev and m >= s:
        return {"state": "active", "distance_pct": None, "days_to_trigger": None,
                "status_message": f"MACD crossover firing · MACD {m:.3f} crossed above signal {s:.3f}",
                "key_value": round(m - s, 4), "key_label": "MACD vs Signal"}

    gap = s - m  # positive when MACD below signal
    ref = abs(s) if s != 0 else 1.0
    gap_pct_of_signal = gap / ref * 100

    if 0 < gap_pct_of_signal <= 3.0:
        return {"state": "forming", "distance_pct": None, "days_to_trigger": None,
                "status_message": f"MACD {m:.3f} approaching signal {s:.3f} — {gap_pct_of_signal:.1f}% below",
                "key_value": round(m - s, 4), "key_label": "MACD vs Signal"}

    return {"state": "idle", "distance_pct": None, "days_to_trigger": None,
            "status_message": f"MACD {m:.3f} · Signal {s:.3f} · gap {gap:.3f}",
            "key_value": round(m - s, 4), "key_label": "MACD vs Signal"}


def _eval_momentum_12m(df: pd.DataFrame) -> dict:
    if len(df) < 252:
        return {"state": "idle", "distance_pct": None, "days_to_trigger": None,
                "status_message": "Not enough data (need 12m history)", "key_value": None, "key_label": None}

    ret_12m = float((df["close"].iloc[-1] / df["close"].iloc[-252] - 1) * 100)
    close = float(df["close"].iloc[-1])
    sma200 = float(_sma(df, 200).iloc[-1])
    rsi = _safe_rsi(df)
    rsi_val = float(rsi.iloc[-1]) if rsi is not None else 50.0

    above_200 = close > sma200
    rsi_ok = rsi_val > 50
    ret_ok = ret_12m > 20.0

    conditions_met = sum([above_200, rsi_ok, ret_ok])

    if conditions_met == 3:
        return {"state": "active", "distance_pct": None, "days_to_trigger": None,
                "status_message": f"All conditions met · 12m return {ret_12m:.1f}% · RSI {rsi_val:.0f}",
                "key_value": round(ret_12m, 1), "key_label": "12m Return %"}

    if conditions_met >= 2:
        missing = []
        if not ret_ok: missing.append(f"12m return {ret_12m:.1f}% (needs >20%)")
        if not above_200: missing.append(f"price below 200MA")
        if not rsi_ok: missing.append(f"RSI {rsi_val:.0f} (needs >50)")
        return {"state": "forming", "distance_pct": None, "days_to_trigger": None,
                "status_message": f"2/3 conditions · missing: {missing[0]}",
                "key_value": round(ret_12m, 1), "key_label": "12m Return %"}

    return {"state": "idle", "distance_pct": None, "days_to_trigger": None,
            "status_message": f"12m return {ret_12m:.1f}% · RSI {rsi_val:.0f} · {conditions_met}/3 conditions",
            "key_value": round(ret_12m, 1), "key_label": "12m Return %"}


def _eval_high_rs_momentum(df: pd.DataFrame) -> dict:
    if len(df) < 252:
        return {"state": "idle", "distance_pct": None, "days_to_trigger": None,
                "status_message": "Not enough data", "key_value": None, "key_label": None}

    close = float(df["close"].iloc[-1])
    high_52w = float(df["high"].iloc[-252:].max())
    rel_high_pct = close / high_52w * 100
    rsi = _safe_rsi(df)
    rsi_val = float(rsi.iloc[-1]) if rsi is not None else 50.0
    green_days = int(sum(df["close"].iloc[-2] > df["open"].iloc[-2] for _ in [None]))
    # Count last 2 consecutive closes up
    recent_gains = sum(1 for i in range(-3, -1) if df["close"].iloc[i] > df["close"].iloc[i-1])

    rs_ok = rel_high_pct >= 85
    rsi_ok = rsi_val > 55
    gains_ok = recent_gains >= 2

    conditions_met = sum([rs_ok, rsi_ok, gains_ok])

    if conditions_met == 3:
        return {"state": "active", "distance_pct": None, "days_to_trigger": None,
                "status_message": f"All conditions met · {rel_high_pct:.0f}% of 52w high · RSI {rsi_val:.0f}",
                "key_value": round(rel_high_pct, 1), "key_label": "% of 52w High"}

    if conditions_met >= 2:
        return {"state": "forming", "distance_pct": None, "days_to_trigger": None,
                "status_message": f"{conditions_met}/3 conditions · {rel_high_pct:.0f}% of 52w high · RSI {rsi_val:.0f}",
                "key_value": round(rel_high_pct, 1), "key_label": "% of 52w High"}

    return {"state": "idle", "distance_pct": None, "days_to_trigger": None,
            "status_message": f"{rel_high_pct:.0f}% of 52w high · RSI {rsi_val:.0f} · {conditions_met}/3 conditions",
            "key_value": round(rel_high_pct, 1), "key_label": "% of 52w High"}


def _eval_consecutive_gains(df: pd.DataFrame) -> dict:
    if len(df) < 10:
        return {"state": "idle", "distance_pct": None, "days_to_trigger": None,
                "status_message": "Not enough data", "key_value": None, "key_label": None}

    # Count consecutive green closes from end
    streak = 0
    for i in range(-1, -min(10, len(df)), -1):
        if df["close"].iloc[i] > df["close"].iloc[i - 1]:
            streak += 1
        else:
            break

    rsi = _safe_rsi(df)
    rsi_val = float(rsi.iloc[-1]) if rsi is not None else 50.0

    if streak >= 3 and rsi_val > 40:
        return {"state": "active", "distance_pct": None, "days_to_trigger": None,
                "status_message": f"{streak} consecutive up-closes · RSI {rsi_val:.0f}",
                "key_value": float(streak), "key_label": "Consecutive gains"}

    if streak == 2 and rsi_val > 40:
        return {"state": "forming", "distance_pct": None, "days_to_trigger": None,
                "status_message": f"{streak}/3 consecutive gains · needs one more up-close",
                "key_value": float(streak), "key_label": "Consecutive gains"}

    return {"state": "idle", "distance_pct": None, "days_to_trigger": None,
            "status_message": f"{streak} consecutive up-closes (needs ≥3 + RSI>{40})",
            "key_value": float(streak), "key_label": "Consecutive gains"}


def _eval_volume_surge(df: pd.DataFrame) -> dict:
    if len(df) < 22:
        return {"state": "idle", "distance_pct": None, "days_to_trigger": None,
                "status_message": "Not enough data", "key_value": None, "key_label": None}

    avg_vol = float(df["volume"].iloc[-22:-1].mean())
    today_vol = float(df["volume"].iloc[-1])
    vol_ratio = today_vol / avg_vol if avg_vol > 0 else 1.0
    up_day = df["close"].iloc[-1] > df["open"].iloc[-1]

    if vol_ratio >= 2.0 and up_day:
        return {"state": "active", "distance_pct": None, "days_to_trigger": None,
                "status_message": f"Volume surge firing · {vol_ratio:.1f}× avg on up-day",
                "key_value": round(vol_ratio, 2), "key_label": "Volume ratio"}

    if vol_ratio >= 1.5:
        return {"state": "forming", "distance_pct": None, "days_to_trigger": None,
                "status_message": f"Volume building · {vol_ratio:.1f}× avg (needs 2×+ on up-day)",
                "key_value": round(vol_ratio, 2), "key_label": "Volume ratio"}

    return {"state": "idle", "distance_pct": None, "days_to_trigger": None,
            "status_message": f"Normal volume · {vol_ratio:.1f}× avg",
            "key_value": round(vol_ratio, 2), "key_label": "Volume ratio"}


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

def _evaluate_single(preset_key: str, df: pd.DataFrame) -> dict:
    """Run the correct evaluator for a given preset."""
    k = preset_key
    if k in ("canslim_leaders", "stage2_breakout", "momentum_surge", "breakout_52w"):
        return _eval_breakout(df, lookback=5)
    if k == "darvas_box":
        return _eval_breakout(df, lookback=5)
    if k == "turtle_breakout":
        return _eval_turtle(df)
    if k == "mean_reversion_quality":
        return _eval_rsi_recovery(df, threshold=35.0, filter_threshold=40.0)
    if k in ("deep_value_bounce", "rsi_oversold"):
        return _eval_rsi_recovery(df, threshold=32.0, filter_threshold=35.0)
    if k in ("power_trend", "ema_stack_uptrend"):
        return _eval_ema_pullback(df)
    if k == "volatility_contraction":
        return _eval_squeeze(df)
    if k == "zscore_reversion":
        return _eval_zscore(df)
    if k == "golden_cross":
        return _eval_golden_cross(df)
    if k == "macd_bullish":
        return _eval_macd(df)
    if k == "momentum_12m":
        return _eval_momentum_12m(df)
    if k == "high_rs_momentum":
        return _eval_high_rs_momentum(df)
    if k == "consecutive_gains":
        return _eval_consecutive_gains(df)
    if k == "volume_surge":
        return _eval_volume_surge(df)
    return {"state": "idle", "distance_pct": None, "days_to_trigger": None,
            "status_message": "No evaluator defined", "key_value": None, "key_label": None}


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def evaluate_all(
    symbol: str,
    df: pd.DataFrame,
    trade_map: Dict[str, Any],  # preset_key → StrategyTrade ORM object (open or candidate)
    current_price: Optional[float] = None,
) -> List[StrategyStateResult]:
    """
    Evaluate all 19 strategies for a single symbol.
    trade_map: {preset_key: StrategyTrade} for open/candidate trades on this symbol.
    """
    results: List[StrategyStateResult] = []

    for preset_key in ALL_PRESETS:
        label = PRESET_LABELS.get(preset_key, preset_key)
        trade = trade_map.get(preset_key)

        # Compute indicator-based state
        try:
            base = _evaluate_single(preset_key, df)
        except Exception as e:
            base = {"state": "idle", "distance_pct": None, "days_to_trigger": None,
                    "status_message": f"Error: {e}", "key_value": None, "key_label": None}

        state: State = base["state"]
        status_message: str = base["status_message"]
        trade_id = None
        entry_price = None
        cp = current_price
        stop_price = None
        target_price = None

        if trade is not None:
            trade_id = trade.id
            entry_price = trade.entry_price if trade.entry_price and trade.entry_price > 0 else None
            stop_price = trade.stop_price if trade.stop_price and trade.stop_price > 0 else None
            target_price = trade.target_price if trade.target_price and trade.target_price > 0 else None
            cp = current_price or trade.last_known_price

            if trade.status == "open" and entry_price:
                pnl_pct = ((cp - entry_price) / entry_price * 100) if cp else None
                pnl_str = f" · {pnl_pct:+.1f}%" if pnl_pct is not None else ""
                # Check exit conditions
                if cp and stop_price and cp <= stop_price:
                    state = "exit_triggered"
                    status_message = f"Stop hit at ${stop_price:.2f}{pnl_str} · Entry ${entry_price:.2f}"
                elif cp and target_price and cp >= target_price:
                    state = "exit_triggered"
                    status_message = f"Target reached at ${target_price:.2f}{pnl_str} · Entry ${entry_price:.2f}"
                else:
                    state = "active"
                    status_message = f"Long {trade.shares:.0f}sh{pnl_str} · Entry ${entry_price:.2f}"
                    if stop_price:
                        status_message += f" · Stop ${stop_price:.2f}"

            elif trade.status == "candidate":
                # Candidate: trigger-based state already computed; mark as forming at minimum
                if state == "idle":
                    state = "forming"
                    status_message = f"On watchlist — waiting for trigger"

        results.append(StrategyStateResult(
            preset_key=preset_key,
            preset_label=label,
            state=state,
            distance_pct=base["distance_pct"],
            days_to_trigger=base["days_to_trigger"],
            status_message=status_message,
            key_value=base["key_value"],
            key_label=base["key_label"],
            trade_id=trade_id,
            entry_price=entry_price,
            current_price=cp,
            stop_price=stop_price,
            target_price=target_price,
        ))

    results.sort(key=lambda r: STATE_ORDER[r.state])
    return results
