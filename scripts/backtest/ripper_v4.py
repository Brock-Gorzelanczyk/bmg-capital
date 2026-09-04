"""
PHASE 3: BMG SPY Ripper v4 — Regime-Conditional Adaptive Strategy.

New in v4 vs v3.4:
  - Detects market regime from VIX (low/mid/high/crisis) × trend (bull/bear)
  - Per-setup regime-conditional enable/disable rules derived from Phase 2 analysis
  - Auto-kills losing setups in regimes where they historically bled
  - Data-driven rules from 8.5-year Python backtest (2018-2026)

Regime detection:
  - VIX bin: low (<15), mid (15-25), high (25-35), crisis (>=35)
  - Trend bin: bull (close > 200D SMA), bear (close < 200D SMA)
  - Combined: 8 possible regime states (4 VIX × 2 trend)

Per-setup regime rules (derived from Phase 2 CSV):
  - Vol Bull: enable in bull_low, bull_mid, bull_high (was +43R over 8.5yr, 8/10 regimes positive)
  - EMA Death: enable in bear_mid, bear_high (was +18.5R, 7/10 regimes)
  - ORB Dn: enable in bull_high, bear_high, bear_crisis (VIX high already default)
  - EMA Gold: enable in bull_low, bull_mid (was +12.5R)
  - VWAP Fade Dn / Bounce Up: enable in bull_mid (mid-VIX only)
  - Vol Bear: enable in bear_high, bear_crisis
  - PDH Retest: DISABLE (structural loser -47R across regimes; my Python overfires it vs Pine)
  - BB Up / BB Dn: DISABLE (structural loser, 7/10 regimes losing)
  - ORB Up: enable only in bull_low (was decent), disable elsewhere
  - RSI Bull / RSI Bear: enable only in high vol regimes (small samples)
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Optional
import sys
from pathlib import Path

# Import base indicator functions from v3 module
sys.path.insert(0, str(Path(__file__).parent))
from ripper import (
    rsi, ema, sma, macd, bollinger, atr, vwap_session,
    compute_opening_range, compute_pdh_pdl, compute_htf_ema_1h,
    Trade, RR_TARGET, ATR_STOP_MULT, TIMEOUT_BARS,
    BULL_SETUPS, BEAR_SETUPS, SETUP_DISPLAY_NAMES, SETUP_PRIORITY,
    RSI_LEN, RSI_OVERSOLD, RSI_OVERBOUGHT, MACD_FAST, MACD_SLOW, MACD_SIGNAL,
    BB_LEN, BB_STD, SQUEEZE_LOOKBACK, SQUEEZE_THRESH_MULT, SMA50_LEN,
    EMA_FAST_LEN, EMA_SLOW_LEN, ATR_LEN, ORB_MINUTES, VWAP_SIGMA_MULT,
    RETEST_PCT, VOL_BULL_MULT, VOL_BEAR_MULT, TREND_EMA_LEN,
)


# ── Regime Detection ─────────────────────────────────────────────────────
def compute_regime(spy_15m: pd.DataFrame, vix_15m: pd.Series) -> pd.Series:
    """Return a series of regime labels per bar.

    Regime = {vix_bin}_{trend_bin}:
      vix_bin: low (<15), mid (15-25), high (25-35), crisis (>=35)
      trend_bin: bull (SPY > 200D SMA), bear (SPY < 200D SMA)

    Total 8 regimes: bull_low, bull_mid, bull_high, bull_crisis,
                     bear_low, bear_mid, bear_high, bear_crisis
    """
    close = spy_15m['close']
    # 200-day SMA on daily bars — resample 15m to daily close first
    daily_close = close.resample('1D').last().dropna()
    sma_200_daily = daily_close.rolling(200).mean()
    # Reindex back to 15m, forward-fill
    sma_200 = sma_200_daily.reindex(spy_15m.index, method='ffill').shift(1)  # use prior day's SMA (no lookahead)

    trend = pd.Series('bear', index=spy_15m.index)
    trend[close > sma_200] = 'bull'

    vix_bin = pd.Series('mid', index=spy_15m.index)
    vix_bin[vix_15m < 15.0] = 'low'
    vix_bin[(vix_15m >= 15.0) & (vix_15m < 25.0)] = 'mid'
    vix_bin[(vix_15m >= 25.0) & (vix_15m < 35.0)] = 'high'
    vix_bin[vix_15m >= 35.0] = 'crisis'

    regime = trend + '_' + vix_bin
    return regime, trend, vix_bin


# ── Per-setup regime enable rules (from Phase 2 data) ────────────────────
# Format: setup_name → set of regime strings where this setup fires
# If regime not in set, setup is disabled.
REGIME_RULES = {
    # Bull setups
    'RSI Bull': {'bull_high', 'bull_crisis', 'bear_high', 'bear_crisis'},  # rare, high-vol only
    'BB Up': set(),  # STRUCTURAL LOSER — disable everywhere
    'EMA Gold': {'bull_low', 'bull_mid'},  # Phase 2: +12.5R in trending bull
    'ORB Up': {'bull_low'},  # Best only in bull_low (was killed elsewhere)
    'VWAP Fade Dn': {'bull_mid', 'bear_mid'},  # VWAP works in normal-vol
    'VWAP Bounce Up': {'bull_mid'},  # Only mid-vol bull
    'PDH Retest': set(),  # STRUCTURAL LOSER — disable everywhere
    'Vol Bull': {'bull_low', 'bull_mid', 'bull_high'},  # Vol Bull is the star — all bull regimes

    # Bear setups
    'RSI Bear': {'bull_high', 'bull_crisis', 'bear_high', 'bear_crisis'},  # high-vol reversals
    'BB Dn': set(),  # STRUCTURAL LOSER
    'EMA Death': {'bear_mid', 'bear_high', 'bear_crisis'},  # Phase 2: +18.5R
    'ORB Dn': {'bear_high', 'bear_crisis', 'bull_high'},  # High-vol regimes
    'VWAP Fade Up': {'bull_mid', 'bear_mid'},  # (name quirk in code — VWAP Fade Dn display)
    'Vol Bear': {'bear_high', 'bear_crisis'},  # crisis bear only
    'PDL Retest': set(),  # STRUCTURAL LOSER
    # MACD Bull/Bear already disabled by SPY defaults
}


# Setups always on for baseline v4 (regime-conditional list)
V4_ENABLED_SETUPS = set(REGIME_RULES.keys()) - {s for s, regimes in REGIME_RULES.items() if not regimes}


# ── Backtest engine ─────────────────────────────────────────────────────

def compute_signals_v4(df: pd.DataFrame, vix_daily: pd.DataFrame):
    """Compute all signals + regime detection."""
    close = df['close']; high = df['high']; low = df['low']; open_ = df['open']; volume = df['volume']

    rsi_val = rsi(close, RSI_LEN)
    macd_line, signal_line, _ = macd(close, MACD_FAST, MACD_SLOW, MACD_SIGNAL)
    bb_mid, bb_up_band, bb_dn_band = bollinger(close, BB_LEN, BB_STD)
    bb_bw = (bb_up_band - bb_dn_band) / bb_mid
    bb_bw_lowest = bb_bw.rolling(SQUEEZE_LOOKBACK).min()
    in_squeeze = bb_bw < bb_bw_lowest * SQUEEZE_THRESH_MULT
    sma50 = sma(close, SMA50_LEN)
    ema_fast = ema(close, EMA_FAST_LEN)
    ema_slow = ema(close, EMA_SLOW_LEN)
    atr_val = atr(high, low, close, ATR_LEN)
    vwap_val, vwap_std = vwap_session(df)
    vwap_up_1 = vwap_val + VWAP_SIGMA_MULT * vwap_std
    vwap_dn_1 = vwap_val - VWAP_SIGMA_MULT * vwap_std
    vol_avg = sma(volume, 20)
    or_high, or_low, or_locked = compute_opening_range(df, ORB_MINUTES)
    pdh, pdl = compute_pdh_pdl(df)
    htf_ema = compute_htf_ema_1h(df, TREND_EMA_LEN)
    in_uptrend = close > htf_ema
    in_downtrend = close < htf_ema

    def crossover(a, b):
        return (a > b) & (a.shift(1) <= b.shift(1))
    def crossunder(a, b):
        return (a < b) & (a.shift(1) >= b.shift(1))

    close_prev = close.shift(1)

    signals = {
        'RSI Bull': (rsi_val < RSI_OVERSOLD) & (close > close_prev),
        'RSI Bear': (rsi_val > RSI_OVERBOUGHT) & (close < close_prev),
        'BB Up': in_squeeze & (close > bb_up_band) & (close_prev <= bb_up_band.shift(1)),
        'BB Dn': in_squeeze & (close < bb_dn_band) & (close_prev >= bb_dn_band.shift(1)),
        'EMA Gold': crossover(ema_fast, ema_slow),
        'EMA Death': crossunder(ema_fast, ema_slow),
        'ORB Up': or_locked & (close > or_high) & (close_prev <= or_high) & (volume > vol_avg),
        'ORB Dn': or_locked & (close < or_low) & (close_prev >= or_low) & (volume > vol_avg),
        'VWAP Fade Dn': (close > vwap_up_1) & (rsi_val > 70),  # display "VWAP Fade Dn" fires PUT
        'VWAP Bounce Up': (close < vwap_dn_1) & (rsi_val < 30),  # display "VWAP Bounce Up" fires CALL
        'Vol Bull': (volume > vol_avg * VOL_BULL_MULT) & (close > vwap_val) & (close > open_),
        'Vol Bear': (volume > vol_avg * VOL_BEAR_MULT) & (close < open_) & (close < vwap_val),
    }

    # PDH/PDL retest (kept in signals but disabled by regime rules)
    pdh_zone_lo = pdh * (1 - RETEST_PCT/100)
    pdh_zone_hi = pdh * (1 + RETEST_PCT/100)
    pdl_zone_lo = pdl * (1 - RETEST_PCT/100)
    pdl_zone_hi = pdl * (1 + RETEST_PCT/100)
    broke_pdh_recently = high.rolling(20).max() > pdh
    broke_pdl_recently = low.rolling(20).min() < pdl
    signals['PDH Retest'] = broke_pdh_recently & (low <= pdh_zone_hi) & (low >= pdh_zone_lo) & (close > open_)
    signals['PDL Retest'] = broke_pdl_recently & (high >= pdl_zone_lo) & (high <= pdl_zone_hi) & (close < open_)

    # Fill NaN with False for all signals
    signals = {k: v.fillna(False) for k, v in signals.items()}

    # VIX daily → 15m
    vix_daily_close = vix_daily['close'].copy()
    vix_daily_close.index = vix_daily_close.index.date
    et_dates = pd.Series(df.index.tz_convert('America/New_York').date, index=df.index)
    vix_15m = et_dates.map(vix_daily_close).ffill()

    # Regime detection
    regime, trend, vix_bin = compute_regime(df, vix_15m)

    return signals, {
        'atr': atr_val,
        'in_uptrend': in_uptrend,
        'in_downtrend': in_downtrend,
        'vix_15m': vix_15m,
        'vix_bin': vix_bin,
        'trend': trend,
        'regime': regime,
    }


# Bull/bear setup classification for v4
BULL_SETUP_NAMES = {'RSI Bull', 'BB Up', 'EMA Gold', 'ORB Up', 'VWAP Bounce Up', 'PDH Retest', 'Vol Bull'}
BEAR_SETUP_NAMES = {'RSI Bear', 'BB Dn', 'EMA Death', 'ORB Dn', 'VWAP Fade Dn', 'PDL Retest', 'Vol Bear'}
# Priority order — match Pine's ternary
V4_PRIORITY = ['RSI Bull', 'RSI Bear', 'BB Up', 'BB Dn', 'EMA Gold', 'EMA Death',
               'ORB Up', 'ORB Dn', 'VWAP Fade Dn', 'VWAP Bounce Up',
               'PDH Retest', 'PDL Retest', 'Vol Bull', 'Vol Bear']


def run_backtest_v4(df, signals, extras, use_regime_gates=True, use_trend_filter=True):
    """Walk-forward with regime-conditional gates."""
    atr_val = extras['atr'].values
    in_uptrend = extras['in_uptrend'].values
    in_downtrend = extras['in_downtrend'].values
    regime = extras['regime'].values
    vix_15m = extras['vix_15m'].values
    vix_bin = extras['vix_bin'].values

    high = df['high'].values; low = df['low'].values; close = df['close'].values
    times = df.index
    n_bars = len(df)

    signal_arrays = {name: s.values for name, s in signals.items()}
    trades = []
    active: Optional[Trade] = None

    for i in range(n_bars):
        # Close active trade if hit
        if active is not None:
            if active.direction == 'CALL':
                hit_target = high[i] >= active.target
                hit_stop = low[i] <= active.stop
            else:
                hit_target = low[i] <= active.target
                hit_stop = high[i] >= active.stop
            bars_since = i - active.fire_bar_idx
            if bars_since > 0:
                if hit_target and hit_stop:
                    active.outcome = 'LOSS'
                elif hit_target:
                    active.outcome = 'WIN'
                elif hit_stop:
                    active.outcome = 'LOSS'
                elif bars_since >= TIMEOUT_BARS:
                    active.outcome = 'TIMEOUT'
                if active.outcome != 'OPEN':
                    active.close_bar_idx = i
                    active.close_time = times[i]
                    trades.append(active)
                    active = None
        if active is not None:
            continue

        # Check fires
        current_regime = regime[i]

        # Find first setup in priority order that fires AND is allowed by regime AND direction
        setup_name = None
        direction = None
        for name in V4_PRIORITY:
            if name not in signal_arrays:
                continue
            if not signal_arrays[name][i]:
                continue
            # Regime gate
            if use_regime_gates:
                allowed_regimes = REGIME_RULES.get(name, set())
                if current_regime not in allowed_regimes:
                    continue
            # Direction / trend filter
            is_bull_setup = name in BULL_SETUP_NAMES
            if use_trend_filter:
                if is_bull_setup and not in_uptrend[i]:
                    continue
                if not is_bull_setup and not in_downtrend[i]:
                    continue
            setup_name = name
            direction = 'CALL' if is_bull_setup else 'PUT'
            break

        if setup_name is None:
            continue

        entry = close[i]
        atr_this = atr_val[i]
        if np.isnan(atr_this) or atr_this == 0:
            continue
        risk = atr_this * ATR_STOP_MULT
        if direction == 'CALL':
            stop = entry - risk
            target = entry + risk * RR_TARGET
        else:
            stop = entry + risk
            target = entry - risk * RR_TARGET

        active = Trade(
            fire_bar_idx=i,
            fire_time=times[i],
            direction=direction,
            setup_name=setup_name,
            entry=entry, stop=stop, target=target,
            vix_at_fire=vix_15m[i] if not np.isnan(vix_15m[i]) else np.nan,
            vix_bin=vix_bin[i] if isinstance(vix_bin[i], str) else 'mid',
        )

    if active is not None:
        trades.append(active)

    rows = []
    for t in trades:
        r = 0.0
        if t.outcome == 'WIN': r = RR_TARGET
        elif t.outcome == 'LOSS': r = -1.0
        rows.append({
            'fire_time': t.fire_time,
            'setup': t.setup_name,
            'direction': t.direction,
            'entry': t.entry, 'stop': t.stop, 'target': t.target,
            'outcome': t.outcome,
            'close_time': t.close_time,
            'bars_held': (t.close_bar_idx - t.fire_bar_idx) if t.close_bar_idx else None,
            'vix_at_fire': t.vix_at_fire,
            'vix_bin': t.vix_bin,
            'regime': regime[t.fire_bar_idx],
            'r_multiple': r,
        })
    return pd.DataFrame(rows)
