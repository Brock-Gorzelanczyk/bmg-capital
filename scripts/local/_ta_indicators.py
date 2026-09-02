"""Native pandas technical indicators — no external deps beyond pandas+numpy.

Every function takes a pandas.DataFrame with columns: open, high, low, close, volume.
Returns a Series or dict of Series that can be attached back to the bars frame.

Reference: canonical formulas from Kaufman *Trading Systems and Methods* 6e.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index (Wilder's smoothing). Returns 0-100."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    # Wilder's smoothing = EWM with alpha = 1/period
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return (100 - (100 / (1 + rs))).fillna(50)


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    """MACD line, signal line, histogram. Standard 12/26/9 params."""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    sig_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - sig_line
    return {"macd": macd_line, "signal": sig_line, "hist": hist}


def bollinger_bands(close: pd.Series, period: int = 20, std_mult: float = 2.0) -> dict:
    """Bollinger Bands. Returns middle (SMA), upper, lower, and %B position."""
    ma = close.rolling(period).mean()
    sd = close.rolling(period).std()
    upper = ma + std_mult * sd
    lower = ma - std_mult * sd
    # %B: where price sits within the bands. 0 = lower, 1 = upper.
    pct_b = (close - lower) / (upper - lower).replace(0, np.nan)
    # Bandwidth: (upper - lower) / middle — tightens before breakouts
    bw = (upper - lower) / ma.replace(0, np.nan)
    return {"middle": ma, "upper": upper, "lower": lower, "pct_b": pct_b, "bandwidth": bw}


def vwap(df: pd.DataFrame) -> pd.Series:
    """Volume-weighted average price. Session-level (resets daily in intraday use).
    For daily bars this is cumulative; for intraday, group by day and cumulate.
    """
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    pv = typical * df["volume"]
    if isinstance(df.index, pd.DatetimeIndex):
        # Reset VWAP at session boundaries (per day)
        day = df.index.date
        cumpv = pd.Series(pv.values, index=df.index).groupby(day).cumsum()
        cumvol = pd.Series(df["volume"].values, index=df.index).groupby(day).cumsum()
        return cumpv / cumvol.replace(0, np.nan)
    # Non-datetime index: cumulative
    return pv.cumsum() / df["volume"].cumsum().replace(0, np.nan)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range (Wilder). For stop-loss + volatility sizing."""
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low).abs(),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def stoch(df: pd.DataFrame, k_period: int = 14, d_period: int = 3) -> dict:
    """Stochastic oscillator %K and %D."""
    low_k = df["low"].rolling(k_period).min()
    high_k = df["high"].rolling(k_period).max()
    k = 100 * (df["close"] - low_k) / (high_k - low_k).replace(0, np.nan)
    d = k.rolling(d_period).mean()
    return {"k": k, "d": d}


def compute_all(df: pd.DataFrame) -> pd.DataFrame:
    """Attach a standard indicator bundle to a bars frame.

    Adds columns: rsi_14, macd, macd_signal, macd_hist, bb_upper, bb_lower, bb_pct_b,
    bb_bandwidth, vwap, atr_14, sma_20, sma_50, ema_20, ema_50, stoch_k, stoch_d.
    """
    out = df.copy()
    out["rsi_14"] = rsi(df["close"], 14)
    m = macd(df["close"])
    out["macd"] = m["macd"]
    out["macd_signal"] = m["signal"]
    out["macd_hist"] = m["hist"]
    bb = bollinger_bands(df["close"])
    out["bb_upper"] = bb["upper"]
    out["bb_lower"] = bb["lower"]
    out["bb_pct_b"] = bb["pct_b"]
    out["bb_bandwidth"] = bb["bandwidth"]
    out["vwap"] = vwap(df)
    out["atr_14"] = atr(df)
    out["sma_20"] = sma(df["close"], 20)
    out["sma_50"] = sma(df["close"], 50)
    out["ema_20"] = ema(df["close"], 20)
    out["ema_50"] = ema(df["close"], 50)
    st = stoch(df)
    out["stoch_k"] = st["k"]
    out["stoch_d"] = st["d"]
    return out
