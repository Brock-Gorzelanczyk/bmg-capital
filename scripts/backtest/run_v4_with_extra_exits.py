"""
Compare Ripper v4 baseline vs v4 + additional mechanical exits from vault research/32 and /36:
  - Friday >= 3:30 PM ET close (weekend theta bleed)
  - VIX >= 35 crisis close
  - OpEx Thursday >= 3:00 PM ET close (pin risk)
  - DAY setups >= 3:00 PM ET close (session end)

Purpose: validate that the exit rules I added to the Pine v4.3 actually IMPROVE the 8.5-year backtest.
If they don't, they get removed from Pine. If they do, the vault projections are validated.
"""
import sys
from pathlib import Path
import pandas as pd
import numpy as np
from datetime import datetime
import pytz

sys.path.insert(0, str(Path(__file__).parent))
from ripper_v4 import compute_signals_v4, run_backtest_v4, REGIME_RULES
from ripper import Trade, RR_TARGET, ATR_STOP_MULT, TIMEOUT_BARS

# Match ripper_v4.py setup classification
BULL_SETUP_NAMES = {'RSI Bull', 'BB Up', 'EMA Gold', 'ORB Up', 'VWAP Bounce Up', 'PDH Retest', 'Vol Bull'}
V4_PRIORITY = ['RSI Bull', 'RSI Bear', 'BB Up', 'BB Dn', 'EMA Gold', 'EMA Death',
               'ORB Up', 'ORB Dn', 'VWAP Fade Dn', 'VWAP Bounce Up',
               'PDH Retest', 'PDL Retest', 'Vol Bull', 'Vol Bear']

# DAY setups per vault research/36 §3.2 (Pine indicator's is_day_setup logic)
DAY_SETUPS = {'ORB Up', 'ORB Dn', 'VWAP Fade Dn', 'VWAP Bounce Up', 'RSI Bull', 'RSI Bear'}

DATA_DIR = Path(__file__).parent / "data"
ET = pytz.timezone('America/New_York')


def to_et(ts: pd.Timestamp):
    """Convert timestamp to ET-localized."""
    if ts.tzinfo is None:
        ts = ts.tz_localize('UTC')
    return ts.tz_convert(ET)


def force_close_extras(setup_name: str, ts_utc: pd.Timestamp, vix_val: float):
    """Returns (should_close: bool, reason: str)."""
    et = to_et(ts_utc)
    # VIX crisis
    if not np.isnan(vix_val) and vix_val >= 35.0:
        return True, 'VIX_CRISIS'
    # Friday 3:30 PM ET
    if et.weekday() == 4 and (et.hour > 15 or (et.hour == 15 and et.minute >= 30)):
        return True, 'FRI_WEEKEND'
    # OpEx Thursday 3:00 PM ET (Thursday with dayofmonth 14-20 = Thursday before 3rd Friday)
    if et.weekday() == 3 and 14 <= et.day <= 20 and et.hour >= 15:
        return True, 'OPEX_THU'
    # DAY setup end-of-day 3:00 PM ET
    if setup_name in DAY_SETUPS and et.hour >= 15:
        return True, 'DAY_EOD'
    return False, ''


def run_backtest_v4_with_extras(df, signals, extras):
    """v4 backtest + extra mechanical exits."""
    atr_val = extras['atr'].values
    in_uptrend = extras['in_uptrend'].values
    in_downtrend = extras['in_downtrend'].values
    regime = extras['regime'].values
    vix_15m = extras['vix_15m'].values
    vix_bin = extras['vix_bin'].values

    high = df['high'].values
    low = df['low'].values
    close_arr = df['close'].values
    times = df.index
    n_bars = len(df)

    signal_arrays = {name: s.values for name, s in signals.items()}
    trades = []
    active = None
    active_extra_r = None  # tracks R for early-close trades
    active_close_reason = None

    for i in range(n_bars):
        if active is not None:
            if active.direction == 'CALL':
                hit_target = high[i] >= active.target
                hit_stop = low[i] <= active.stop
            else:
                hit_target = low[i] <= active.target
                hit_stop = high[i] >= active.stop
            bars_since = i - active.fire_bar_idx

            # Extras exits check
            should_extras_close, extras_reason = force_close_extras(
                active.setup_name, times[i], vix_15m[i]
            )

            if bars_since > 0:
                # Priority: TP > SL > TIMEOUT > extras
                if hit_target and hit_stop:
                    active.outcome = 'LOSS'
                    active_extra_r = None
                    active_close_reason = 'TP_AND_SL_SAME_BAR'
                elif hit_target:
                    active.outcome = 'WIN'
                    active_extra_r = None
                    active_close_reason = 'TP'
                elif hit_stop:
                    active.outcome = 'LOSS'
                    active_extra_r = None
                    active_close_reason = 'SL'
                elif bars_since >= TIMEOUT_BARS:
                    active.outcome = 'TIMEOUT'
                    active_extra_r = 0.0
                    active_close_reason = 'TIMEOUT'
                elif should_extras_close:
                    # Extras-close: compute actual R from bar close
                    if active.direction == 'CALL':
                        r = (close_arr[i] - active.entry) / (active.entry - active.stop)
                    else:
                        r = (active.entry - close_arr[i]) / (active.stop - active.entry)
                    if r > 0:
                        active.outcome = 'WIN'  # partial win
                    elif r < 0:
                        active.outcome = 'LOSS'  # partial loss
                    else:
                        active.outcome = 'TIMEOUT'
                    active_extra_r = r
                    active_close_reason = extras_reason

                if active.outcome != 'OPEN':
                    active.close_bar_idx = i
                    active.close_time = times[i]
                    trades.append((active, active_extra_r, active_close_reason))
                    active = None
                    active_extra_r = None
                    active_close_reason = None

        if active is not None:
            continue

        # Fire logic — same as v4
        current_regime = regime[i]
        setup_name = None
        direction = None
        for name in V4_PRIORITY:
            if name not in signal_arrays:
                continue
            if not signal_arrays[name][i]:
                continue
            allowed_regimes = REGIME_RULES.get(name, set())
            if current_regime not in allowed_regimes:
                continue
            is_bull_setup = name in BULL_SETUP_NAMES
            if is_bull_setup and not in_uptrend[i]:
                continue
            if not is_bull_setup and not in_downtrend[i]:
                continue
            setup_name = name
            direction = 'CALL' if is_bull_setup else 'PUT'
            break

        if setup_name is None:
            continue

        entry = close_arr[i]
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
            fire_bar_idx=i, fire_time=times[i],
            direction=direction, setup_name=setup_name,
            entry=entry, stop=stop, target=target,
            vix_at_fire=vix_15m[i] if not np.isnan(vix_15m[i]) else np.nan,
            vix_bin=vix_bin[i] if isinstance(vix_bin[i], str) else 'mid',
        )
        active_extra_r = None
        active_close_reason = None

    if active is not None:
        trades.append((active, active_extra_r, active_close_reason))

    rows = []
    for t, extra_r, reason in trades:
        if extra_r is not None:
            r = extra_r
        elif t.outcome == 'WIN':
            r = RR_TARGET
        elif t.outcome == 'LOSS':
            r = -1.0
        else:
            r = 0.0
        rows.append({
            'fire_time': t.fire_time,
            'setup': t.setup_name,
            'direction': t.direction,
            'outcome': t.outcome,
            'close_time': t.close_time,
            'r_multiple': r,
            'close_reason': reason or 'UNKNOWN',
            'regime': extras['regime'].values[t.fire_bar_idx],
        })
    return pd.DataFrame(rows)


def compound_5pct(r_series):
    """Compound wealth curve assuming 5% risk per trade."""
    m = 1.0 + 0.05 * r_series
    wealth = np.cumprod(m)
    if len(wealth) == 0:
        return 1.0, 0.0
    peak = np.maximum.accumulate(wealth)
    max_dd = ((peak - wealth) / peak).max()
    return wealth[-1], max_dd


def max_loss_streak(outcomes):
    cur = mx = 0
    for o in outcomes:
        if o == 'LOSS':
            cur += 1
            mx = max(mx, cur)
        elif o == 'WIN':
            cur = 0
    return mx


def analyze(trades: pd.DataFrame, label: str):
    if len(trades) == 0:
        return {'label': label, 'n': 0}
    n = len(trades)
    w = (trades['outcome'] == 'WIN').sum()
    l = (trades['outcome'] == 'LOSS').sum()
    to = (trades['outcome'] == 'TIMEOUT').sum()
    wr = 100 * w / max(1, w + l)
    total_r = trades['r_multiple'].sum()
    end_w, max_dd = compound_5pct(trades['r_multiple'].values)
    return {
        'label': label, 'n': n, 'w': w, 'l': l, 'to': to,
        'wr': wr, 'r': total_r,
        'end_5pct': (end_w - 1) * 100,
        'max_dd_5pct': max_dd * 100,
        'max_ls': max_loss_streak(trades['outcome'].values),
    }


def main():
    print("=" * 80)
    print("v4 baseline vs v4 + extra mechanical exits — 8.5-year comparison")
    print("=" * 80)

    spy = pd.read_parquet(DATA_DIR / "spy_15m.parquet")
    vix = pd.read_parquet(DATA_DIR / "vix_daily.parquet")
    print(f"Loaded {len(spy):,} SPY 15m bars, {len(vix):,} VIX daily bars")
    print(f"Date range: {spy.index[0]} → {spy.index[-1]}")

    print("\nComputing signals + regime...")
    signals, extras = compute_signals_v4(spy, vix)

    print("\n[1/2] Running v4 BASELINE (existing exit rules: TP / SL / 40-bar timeout)...")
    trades_baseline = run_backtest_v4(spy, signals, extras, use_regime_gates=True, use_trend_filter=True)

    print(f"[2/2] Running v4 + EXTRAS (adds Fri weekend / VIX crisis / OpEx Thu / DAY EOD)...")
    trades_extras = run_backtest_v4_with_extras(spy, signals, extras)

    baseline = analyze(trades_baseline, "v4 baseline")
    extras_stats = analyze(trades_extras, "v4 + extras")

    print("\n" + "=" * 80)
    print("RESULTS — Full 8.5-year period")
    print("=" * 80)
    print(f"{'Metric':<28} | {'Baseline':>14} | {'+ Extras':>14} | {'Δ':>10}")
    print("-" * 80)
    print(f"{'Trades':<28} | {baseline['n']:>14,} | {extras_stats['n']:>14,} | {extras_stats['n']-baseline['n']:>+10}")
    print(f"{'Win rate':<28} | {baseline['wr']:>13.1f}% | {extras_stats['wr']:>13.1f}% | {extras_stats['wr']-baseline['wr']:>+9.1f}pp")
    print(f"{'Total R':<28} | {baseline['r']:>+12.1f}R | {extras_stats['r']:>+12.1f}R | {extras_stats['r']-baseline['r']:>+8.1f}R")
    print(f"{'End @ 5% compound':<28} | {baseline['end_5pct']:>+13.0f}% | {extras_stats['end_5pct']:>+13.0f}% | {extras_stats['end_5pct']-baseline['end_5pct']:>+9.0f}pp")
    print(f"{'Max DD @ 5% compound':<28} | {baseline['max_dd_5pct']:>13.1f}% | {extras_stats['max_dd_5pct']:>13.1f}% | {extras_stats['max_dd_5pct']-baseline['max_dd_5pct']:>+9.1f}pp")
    print(f"{'Max loss streak':<28} | {baseline['max_ls']:>14} | {extras_stats['max_ls']:>14} | {extras_stats['max_ls']-baseline['max_ls']:>+10}")
    print("-" * 80)

    # Break down which extras rule triggered
    if len(trades_extras) > 0:
        print("\nEarly close breakdown (v4 + extras):")
        reason_counts = trades_extras['close_reason'].value_counts()
        for reason, cnt in reason_counts.items():
            r_for_reason = trades_extras[trades_extras['close_reason'] == reason]['r_multiple'].sum()
            print(f"  {reason:<20} : {cnt:>5} trades, {r_for_reason:>+7.1f}R total")

    # Verdict
    print("\n" + "=" * 80)
    print("VERDICT")
    print("=" * 80)
    r_delta = extras_stats['r'] - baseline['r']
    dd_delta = extras_stats['max_dd_5pct'] - baseline['max_dd_5pct']
    if r_delta > 0 and dd_delta <= 0:
        print(f"✅ EXTRAS RULES HELP: +{r_delta:.1f}R AND lower DD ({dd_delta:+.1f}pp). Keep in Pine.")
    elif r_delta > 0:
        print(f"⚠️  EXTRAS RULES: +{r_delta:.1f}R BUT DD increased ({dd_delta:+.1f}pp). Judgment call.")
    elif abs(r_delta) < 2.0:
        print(f"🟡 EXTRAS RULES NEUTRAL: {r_delta:+.1f}R — no meaningful edge. Optional.")
    else:
        print(f"❌ EXTRAS RULES HURT: {r_delta:+.1f}R. REMOVE from Pine.")
    print("=" * 80)


if __name__ == "__main__":
    main()
