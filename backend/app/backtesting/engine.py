"""
Backtesting engine for all 19 Strategy Lab strategies.

Uses a fixed 150-stock liquid universe, downloads 3 years of daily data from
yfinance in a single batch call, generates per-strategy entry signals with
vectorised pandas/ta operations, then simulates a paper portfolio day-by-day.

Portfolio rules (mirror live trading):
  - $100 000 starting capital
  - $5 000 per position (5 % allocation)
  - Max 20 concurrent positions
  - Stop loss  : -8 %  (vs entry close)
  - Profit target: +20 % (vs entry close)
  - Time exit  : 30 calendar days
  - Entry      : next-day open after signal
  - Exits      : checked at daily close
"""
from __future__ import annotations

import json
import logging
import math
import os
from dataclasses import dataclass, field
from datetime import timezone, date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

# ── Universe ──────────────────────────────────────────────────────────────────

BACKTEST_UNIVERSE: List[str] = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK-B", "JPM",
    "JNJ", "V", "WMT", "MA", "PG", "XOM", "HD", "CVX", "MRK", "LLY", "PEP",
    "KO", "ABBV", "PFE", "COST", "AVGO", "TMO", "ACN", "MCD", "NEE", "TXN",
    "NFLX", "QCOM", "AMD", "INTU", "AMAT", "CRM", "NOW", "ADBE", "ORCL", "PANW",
    "UNH", "CAT", "DE", "ETN", "HON", "BA", "GE", "LMT", "RTX", "FDX",
    "BAC", "WFC", "GS", "MS", "BLK", "SCHW", "AXP", "USB", "COF", "PNC",
    "T", "VZ", "TMUS", "AMT", "CCI", "EQIX", "PLD", "SPG", "O", "WELL",
    "SBUX", "NKE", "LOW", "TGT", "BKNG", "ABNB", "UBER", "LYFT", "SNAP", "PINS",
    "PYPL", "SQ", "COIN", "HOOD", "SOFI", "AFRM", "UPST", "LC", "NU", "ALLY",
    "ENPH", "FSLR", "PLUG", "BE", "SEDG", "RUN", "ARRY", "NOVA", "MAXN", "CSIQ",
    "DXCM", "ISRG", "MDT", "BSX", "EW", "SYK", "ZBH", "HOLX", "IDXX", "ALGN",
    "CELH", "MNST", "TAP", "STZ", "MO", "PM", "BTI", "BUD", "SAM", "DEO",
    "CLX", "CHD", "EL", "ULTA", "LULU", "ROST", "TJX", "DECK", "SKX", "VFC",
    "DAL", "UAL", "AAL", "LUV", "ALK", "CCL", "RCL", "NCLH", "MAR", "HLT",
    "FCX", "NEM", "GOLD", "WPM", "AEM", "KGC", "AG", "HL", "EXK", "CDE",
    "XLE", "XLF", "XLK", "XLV", "XLI", "XLY", "XLP", "QQQ", "IWM", "SPY",
]

PRESET_LABELS: Dict[str, str] = {
    "canslim_leaders":        "CAN SLIM Leaders",
    "stage2_breakout":        "Stage 2 Breakout",
    "momentum_surge":         "Momentum Surge",
    "high_rs_momentum":       "High RS Leaders",
    "power_trend":            "Power Trend",
    "turtle_breakout":        "Turtle Breakout",
    "momentum_12m":           "12-Month Momentum",
    "darvas_box":             "Darvas Box",
    "mean_reversion_quality": "Quality Dip Buy",
    "deep_value_bounce":      "Quality Oversold",
    "rsi_oversold":           "RSI Oversold",
    "zscore_reversion":       "Z-Score Reversion",
    "volatility_contraction": "Volatility Squeeze",
    "ema_stack_uptrend":      "EMA Stack",
    "consecutive_gains":      "Momentum Continuation",
    "golden_cross":           "Golden Cross",
    "macd_bullish":           "MACD Crossover",
    "volume_surge":           "Volume Surge",
    "breakout_52w":           "52-Week High",
}

# ── Signal generators ─────────────────────────────────────────────────────────
# Each takes a single-stock DataFrame (OHLCV, DatetimeIndex) and returns a
# boolean Series: True on days where an entry signal fires.

def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()

def _sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()

def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(n).mean()
    loss = (-delta.clip(upper=0)).rolling(n).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def sig_canslim_leaders(df: pd.DataFrame) -> pd.Series:
    c = df["Close"]
    v = df["Volume"]
    sma50 = _sma(c, 50)
    sma200 = _sma(c, 200)
    rsi = _rsi(c)
    vol_avg = v.rolling(20).mean()
    high20 = c.rolling(20).max()
    return (
        (c > sma50) & (c > sma200) &
        (rsi > 60) &
        (c >= high20) &
        (v > vol_avg * 1.4)
    ).fillna(False)


def sig_stage2_breakout(df: pd.DataFrame) -> pd.Series:
    c = df["Close"]
    v = df["Volume"]
    sma200 = _sma(c, 200)
    vol_avg = v.rolling(20).mean()
    above = c > sma200
    cross = above & ~above.shift(1).fillna(False)
    return (cross & (v > vol_avg * 1.5)).fillna(False)


def sig_momentum_surge(df: pd.DataFrame) -> pd.Series:
    c = df["Close"]
    ret3m = c / c.shift(63) - 1
    ret6m = c / c.shift(126) - 1
    rsi = _rsi(c)
    sma50 = _sma(c, 50)
    return (
        (ret3m > 0.10) & (ret6m > 0.15) &
        (rsi > 58) & (c > sma50)
    ).fillna(False)


def sig_high_rs_momentum(df: pd.DataFrame) -> pd.Series:
    c = df["Close"]
    ret3m = c / c.shift(63) - 1
    sma50 = _sma(c, 50)
    high52 = c.rolling(252).max()
    return (
        (ret3m > 0.15) &
        (c > sma50) &
        (c >= high52 * 0.95)
    ).fillna(False)


def sig_power_trend(df: pd.DataFrame) -> pd.Series:
    c = df["Close"]
    e20 = _ema(c, 20)
    e50 = _ema(c, 50)
    sma200 = _sma(c, 200)
    stacked = (e20 > e50) & (e50 > sma200)
    rising = (e20 > e20.shift(5)) & (e50 > e50.shift(10))
    pullback = (c <= e20 * 1.03) & (c >= e20 * 0.97)
    return (stacked & rising & pullback).fillna(False)


def sig_turtle_breakout(df: pd.DataFrame) -> pd.Series:
    c = df["Close"]
    v = df["Volume"]
    high55 = c.shift(1).rolling(55).max()
    vol_avg = v.rolling(20).mean()
    return ((c > high55) & (v > vol_avg)).fillna(False)


def sig_momentum_12m(df: pd.DataFrame) -> pd.Series:
    c = df["Close"]
    ret12m = c / c.shift(252) - 1
    ret1m = c / c.shift(21) - 1
    sma200 = _sma(c, 200)
    return (
        (ret12m > 0.20) & (ret1m > 0) & (c > sma200)
    ).fillna(False)


def sig_darvas_box(df: pd.DataFrame) -> pd.Series:
    c = df["Close"]
    v = df["Volume"]
    vol_avg = v.rolling(20).mean()
    box_high = c.shift(1).rolling(15).max()
    box_low = c.shift(1).rolling(15).min()
    box_pct = (box_high - box_low) / box_low
    breakout = (c > box_high) & (box_pct < 0.15)
    return (breakout & (v > vol_avg * 1.5)).fillna(False)


def sig_mean_reversion_quality(df: pd.DataFrame) -> pd.Series:
    c = df["Close"]
    sma200 = _sma(c, 200)
    rsi = _rsi(c)
    near_sma = (c <= sma200 * 1.03) & (c >= sma200 * 0.97)
    return (near_sma & (rsi > 35) & (rsi < 50)).fillna(False)


def sig_deep_value_bounce(df: pd.DataFrame) -> pd.Series:
    c = df["Close"]
    rsi = _rsi(c)
    ret60 = c / c.shift(60) - 1
    stab = c > c.shift(3)
    return (
        (ret60 < -0.20) & (rsi < 35) & stab
    ).fillna(False)


def sig_rsi_oversold(df: pd.DataFrame) -> pd.Series:
    c = df["Close"]
    sma200 = _sma(c, 200)
    rsi = _rsi(c)
    was_below = rsi.shift(1) < 35
    now_above = rsi >= 35
    return (was_below & now_above & (c > sma200)).fillna(False)


def sig_zscore_reversion(df: pd.DataFrame) -> pd.Series:
    c = df["Close"]
    mu = c.rolling(20).mean()
    sigma = c.rolling(20).std()
    z = (c - mu) / sigma.replace(0, np.nan)
    was_neg = z.shift(1) < -2.0
    recovering = z > z.shift(1)
    return (was_neg & recovering).fillna(False)


def sig_volatility_contraction(df: pd.DataFrame) -> pd.Series:
    c = df["Close"]
    v = df["Volume"]
    std20 = c.rolling(20).std()
    bb_width = std20 / _sma(c, 20)
    squeeze = bb_width < bb_width.rolling(30).min().shift(1) * 1.05
    upper_bb = _sma(c, 20) + 2 * std20
    breakout = c > upper_bb
    vol_avg = v.rolling(20).mean()
    return (squeeze.shift(1).fillna(False) & breakout & (v > vol_avg)).fillna(False)


def sig_ema_stack_uptrend(df: pd.DataFrame) -> pd.Series:
    c = df["Close"]
    e20 = _ema(c, 20)
    e50 = _ema(c, 50)
    e200 = _ema(c, 200)
    stacked = (e20 > e50) & (e50 > e200)
    pullback = (c.shift(1) <= e20.shift(1) * 1.02) & (c > e20)
    return (stacked & pullback).fillna(False)


def sig_consecutive_gains(df: pd.DataFrame) -> pd.Series:
    c = df["Close"]
    v = df["Volume"]
    vol_avg = v.rolling(20).mean()
    sma50 = _sma(c, 50)
    up = (c > c.shift(1)).astype(int)
    streak = up.rolling(4).sum()
    return (
        (streak >= 4) & (c > sma50) & (v > vol_avg * 1.1)
    ).fillna(False)


def sig_golden_cross(df: pd.DataFrame) -> pd.Series:
    c = df["Close"]
    sma50 = _sma(c, 50)
    sma200 = _sma(c, 200)
    cross = (sma50 > sma200) & (sma50.shift(1) <= sma200.shift(1))
    return cross.fillna(False)


def sig_macd_bullish(df: pd.DataFrame) -> pd.Series:
    c = df["Close"]
    macd = _ema(c, 12) - _ema(c, 26)
    signal = _ema(macd, 9)
    cross = (macd > signal) & (macd.shift(1) <= signal.shift(1))
    sma200 = _sma(c, 200)
    return (cross & (c > sma200)).fillna(False)


def sig_volume_surge(df: pd.DataFrame) -> pd.Series:
    c = df["Close"]
    v = df["Volume"]
    vol_avg = v.rolling(20).mean()
    up_day = c > c.shift(1)
    high_range = c.shift(1).rolling(252).max()
    near_high = c >= high_range * 0.92
    return (
        (v > vol_avg * 2.5) & up_day & near_high
    ).fillna(False)


def sig_breakout_52w(df: pd.DataFrame) -> pd.Series:
    c = df["Close"]
    v = df["Volume"]
    high52 = c.shift(1).rolling(252).max()
    vol_avg = v.rolling(20).mean()
    return ((c > high52) & (v > vol_avg)).fillna(False)


SIGNAL_FNS = {
    "canslim_leaders":        sig_canslim_leaders,
    "stage2_breakout":        sig_stage2_breakout,
    "momentum_surge":         sig_momentum_surge,
    "high_rs_momentum":       sig_high_rs_momentum,
    "power_trend":            sig_power_trend,
    "turtle_breakout":        sig_turtle_breakout,
    "momentum_12m":           sig_momentum_12m,
    "darvas_box":             sig_darvas_box,
    "mean_reversion_quality": sig_mean_reversion_quality,
    "deep_value_bounce":      sig_deep_value_bounce,
    "rsi_oversold":           sig_rsi_oversold,
    "zscore_reversion":       sig_zscore_reversion,
    "volatility_contraction": sig_volatility_contraction,
    "ema_stack_uptrend":      sig_ema_stack_uptrend,
    "consecutive_gains":      sig_consecutive_gains,
    "golden_cross":           sig_golden_cross,
    "macd_bullish":           sig_macd_bullish,
    "volume_surge":           sig_volume_surge,
    "breakout_52w":           sig_breakout_52w,
}

# ── Portfolio simulation ──────────────────────────────────────────────────────

INITIAL_CAPITAL = 100_000.0
POSITION_SIZE   = 5_000.0
MAX_POSITIONS   = 20
STOP_PCT        = -0.08
TARGET_PCT      =  0.20
MAX_HOLD_DAYS   = 30


@dataclass
class Trade:
    symbol: str
    entry_date: date
    entry_price: float
    shares: float
    stop_price: float
    target_price: float
    exit_date: Optional[date] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None

    @property
    def pnl(self) -> float:
        if self.exit_price is None:
            return 0.0
        return (self.exit_price - self.entry_price) * self.shares

    @property
    def pnl_pct(self) -> float:
        if self.exit_price is None:
            return 0.0
        return (self.exit_price - self.entry_price) / self.entry_price * 100


def _simulate(
    signals_by_symbol: Dict[str, pd.Series],
    price_data: Dict[str, pd.DataFrame],
    trading_days: pd.DatetimeIndex,
) -> Tuple[List[Trade], List[float]]:
    """Simulate a single strategy portfolio. Returns (trades, daily_equity)."""
    cash = INITIAL_CAPITAL
    open_positions: List[Trade] = []
    closed_trades: List[Trade] = []
    equity_curve: List[float] = []
    held_symbols: set = set()

    open_data_cache: Dict[str, pd.Series] = {}
    close_data_cache: Dict[str, pd.Series] = {}

    for sym, df in price_data.items():
        open_data_cache[sym] = df["Open"]
        close_data_cache[sym] = df["Close"]

    for dt in trading_days:
        dt_date = dt.date()

        # ── 1. Check exits ────────────────────────────────────────────────────
        still_open: List[Trade] = []
        for pos in open_positions:
            close_s = close_data_cache.get(pos.symbol)
            if close_s is None or dt not in close_s.index:
                still_open.append(pos)
                continue
            current = float(close_s[dt])
            days_held = (dt_date - pos.entry_date).days
            reason = None
            if current <= pos.stop_price:
                reason = "stop"
            elif current >= pos.target_price:
                reason = "target"
            elif days_held >= MAX_HOLD_DAYS:
                reason = "time"
            if reason:
                pos.exit_date = dt_date
                pos.exit_price = current
                pos.exit_reason = reason
                cash += current * pos.shares
                held_symbols.discard(pos.symbol)
                closed_trades.append(pos)
            else:
                still_open.append(pos)
        open_positions = still_open

        # ── 2. Enter new signals ──────────────────────────────────────────────
        if len(open_positions) < MAX_POSITIONS:
            for sym, sig_series in signals_by_symbol.items():
                if sym in held_symbols:
                    continue
                if len(open_positions) >= MAX_POSITIONS:
                    break
                # Signal fires today → enter at tomorrow's open
                if dt not in sig_series.index or not sig_series[dt]:
                    continue
                # Find next open price
                open_s = open_data_cache.get(sym)
                if open_s is None:
                    continue
                future = open_s[open_s.index > dt]
                if future.empty:
                    continue
                entry_price = float(future.iloc[0])
                if entry_price <= 0:
                    continue
                shares = POSITION_SIZE / entry_price
                cost = entry_price * shares
                if cost > cash:
                    continue
                pos = Trade(
                    symbol=sym,
                    entry_date=future.index[0].date(),
                    entry_price=entry_price,
                    shares=shares,
                    stop_price=entry_price * (1 + STOP_PCT),
                    target_price=entry_price * (1 + TARGET_PCT),
                )
                cash -= cost
                open_positions.append(pos)
                held_symbols.add(sym)

        # ── 3. Mark portfolio value ────────────────────────────────────────────
        open_value = sum(
            float(close_data_cache[p.symbol][dt]) * p.shares
            if p.symbol in close_data_cache and dt in close_data_cache[p.symbol].index
            else p.entry_price * p.shares
            for p in open_positions
        )
        equity_curve.append(cash + open_value)

    # Close any remaining positions at last price
    last_dt = trading_days[-1]
    for pos in open_positions:
        close_s = close_data_cache.get(pos.symbol)
        if close_s is not None and last_dt in close_s.index:
            pos.exit_price = float(close_s[last_dt])
        else:
            pos.exit_price = pos.entry_price
        pos.exit_date = last_dt.date()
        pos.exit_reason = "time"
        closed_trades.append(pos)

    return closed_trades, equity_curve


# ── Metrics calculation ───────────────────────────────────────────────────────

def _metrics(trades: List[Trade], equity_curve: List[float], period_years: float) -> dict:
    if not trades:
        return {
            "total_return_pct": 0.0, "cagr": 0.0, "win_rate": 0.0,
            "avg_win_pct": 0.0, "avg_loss_pct": 0.0, "max_drawdown_pct": 0.0,
            "sharpe_ratio": 0.0, "profit_factor": 0.0, "total_trades": 0,
        }

    wins   = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]

    final_val     = equity_curve[-1]
    total_ret     = (final_val - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
    cagr          = ((final_val / INITIAL_CAPITAL) ** (1 / max(period_years, 0.1)) - 1) * 100
    win_rate      = len(wins) / len(trades) * 100 if trades else 0
    avg_win       = sum(t.pnl_pct for t in wins) / len(wins) if wins else 0
    avg_loss      = sum(t.pnl_pct for t in losses) / len(losses) if losses else 0
    gross_profit  = sum(t.pnl for t in wins)
    gross_loss    = abs(sum(t.pnl for t in losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)

    # Max drawdown
    arr   = np.array(equity_curve)
    peak  = np.maximum.accumulate(arr)
    dd    = (arr - peak) / peak * 100
    max_dd = float(abs(dd.min()))

    # Sharpe (daily returns, annualised)
    if len(equity_curve) > 1:
        daily_rets = np.diff(arr) / arr[:-1]
        sharpe = (daily_rets.mean() / daily_rets.std() * math.sqrt(252)) if daily_rets.std() > 0 else 0.0
    else:
        sharpe = 0.0

    return {
        "total_return_pct": round(total_ret, 2),
        "cagr":             round(cagr, 2),
        "win_rate":         round(win_rate, 1),
        "avg_win_pct":      round(avg_win, 2),
        "avg_loss_pct":     round(avg_loss, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "sharpe_ratio":     round(sharpe, 2),
        "profit_factor":    round(profit_factor, 2),
        "total_trades":     len(trades),
    }


# ── Main entry point ──────────────────────────────────────────────────────────

CACHE_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "backtest_cache.json")


def _save_cache(data: dict) -> None:
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, "w") as f:
        json.dump(data, f)


def load_cache() -> Optional[dict]:
    if not os.path.exists(CACHE_PATH):
        return None
    with open(CACHE_PATH) as f:
        return json.load(f)


def run_backtest(period_years: int = 3) -> dict:
    """
    Download data, run all 19 strategies, cache results, return summary dict.
    Can take 1–3 minutes depending on network speed.
    """
    logger.info("Backtest starting — downloading %d symbols…", len(BACKTEST_UNIVERSE))

    end_dt   = datetime.now(timezone.utc)
    # Extra lookback for indicator warmup (200 days)
    start_dt = end_dt - timedelta(days=period_years * 365 + 250)

    # Single batched download
    raw = yf.download(
        BACKTEST_UNIVERSE,
        start=start_dt.strftime("%Y-%m-%d"),
        end=end_dt.strftime("%Y-%m-%d"),
        auto_adjust=True,
        progress=False,
        threads=True,
    )

    if raw.empty:
        raise RuntimeError("yfinance returned no data")

    # Split into per-symbol DataFrames
    price_data: Dict[str, pd.DataFrame] = {}
    if isinstance(raw.columns, pd.MultiIndex):
        for sym in BACKTEST_UNIVERSE:
            try:
                df = raw.xs(sym, axis=1, level=1).dropna(how="all")
                if len(df) > 200:
                    price_data[sym] = df
            except KeyError:
                pass
    else:
        # Single-symbol fallback (shouldn't happen)
        sym = BACKTEST_UNIVERSE[0]
        price_data[sym] = raw.dropna(how="all")

    logger.info("Loaded %d symbols. Computing signals…", len(price_data))

    # Signal indicator warmup cutoff
    signal_start = end_dt - timedelta(days=period_years * 365)
    signal_start_ts = pd.Timestamp(signal_start)

    # Build all signals
    all_signals: Dict[str, Dict[str, pd.Series]] = {k: {} for k in SIGNAL_FNS}
    for sym, df in price_data.items():
        for key, fn in SIGNAL_FNS.items():
            try:
                sig = fn(df)
                sig = sig[sig.index >= signal_start_ts]
                all_signals[key][sym] = sig
            except Exception:
                pass

    # Trading days for the signal period
    # Use SPY (most complete) or first available symbol
    ref_sym = "SPY" if "SPY" in price_data else list(price_data.keys())[0]
    trading_days = price_data[ref_sym].index[price_data[ref_sym].index >= signal_start_ts]

    # Trim price_data to signal period for equity tracking efficiency
    trimmed: Dict[str, pd.DataFrame] = {
        sym: df[df.index >= signal_start_ts] for sym, df in price_data.items()
    }

    logger.info("Running portfolio simulations for %d strategies…", len(SIGNAL_FNS))

    results = {}
    equity_curves = {}
    all_trades_out = {}

    for key in SIGNAL_FNS:
        try:
            trades, equity = _simulate(all_signals[key], trimmed, trading_days)
            m = _metrics(trades, equity, period_years)
            results[key] = m
            # Equity curve sampled weekly to keep payload small
            step = max(1, len(trading_days) // 104)
            equity_curves[key] = [
                {"date": trading_days[i].date().isoformat(), "value": round(equity[i], 2)}
                for i in range(0, len(equity), step)
            ]
            all_trades_out[key] = [
                {
                    "symbol": t.symbol,
                    "entry_date": t.entry_date.isoformat(),
                    "entry_price": round(t.entry_price, 2),
                    "exit_date": t.exit_date.isoformat() if t.exit_date else None,
                    "exit_price": round(t.exit_price, 2) if t.exit_price else None,
                    "exit_reason": t.exit_reason,
                    "pnl_pct": round(t.pnl_pct, 2),
                    "pnl": round(t.pnl, 2),
                }
                for t in trades
            ]
            logger.info("  %s: %.1f%% return, %d trades", key, m["total_return_pct"], m["total_trades"])
        except Exception as e:
            logger.error("Backtest failed for %s: %s", key, e, exc_info=True)
            results[key] = {}

    payload = {
        "status": "complete",
        "run_date": datetime.now(timezone.utc).isoformat(),
        "period_years": period_years,
        "results": results,
        "equity_curves": equity_curves,
        "trades": all_trades_out,
    }
    _save_cache(payload)
    logger.info("Backtest complete and cached.")
    return payload
