from __future__ import annotations

from typing import Dict

import pandas as pd
import ta


def detect_golden_cross(df: pd.DataFrame) -> bool:
    """SMA50 crossed above SMA200 in the last bar."""
    if len(df) < 201:
        return False
    sma50 = df["close"].rolling(50).mean()
    sma200 = df["close"].rolling(200).mean()
    return bool(sma50.iloc[-2] < sma200.iloc[-2] and sma50.iloc[-1] > sma200.iloc[-1])


def detect_death_cross(df: pd.DataFrame) -> bool:
    """SMA50 crossed below SMA200 in the last bar."""
    if len(df) < 201:
        return False
    sma50 = df["close"].rolling(50).mean()
    sma200 = df["close"].rolling(200).mean()
    return bool(sma50.iloc[-2] > sma200.iloc[-2] and sma50.iloc[-1] < sma200.iloc[-1])


def detect_rsi_oversold(df: pd.DataFrame, threshold: float = 30.0) -> bool:
    """RSI(14) < threshold in the last bar."""
    if len(df) < 15:
        return False
    rsi = ta.momentum.RSIIndicator(df["close"], window=14).rsi()
    last = rsi.iloc[-1]
    if pd.isna(last):
        return False
    return bool(float(last) < threshold)


def detect_rsi_overbought(df: pd.DataFrame, threshold: float = 70.0) -> bool:
    """RSI(14) > threshold in the last bar."""
    if len(df) < 15:
        return False
    rsi = ta.momentum.RSIIndicator(df["close"], window=14).rsi()
    last = rsi.iloc[-1]
    if pd.isna(last):
        return False
    return bool(float(last) > threshold)


def detect_macd_bullish_crossover(df: pd.DataFrame) -> bool:
    """MACD line crossed above signal line (yesterday below, today above)."""
    if len(df) < 35:
        return False
    macd_obj = ta.trend.MACD(df["close"])
    line = macd_obj.macd()
    signal = macd_obj.macd_signal()
    if pd.isna(line.iloc[-1]) or pd.isna(line.iloc[-2]):
        return False
    return bool(line.iloc[-2] < signal.iloc[-2] and line.iloc[-1] > signal.iloc[-1])


def detect_macd_bearish_crossover(df: pd.DataFrame) -> bool:
    """MACD line crossed below signal line (yesterday above, today below)."""
    if len(df) < 35:
        return False
    macd_obj = ta.trend.MACD(df["close"])
    line = macd_obj.macd()
    signal = macd_obj.macd_signal()
    if pd.isna(line.iloc[-1]) or pd.isna(line.iloc[-2]):
        return False
    return bool(line.iloc[-2] > signal.iloc[-2] and line.iloc[-1] < signal.iloc[-1])


def detect_volume_breakout(df: pd.DataFrame, multiplier: float = 2.0) -> bool:
    """Volume in last bar > multiplier × mean volume of prior 20 bars."""
    if len(df) < 22:
        return False
    avg_volume = df["volume"].iloc[-21:-1].mean()
    if avg_volume == 0:
        return False
    return bool(float(df["volume"].iloc[-1]) > multiplier * avg_volume)


def detect_52w_breakout(df: pd.DataFrame) -> bool:
    """Close in last bar > 52-week high of prior bars (needs ≥254 bars)."""
    if len(df) < 254:
        return False
    prior_high = df["close"].iloc[-253:-1].max()
    return bool(float(df["close"].iloc[-1]) > prior_high)


SIGNAL_DETECTORS: Dict[str, object] = {
    "golden_cross": detect_golden_cross,
    "death_cross": detect_death_cross,
    "rsi_oversold": detect_rsi_oversold,
    "rsi_overbought": detect_rsi_overbought,
    "macd_bull": detect_macd_bullish_crossover,
    "macd_bear": detect_macd_bearish_crossover,
    "volume_breakout": detect_volume_breakout,
    "breakout_52w": detect_52w_breakout,
}


def run_all_signals(df: pd.DataFrame) -> Dict[str, bool]:
    """Return ``{signal_type: bool}`` for all registered signal detectors."""
    return {name: fn(df) for name, fn in SIGNAL_DETECTORS.items()}  # type: ignore[operator]
