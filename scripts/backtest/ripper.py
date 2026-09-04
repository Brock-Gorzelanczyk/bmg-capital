"""
BMG SPY Ripper — Python replication of Pine v3.4 for multi-regime backtesting.

Faithfully replicates:
  - 18 setup detection rules from Pine (RSI, MACD, BB, EMA, ORB, VWAP, PDH/PDL, Vol)
  - Trend filter (1H 200EMA)
  - VIX crisis halt (>= 35 with hysteresis)
  - Per-setup VIX regime gates (ORB Dn = high_only, Vol Bull = mid_only, VWAP Bounce = mid_only)
  - SPY-tuned defaults (MACD Bull/Bear OFF, PDL Retest OFF)
  - ATR-based stops (1.5×), 1.5R targets, 20-bar timeout
  - Sticky trade state (one at a time)

The 2 remaining Pine setups (PC Bull, PC Bear) require CBOE PCC data — off by default in Pine too.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Optional


# ── Indicator params (match Pine defaults) ──────────────────────────────
RSI_LEN = 14
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
BB_LEN = 20
BB_STD = 2.0
SQUEEZE_LOOKBACK = 60
SQUEEZE_THRESH_MULT = 1.20
SMA50_LEN = 50
EMA_FAST_LEN = 20
EMA_SLOW_LEN = 50
ATR_LEN = 14
ATR_STOP_MULT = 1.5
RR_TARGET = 1.5
ORB_MINUTES = 15
VWAP_SIGMA_MULT = 1.0
RETEST_PCT = 0.15  # % of level, /100 in formula
VOL_BULL_MULT = 2.0
VOL_BEAR_MULT = 3.0
TREND_EMA_LEN = 200  # 1H
TIMEOUT_BARS = 20

# VIX halt (default OFF in Pine but implemented for completeness)
VIX_HALT_LEVEL = 35.0
VIX_RESUME_LEVEL = 30.0

# Setup toggles (match Pine v3.4 SPY defaults)
EN_RSI_BULL = True
EN_RSI_BEAR = True
EN_MACD_BULL = False       # KILLED — SPY loser
EN_MACD_BEAR = False       # KILLED — SPY loser
EN_BB_UP = True
EN_BB_DN = True
EN_EMA_GOLD = True
EN_EMA_DEATH = True
EN_ORB_UP = True
EN_ORB_DN = True
EN_VWAP_FADE_UP = True     # Fade DOWN >1σ above
EN_VWAP_FADE_DN = True     # Bounce UP <1σ below
EN_PDH_RETEST = True
EN_PDL_RETEST = False      # KILLED — SPY loser
EN_VOL_BULL = True
EN_VOL_BEAR = True

# Per-setup VIX regime gates (v3.1 defaults)
GATE_ORB_DN = "high_only"       # V>25 only
GATE_VOL_BULL = "mid_only"      # V15-25 only
GATE_VWAP_BOUNCE = "mid_only"   # V15-25 only

# Trend filter (v3.1 default ON)
USE_TREND_FILTER = True

# VIX crisis halt (default OFF)
USE_VIX_HALT = False


# ── Indicator functions ─────────────────────────────────────────────────

def rsi(series: pd.Series, length: int = 14) -> pd.Series:
    """Pine-equivalent RSI using Wilder's smoothing (RMA)."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    # Wilder's RMA = EMA with alpha = 1/length
    avg_gain = gain.ewm(alpha=1/length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/length, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def ema(series: pd.Series, length: int) -> pd.Series:
    """Pine-equivalent EMA."""
    return series.ewm(span=length, adjust=False).mean()


def sma(series: pd.Series, length: int) -> pd.Series:
    return series.rolling(length).mean()


def macd(close: pd.Series, fast=12, slow=26, signal=9):
    line = ema(close, fast) - ema(close, slow)
    sig = ema(line, signal)
    hist = line - sig
    return line, sig, hist


def bollinger(close: pd.Series, length=20, std=2.0):
    mid = sma(close, length)
    dev = close.rolling(length).std(ddof=0)  # Pine uses population std
    up = mid + std * dev
    dn = mid - std * dev
    return mid, up, dn


def atr(high: pd.Series, low: pd.Series, close: pd.Series, length=14) -> pd.Series:
    """Wilder's ATR."""
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1/length, adjust=False).mean()


def vwap_session(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Session-based VWAP using HLC3 as source, resets daily at market open.
    Returns (vwap, rolling_stddev_of_deviation) matching Pine's ta.vwap + ta.variance."""
    hlc3 = (df['high'] + df['low'] + df['close']) / 3
    # Session key = date in ET (market day)
    session = df.index.tz_convert('America/New_York').date
    df_session = pd.Series(session, index=df.index)

    # Cumulative typical price * volume, cumulative volume, per session
    tpv = hlc3 * df['volume']
    cum_tpv = tpv.groupby(df_session).cumsum()
    cum_vol = df['volume'].groupby(df_session).cumsum()
    vwap = cum_tpv / cum_vol

    # For the ±1σ bands: Pine uses ta.variance(hlc3 - vwap_val, 20) — rolling 20-bar variance
    deviation = hlc3 - vwap
    variance = deviation.rolling(20).var(ddof=0)
    vwap_std = np.sqrt(variance)
    return vwap, vwap_std


def compute_opening_range(df: pd.DataFrame, orb_minutes=15) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Compute per-bar opening range high / low / locked flag.
    ORB locks after `orb_minutes` from market open (9:30 ET)."""
    et_idx = df.index.tz_convert('America/New_York')
    session = pd.Series(et_idx.date, index=df.index)

    or_high = pd.Series(np.nan, index=df.index)
    or_low = pd.Series(np.nan, index=df.index)
    or_locked = pd.Series(False, index=df.index)

    # For each session, compute running high/low until orb_minutes elapsed
    for sess_date, group in df.groupby(session):
        gh = group['high'].cummax()
        gl = group['low'].cummin()
        # Time since session start (in minutes) — session starts at first bar of the day
        session_start = group.index[0]
        mins_from_open = ((group.index - session_start).total_seconds() / 60).astype(int)
        locked = pd.Series(mins_from_open >= orb_minutes, index=group.index)
        # After locked, or_high/low freeze at the values from the moment lock occurred
        # In Pine: or_high := max(nz(or_high, high), high) UNTIL locked, then it stops updating
        # So we compute cummax UP TO the lock point, then hold constant
        lock_idx = locked.idxmax() if locked.any() else group.index[-1]
        # High/low at the lock moment
        oh_at_lock = gh.loc[lock_idx]
        ol_at_lock = gl.loc[lock_idx]
        # Before lock: running high/low. After lock: frozen at lock values.
        pre_mask = ~locked
        or_high.loc[group.index[pre_mask]] = gh.loc[group.index[pre_mask]]
        or_low.loc[group.index[pre_mask]] = gl.loc[group.index[pre_mask]]
        or_high.loc[group.index[~pre_mask]] = oh_at_lock
        or_low.loc[group.index[~pre_mask]] = ol_at_lock
        or_locked.loc[group.index] = locked

    return or_high, or_low, or_locked


def compute_pdh_pdl(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Prior day high / low, forward-filled across the current session."""
    et_idx = df.index.tz_convert('America/New_York')
    session = pd.Series(et_idx.date, index=df.index)
    daily_high = df.groupby(session)['high'].max()
    daily_low = df.groupby(session)['low'].min()
    # Shift by 1 = prior day
    pdh_by_date = daily_high.shift(1)
    pdl_by_date = daily_low.shift(1)
    pdh = session.map(pdh_by_date)
    pdl = session.map(pdl_by_date)
    return pdh, pdl


def compute_htf_ema_1h(df_15m: pd.DataFrame, length=200) -> pd.Series:
    """Resample 15m → 1h, compute EMA200, forward-fill back to 15m timeline.
    Matches Pine's request.security with lookahead_off (uses PRIOR completed 1h bar)."""
    df_1h = df_15m['close'].resample('1h').last().dropna()
    ema_1h = ema(df_1h, length)
    # Shift by 1 bar to avoid lookahead (use PRIOR completed 1h bar for current 15m)
    ema_1h_shifted = ema_1h.shift(1)
    # Reindex back to 15m timeline, forward-fill
    ema_15m = ema_1h_shifted.reindex(df_15m.index, method='ffill')
    return ema_15m


# ── Setup detection ─────────────────────────────────────────────────────

@dataclass
class Signals:
    """Boolean series for each setup (True on bars where setup fires)."""
    rsi_bull: pd.Series
    rsi_bear: pd.Series
    macd_bull: pd.Series
    macd_bear: pd.Series
    bb_up: pd.Series
    bb_dn: pd.Series
    ema_gold: pd.Series
    ema_death: pd.Series
    orb_up: pd.Series
    orb_dn: pd.Series
    vwap_fade_up: pd.Series   # display: "VWAP Fade Dn" → PUT
    vwap_fade_dn: pd.Series   # display: "VWAP Bounce Up" → CALL
    pdh_retest: pd.Series
    pdl_retest: pd.Series
    vol_bull: pd.Series
    vol_bear: pd.Series


def compute_signals(df: pd.DataFrame, vix_daily: pd.DataFrame) -> tuple[Signals, dict]:
    """Compute all 16 setup boolean series + supporting series. Returns (Signals, extras)."""
    close = df['close']
    high = df['high']
    low = df['low']
    open_ = df['open']
    volume = df['volume']

    # Indicators
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

    # Crossovers
    def crossover(a, b):
        return (a > b) & (a.shift(1) <= b.shift(1))
    def crossunder(a, b):
        return (a < b) & (a.shift(1) >= b.shift(1))

    # ── Setup conditions (mirror Pine v3.4 exactly) ──
    close_prev = close.shift(1)

    sig_rsi_bull = EN_RSI_BULL & (rsi_val < RSI_OVERSOLD) & (close > close_prev)
    sig_rsi_bear = EN_RSI_BEAR & (rsi_val > RSI_OVERBOUGHT) & (close < close_prev)
    sig_macd_bull = EN_MACD_BULL & crossover(macd_line, signal_line) & (close > sma50)
    sig_macd_bear = EN_MACD_BEAR & crossunder(macd_line, signal_line) & (close < sma50)
    sig_bb_up = EN_BB_UP & in_squeeze & (close > bb_up_band) & (close_prev <= bb_up_band.shift(1))
    sig_bb_dn = EN_BB_DN & in_squeeze & (close < bb_dn_band) & (close_prev >= bb_dn_band.shift(1))
    sig_ema_gold = EN_EMA_GOLD & crossover(ema_fast, ema_slow)
    sig_ema_death = EN_EMA_DEATH & crossunder(ema_fast, ema_slow)

    sig_orb_up = EN_ORB_UP & or_locked & (close > or_high) & (close_prev <= or_high) & (volume > vol_avg)
    sig_orb_dn = EN_ORB_DN & or_locked & (close < or_low) & (close_prev >= or_low) & (volume > vol_avg)

    sig_vwap_fade_up = EN_VWAP_FADE_UP & (close > vwap_up_1) & (rsi_val > 70)
    sig_vwap_fade_dn = EN_VWAP_FADE_DN & (close < vwap_dn_1) & (rsi_val < 30)

    pdh_zone_lo = pdh * (1 - RETEST_PCT/100)
    pdh_zone_hi = pdh * (1 + RETEST_PCT/100)
    pdl_zone_lo = pdl * (1 - RETEST_PCT/100)
    pdl_zone_hi = pdl * (1 + RETEST_PCT/100)
    broke_pdh_recently = high.rolling(20).max() > pdh
    broke_pdl_recently = low.rolling(20).min() < pdl
    sig_pdh_retest = EN_PDH_RETEST & broke_pdh_recently & (low <= pdh_zone_hi) & (low >= pdh_zone_lo) & (close > open_)
    sig_pdl_retest = EN_PDL_RETEST & broke_pdl_recently & (high >= pdl_zone_lo) & (high <= pdl_zone_hi) & (close < open_)

    sig_vol_bull = EN_VOL_BULL & (volume > vol_avg * VOL_BULL_MULT) & (close > vwap_val) & (close > open_)
    sig_vol_bear = EN_VOL_BEAR & (volume > vol_avg * VOL_BEAR_MULT) & (close < open_) & (close < vwap_val)

    # ── VIX regime bin (daily VIX close, ffill to 15m) ──
    vix_daily_close = vix_daily['close']
    vix_daily_close.index = pd.to_datetime(vix_daily_close.index)
    # Map each 15m bar to that day's VIX close (using the PRIOR day's close if not yet available intraday)
    et_dates = pd.Series(df.index.tz_convert('America/New_York').date, index=df.index)
    vix_by_date = vix_daily_close.copy()
    vix_by_date.index = vix_by_date.index.date
    vix_15m = et_dates.map(vix_by_date)
    # Forward-fill for weekends/holidays
    vix_15m = vix_15m.ffill()

    vix_zone = pd.Series('mid', index=df.index)
    vix_zone[vix_15m < 15.0] = 'low'
    vix_zone[vix_15m >= 25.0] = 'high'

    def vix_regime_ok(gate_str: str) -> pd.Series:
        if gate_str == "any":
            return pd.Series(True, index=df.index)
        return {
            "low_only": vix_zone == 'low',
            "mid_only": vix_zone == 'mid',
            "high_only": vix_zone == 'high',
            "mid_high": vix_zone.isin(['mid', 'high']),
            "low_mid": vix_zone.isin(['low', 'mid']),
        }[gate_str]

    # Apply VIX regime gates
    sig_orb_dn = sig_orb_dn & vix_regime_ok(GATE_ORB_DN)
    sig_vol_bull = sig_vol_bull & vix_regime_ok(GATE_VOL_BULL)
    sig_vwap_fade_dn = sig_vwap_fade_dn & vix_regime_ok(GATE_VWAP_BOUNCE)

    signals = Signals(
        rsi_bull=sig_rsi_bull.fillna(False),
        rsi_bear=sig_rsi_bear.fillna(False),
        macd_bull=sig_macd_bull.fillna(False),
        macd_bear=sig_macd_bear.fillna(False),
        bb_up=sig_bb_up.fillna(False),
        bb_dn=sig_bb_dn.fillna(False),
        ema_gold=sig_ema_gold.fillna(False),
        ema_death=sig_ema_death.fillna(False),
        orb_up=sig_orb_up.fillna(False),
        orb_dn=sig_orb_dn.fillna(False),
        vwap_fade_up=sig_vwap_fade_up.fillna(False),
        vwap_fade_dn=sig_vwap_fade_dn.fillna(False),
        pdh_retest=sig_pdh_retest.fillna(False),
        pdl_retest=sig_pdl_retest.fillna(False),
        vol_bull=sig_vol_bull.fillna(False),
        vol_bear=sig_vol_bear.fillna(False),
    )
    extras = {
        'atr': atr_val,
        'in_uptrend': in_uptrend,
        'in_downtrend': in_downtrend,
        'vix_zone': vix_zone,
        'vix_15m': vix_15m,
    }
    return signals, extras


# ── Trade / Backtest engine ─────────────────────────────────────────────

BULL_SETUPS = ['rsi_bull', 'macd_bull', 'bb_up', 'ema_gold', 'orb_up', 'vwap_fade_dn', 'pdh_retest', 'vol_bull']
BEAR_SETUPS = ['rsi_bear', 'macd_bear', 'bb_dn', 'ema_death', 'orb_dn', 'vwap_fade_up', 'pdl_retest', 'vol_bear']
SETUP_DISPLAY_NAMES = {
    'rsi_bull': 'RSI Bull',
    'rsi_bear': 'RSI Bear',
    'macd_bull': 'MACD Bull',
    'macd_bear': 'MACD Bear',
    'bb_up': 'BB Up',
    'bb_dn': 'BB Dn',
    'ema_gold': 'EMA Gold',
    'ema_death': 'EMA Death',
    'orb_up': 'ORB Up',
    'orb_dn': 'ORB Dn',
    'vwap_fade_up': 'VWAP Fade Dn',     # NAME QUIRK — matches Pine display
    'vwap_fade_dn': 'VWAP Bounce Up',
    'pdh_retest': 'PDH Retest',
    'pdl_retest': 'PDL Retest',
    'vol_bull': 'Vol Bull',
    'vol_bear': 'Vol Bear',
}
# Priority order matching Pine's inline ternary chain (first fire wins)
SETUP_PRIORITY = ['rsi_bull', 'rsi_bear', 'macd_bull', 'macd_bear', 'bb_up', 'bb_dn', 'ema_gold', 'ema_death',
                  'orb_up', 'orb_dn', 'vwap_fade_up', 'vwap_fade_dn', 'pdh_retest', 'pdl_retest', 'vol_bull', 'vol_bear']


@dataclass
class Trade:
    fire_bar_idx: int
    fire_time: pd.Timestamp
    direction: str  # "CALL" or "PUT"
    setup_name: str
    entry: float
    stop: float
    target: float
    outcome: str = "OPEN"       # "OPEN", "WIN", "LOSS", "TIMEOUT"
    close_bar_idx: Optional[int] = None
    close_time: Optional[pd.Timestamp] = None
    vix_at_fire: float = np.nan
    vix_bin: str = "mid"


def run_backtest(df: pd.DataFrame, signals: Signals, extras: dict) -> pd.DataFrame:
    """Walk-forward backtest. Returns DataFrame with one row per trade."""
    atr_val = extras['atr'].values
    in_uptrend = extras['in_uptrend'].values
    in_downtrend = extras['in_downtrend'].values
    vix_15m = extras['vix_15m'].values
    vix_zone = extras['vix_zone'].values

    high = df['high'].values
    low = df['low'].values
    close = df['close'].values
    times = df.index

    # Precompute per-bar setup fire arrays (matches priority ordering)
    fire_bull = {name: getattr(signals, name).values for name in BULL_SETUPS}
    fire_bear = {name: getattr(signals, name).values for name in BEAR_SETUPS}

    trades: list[Trade] = []
    active: Optional[Trade] = None
    n_bars = len(df)

    # VIX crisis halt state (default OFF but implement for completeness)
    vix_halted = False

    for i in range(n_bars):
        # 1) Check if active trade closes on THIS bar
        if active is not None:
            if active.direction == "CALL":
                hit_target = high[i] >= active.target
                hit_stop = low[i] <= active.stop
            else:  # PUT
                hit_target = low[i] <= active.target
                hit_stop = high[i] >= active.stop

            bars_since = i - active.fire_bar_idx
            if bars_since > 0:  # can't close on same bar as entry
                if hit_target and hit_stop:
                    active.outcome = "LOSS"  # conservative: stop first
                    active.close_bar_idx = i
                    active.close_time = times[i]
                    trades.append(active)
                    active = None
                elif hit_target:
                    active.outcome = "WIN"
                    active.close_bar_idx = i
                    active.close_time = times[i]
                    trades.append(active)
                    active = None
                elif hit_stop:
                    active.outcome = "LOSS"
                    active.close_bar_idx = i
                    active.close_time = times[i]
                    trades.append(active)
                    active = None
                elif bars_since >= TIMEOUT_BARS:
                    active.outcome = "TIMEOUT"
                    active.close_bar_idx = i
                    active.close_time = times[i]
                    trades.append(active)
                    active = None

        # 2) VIX crisis halt update
        if USE_VIX_HALT and not np.isnan(vix_15m[i]):
            if vix_15m[i] >= VIX_HALT_LEVEL:
                vix_halted = True
            elif vix_15m[i] <= VIX_RESUME_LEVEL:
                vix_halted = False
        vix_pass = not (USE_VIX_HALT and vix_halted)

        # 3) Check for new fire (only if no active trade)
        if active is not None or not vix_pass:
            continue

        any_bull_raw = any(fire_bull[name][i] for name in BULL_SETUPS)
        any_bear_raw = any(fire_bear[name][i] for name in BEAR_SETUPS)

        # Trend filter — bull trades only when in uptrend, bear only when downtrend
        if USE_TREND_FILTER:
            can_bull = any_bull_raw and in_uptrend[i]
            can_bear = any_bear_raw and in_downtrend[i]
        else:
            can_bull = any_bull_raw
            can_bear = any_bear_raw

        if not (can_bull or can_bear):
            continue

        # Priority: find the FIRST setup in priority order that matches an allowed direction.
        # This mirrors Pine's inline ternary chain — bull setups appear first in priority so
        # if both fire simultaneously with both directions allowed, bull wins.
        setup_name = None
        direction = None
        for name in SETUP_PRIORITY:
            if name in BULL_SETUPS and can_bull and fire_bull[name][i]:
                setup_name = name
                direction = "CALL"
                break
            elif name in BEAR_SETUPS and can_bear and fire_bear[name][i]:
                setup_name = name
                direction = "PUT"
                break
        if setup_name is None:
            continue

        # Compute entry/stop/target
        entry = close[i]
        atr_this = atr_val[i]
        if np.isnan(atr_this) or atr_this == 0:
            continue  # skip early bars without ATR
        risk = atr_this * ATR_STOP_MULT
        if direction == "CALL":
            stop = entry - risk
            target = entry + risk * RR_TARGET
        else:
            stop = entry + risk
            target = entry - risk * RR_TARGET

        active = Trade(
            fire_bar_idx=i,
            fire_time=times[i],
            direction=direction,
            setup_name=SETUP_DISPLAY_NAMES[setup_name],
            entry=entry,
            stop=stop,
            target=target,
            vix_at_fire=vix_15m[i] if not np.isnan(vix_15m[i]) else np.nan,
            vix_bin=vix_zone[i],
        )

    # Any open trade at end → mark OPEN
    if active is not None:
        trades.append(active)

    # Build DataFrame
    rows = []
    for t in trades:
        r_multiple = 0.0
        if t.outcome == "WIN":
            r_multiple = RR_TARGET
        elif t.outcome == "LOSS":
            r_multiple = -1.0
        # TIMEOUT and OPEN = 0
        rows.append({
            'fire_time': t.fire_time,
            'setup': t.setup_name,
            'direction': t.direction,
            'entry': t.entry,
            'stop': t.stop,
            'target': t.target,
            'outcome': t.outcome,
            'close_time': t.close_time,
            'bars_held': (t.close_bar_idx - t.fire_bar_idx) if t.close_bar_idx else None,
            'vix_at_fire': t.vix_at_fire,
            'vix_bin': t.vix_bin,
            'r_multiple': r_multiple,
        })
    return pd.DataFrame(rows)
