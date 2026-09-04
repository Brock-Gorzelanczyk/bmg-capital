"""Strategy bake-off — test N strategies from vault research on ONE ticker.

Goal: find a strategy that survives the hygiene gate on TSLA.

Strategies tested (all long-only, daily bars):
  S1  Vol-scaled 12mo momentum + 200SMA regime filter (research/17 Barroso-Santa-Clara)
  S2  RSI(2) mean reversion + 200SMA regime filter (Connors)
  S3  Donchian 20/10 breakout with ATR stop (turtle-style)
  S4  TTM Squeeze breakout (research/34)
  S5  Buy-and-hold benchmark

Each strategy → trades DataFrame with r_multiple → hygiene-gated → ranked.

Winner is the strategy with the highest realistic-live R (post-haircut).
"""
from __future__ import annotations

import sys
from pathlib import Path
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from backtest_hygiene import compute_haircut


# ═══════════════════════════════════════════════════════════════════════
# LOAD DATA
# ═══════════════════════════════════════════════════════════════════════

DATA_CSV = Path(__file__).parent / "data" / "tsla_daily.csv"


def load_ticker(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    return df


# ═══════════════════════════════════════════════════════════════════════
# INDICATORS
# ═══════════════════════════════════════════════════════════════════════

def rsi(series: pd.Series, n: int) -> pd.Series:
    delta = series.diff()
    up = delta.clip(lower=0)
    dn = -delta.clip(upper=0)
    ma_up = up.ewm(alpha=1 / n, adjust=False).mean()
    ma_dn = dn.ewm(alpha=1 / n, adjust=False).mean()
    rs = ma_up / ma_dn.replace(0, 1e-9)
    return 100 - (100 / (1 + rs))


def atr(high, low, close, n=14):
    tr = pd.concat([
        (high - low),
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def bollinger(close, n=20, k=2.0):
    ma = close.rolling(n).mean()
    sd = close.rolling(n).std()
    return ma, ma + k * sd, ma - k * sd


def keltner(high, low, close, n=20, k=1.5):
    ma = close.rolling(n).mean()
    a = atr(high, low, close, n)
    return ma, ma + k * a, ma - k * a


# ═══════════════════════════════════════════════════════════════════════
# STRATEGY 1 — Vol-scaled 12mo momentum (Barroso-Santa-Clara 2015)
# ═══════════════════════════════════════════════════════════════════════

def strategy_vol_scaled_momentum(df: pd.DataFrame, target_vol_ann: float = 0.15) -> list[dict]:
    close = df["close"]
    # 12mo momentum = return over t-252 to t-21 (skip most recent month per Jegadeesh)
    momentum = close.shift(21) / close.shift(252) - 1
    sma200 = close.rolling(200).mean()
    # Realized vol = 20d std * sqrt(252)
    daily_ret = close.pct_change()
    real_vol_ann = daily_ret.rolling(20).std() * np.sqrt(252)
    # Position weight = target_vol / realized_vol, clamped [0.3, 2.0]
    weight = (target_vol_ann / real_vol_ann.replace(0, 1e-9)).clip(0.3, 2.0)

    trades = []
    in_pos = False
    entry_idx = None
    entry_price = None
    entry_atr = None
    entry_weight = None
    atr14 = atr(df["high"], df["low"], close, 14)

    for i in range(252, len(df)):
        cur_close = close.iloc[i]
        cur_sma = sma200.iloc[i]
        cur_mom = momentum.iloc[i]

        if not in_pos:
            # Enter long if 12mo momentum positive AND above 200SMA
            if pd.notna(cur_mom) and cur_mom > 0 and cur_close > cur_sma:
                in_pos = True
                entry_idx = i
                entry_price = cur_close
                entry_atr = atr14.iloc[i] if pd.notna(atr14.iloc[i]) else cur_close * 0.02
                entry_weight = weight.iloc[i] if pd.notna(weight.iloc[i]) else 1.0
        else:
            # Exit if momentum turns negative OR breaks below 200SMA
            exit_now = (pd.notna(cur_mom) and cur_mom < 0) or (cur_close < cur_sma * 0.95)
            if exit_now:
                r_stop = entry_atr * 2.0  # 2-ATR stop reference for R math
                r_multiple = (cur_close - entry_price) / r_stop * entry_weight
                trades.append({
                    "strategy": "S1_vol_scaled_momentum",
                    "entry_date": df.index[entry_idx],
                    "exit_date": df.index[i],
                    "entry_price": entry_price,
                    "exit_price": cur_close,
                    "r_multiple": r_multiple,
                    "outcome": "WIN" if r_multiple > 0 else "LOSS",
                    "hold_days": i - entry_idx,
                    "weight": entry_weight,
                })
                in_pos = False
    return trades


# ═══════════════════════════════════════════════════════════════════════
# STRATEGY 2 — RSI(2) mean reversion + 200SMA filter (Connors)
# ═══════════════════════════════════════════════════════════════════════

def strategy_rsi2_meanrev(df: pd.DataFrame) -> list[dict]:
    close = df["close"]
    rsi2 = rsi(close, 2)
    sma200 = close.rolling(200).mean()
    atr14 = atr(df["high"], df["low"], close, 14)

    trades = []
    in_pos = False
    entry_idx = None
    entry_price = None
    entry_atr = None

    for i in range(200, len(df)):
        cur_close = close.iloc[i]
        cur_rsi = rsi2.iloc[i]
        cur_sma = sma200.iloc[i]

        if not in_pos:
            # Enter long: RSI(2) < 10 AND price above 200SMA (regime filter)
            if pd.notna(cur_rsi) and cur_rsi < 10 and cur_close > cur_sma:
                in_pos = True
                entry_idx = i
                entry_price = cur_close
                entry_atr = atr14.iloc[i] if pd.notna(atr14.iloc[i]) else cur_close * 0.02
        else:
            # Exit: RSI(2) > 65 (Connors classic exit)
            if pd.notna(cur_rsi) and cur_rsi > 65:
                r_stop = entry_atr * 2.0
                r_multiple = (cur_close - entry_price) / r_stop
                trades.append({
                    "strategy": "S2_rsi2_meanrev",
                    "entry_date": df.index[entry_idx],
                    "exit_date": df.index[i],
                    "entry_price": entry_price,
                    "exit_price": cur_close,
                    "r_multiple": r_multiple,
                    "outcome": "WIN" if r_multiple > 0 else "LOSS",
                    "hold_days": i - entry_idx,
                    "weight": 1.0,
                })
                in_pos = False
    return trades


# ═══════════════════════════════════════════════════════════════════════
# STRATEGY 3 — Donchian 20/10 breakout (turtle-style)
# ═══════════════════════════════════════════════════════════════════════

def strategy_donchian(df: pd.DataFrame) -> list[dict]:
    high = df["high"]
    low = df["low"]
    close = df["close"]
    dc_up = high.rolling(20).max()
    dc_dn_exit = low.rolling(10).min()
    atr14 = atr(high, low, close, 14)

    trades = []
    in_pos = False
    entry_idx = None
    entry_price = None
    entry_atr = None

    for i in range(20, len(df)):
        cur_close = close.iloc[i]
        cur_high = high.iloc[i]
        cur_low = low.iloc[i]
        prior_dc_up = dc_up.iloc[i - 1]
        prior_dc_dn = dc_dn_exit.iloc[i - 1]

        if not in_pos:
            # Enter long on close above 20-day high
            if pd.notna(prior_dc_up) and cur_close > prior_dc_up:
                in_pos = True
                entry_idx = i
                entry_price = cur_close
                entry_atr = atr14.iloc[i] if pd.notna(atr14.iloc[i]) else cur_close * 0.02
        else:
            # Exit on close below 10-day low OR 2-ATR stop
            stop_price = entry_price - 2 * entry_atr
            if (pd.notna(prior_dc_dn) and cur_close < prior_dc_dn) or cur_low < stop_price:
                # Use stop_price if that's what got hit, else exit at close
                exit_price = min(cur_close, stop_price) if cur_low < stop_price else cur_close
                r_multiple = (exit_price - entry_price) / (2 * entry_atr)
                trades.append({
                    "strategy": "S3_donchian",
                    "entry_date": df.index[entry_idx],
                    "exit_date": df.index[i],
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "r_multiple": r_multiple,
                    "outcome": "WIN" if r_multiple > 0 else "LOSS",
                    "hold_days": i - entry_idx,
                    "weight": 1.0,
                })
                in_pos = False
    return trades


# ═══════════════════════════════════════════════════════════════════════
# STRATEGY 4 — TTM Squeeze (BB inside KC → expansion breakout)
# ═══════════════════════════════════════════════════════════════════════

def strategy_ttm_squeeze(df: pd.DataFrame) -> list[dict]:
    close = df["close"]
    high = df["high"]
    low = df["low"]
    bb_mid, bb_up, bb_dn = bollinger(close, 20, 2.0)
    kc_mid, kc_up, kc_dn = keltner(high, low, close, 20, 1.5)
    atr14 = atr(high, low, close, 14)

    # Squeeze fires when BB inside KC (low vol setup)
    in_squeeze = (bb_up < kc_up) & (bb_dn > kc_dn)
    # Squeeze release: was in squeeze yesterday, not today
    squeeze_release = in_squeeze.shift(1).fillna(False) & (~in_squeeze)
    # Momentum direction (Linear Regression slope proxy)
    mom = close - close.rolling(20).mean()

    trades = []
    in_pos = False
    entry_idx = None
    entry_price = None
    entry_atr = None

    for i in range(30, len(df)):
        cur_close = close.iloc[i]

        if not in_pos:
            if squeeze_release.iloc[i] and mom.iloc[i] > 0:
                in_pos = True
                entry_idx = i
                entry_price = cur_close
                entry_atr = atr14.iloc[i] if pd.notna(atr14.iloc[i]) else cur_close * 0.02
        else:
            hold_days = i - entry_idx
            # Exit at 2-ATR profit, 1-ATR stop, or 20 bars
            profit_target = entry_price + 2 * entry_atr
            stop_price = entry_price - 1 * entry_atr
            if cur_close >= profit_target or cur_close <= stop_price or hold_days >= 20:
                exit_price = cur_close
                r_multiple = (exit_price - entry_price) / entry_atr
                trades.append({
                    "strategy": "S4_ttm_squeeze",
                    "entry_date": df.index[entry_idx],
                    "exit_date": df.index[i],
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "r_multiple": r_multiple,
                    "outcome": "WIN" if r_multiple > 0 else "LOSS",
                    "hold_days": hold_days,
                    "weight": 1.0,
                })
                in_pos = False
    return trades


# ═══════════════════════════════════════════════════════════════════════
# STRATEGY 4b — TTM Squeeze + volume confirm (research/34 exact spec)
# ═══════════════════════════════════════════════════════════════════════

def strategy_ttm_squeeze_v2(df: pd.DataFrame) -> list[dict]:
    """Same as S4 but requires volume > 1.2× 20d avg on breakout day + wider profit target."""
    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]
    bb_mid, bb_up, bb_dn = bollinger(close, 20, 2.0)
    kc_mid, kc_up, kc_dn = keltner(high, low, close, 20, 1.5)
    atr14 = atr(high, low, close, 14)
    vol_avg = volume.rolling(20).mean()

    in_squeeze = (bb_up < kc_up) & (bb_dn > kc_dn)
    squeeze_release = in_squeeze.shift(1).fillna(False) & (~in_squeeze)
    mom = close - close.rolling(20).mean()

    trades = []
    in_pos = False
    entry_idx = None
    entry_price = None
    entry_atr = None

    for i in range(30, len(df)):
        cur_close = close.iloc[i]
        cur_vol = volume.iloc[i]
        cur_vol_avg = vol_avg.iloc[i]

        if not in_pos:
            vol_confirm = pd.notna(cur_vol_avg) and cur_vol > 1.2 * cur_vol_avg
            if squeeze_release.iloc[i] and mom.iloc[i] > 0 and vol_confirm:
                in_pos = True
                entry_idx = i
                entry_price = cur_close
                entry_atr = atr14.iloc[i] if pd.notna(atr14.iloc[i]) else cur_close * 0.02
        else:
            hold_days = i - entry_idx
            # Wider profit target (3-ATR), 1.5-ATR stop, or 30 bars
            profit_target = entry_price + 3 * entry_atr
            stop_price = entry_price - 1.5 * entry_atr
            if cur_close >= profit_target or cur_close <= stop_price or hold_days >= 30:
                exit_price = cur_close
                r_multiple = (exit_price - entry_price) / (1.5 * entry_atr)
                trades.append({
                    "strategy": "S4b_squeeze_vol_confirm",
                    "entry_date": df.index[entry_idx],
                    "exit_date": df.index[i],
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "r_multiple": r_multiple,
                    "outcome": "WIN" if r_multiple > 0 else "LOSS",
                    "hold_days": hold_days,
                    "weight": 1.0,
                })
                in_pos = False
    return trades


# ═══════════════════════════════════════════════════════════════════════
# STRATEGY 6 — MA crossover (10/50) — simple trend catcher
# ═══════════════════════════════════════════════════════════════════════

def strategy_ma_cross(df: pd.DataFrame) -> list[dict]:
    close = df["close"]
    fast = close.rolling(10).mean()
    slow = close.rolling(50).mean()
    atr14 = atr(df["high"], df["low"], close, 14)

    cross_up = (fast > slow) & (fast.shift(1) <= slow.shift(1))
    cross_dn = (fast < slow) & (fast.shift(1) >= slow.shift(1))

    trades = []
    in_pos = False
    entry_idx = None
    entry_price = None
    entry_atr = None

    for i in range(50, len(df)):
        cur_close = close.iloc[i]
        if not in_pos:
            if cross_up.iloc[i]:
                in_pos = True
                entry_idx = i
                entry_price = cur_close
                entry_atr = atr14.iloc[i] if pd.notna(atr14.iloc[i]) else cur_close * 0.02
        else:
            if cross_dn.iloc[i]:
                r_multiple = (cur_close - entry_price) / (2 * entry_atr)
                trades.append({
                    "strategy": "S6_ma_cross_10_50",
                    "entry_date": df.index[entry_idx],
                    "exit_date": df.index[i],
                    "entry_price": entry_price,
                    "exit_price": cur_close,
                    "r_multiple": r_multiple,
                    "outcome": "WIN" if r_multiple > 0 else "LOSS",
                    "hold_days": i - entry_idx,
                    "weight": 1.0,
                })
                in_pos = False
    return trades


# ═══════════════════════════════════════════════════════════════════════
# STRATEGY 7 — Volatility Contraction Pattern (Minervini VCP proxy)
# ═══════════════════════════════════════════════════════════════════════

def strategy_vcp(df: pd.DataFrame) -> list[dict]:
    """Simple VCP proxy: 3+ consecutive weeks of tightening range + break above pivot high."""
    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]
    atr14 = atr(high, low, close, 14)
    # Weekly range = high-low over each rolling 5-day window
    weekly_range = (high.rolling(5).max() - low.rolling(5).min()) / close
    # Contraction: current week range < prior week range < 2-weeks-ago range
    contracting = (weekly_range < weekly_range.shift(5)) & (weekly_range.shift(5) < weekly_range.shift(10))
    # Pivot = 20d high; breakout = close above pivot
    pivot = high.rolling(20).max()
    breakout = close > pivot.shift(1)
    vol_avg = volume.rolling(20).mean()
    vol_ok = volume > 1.3 * vol_avg
    sma200 = close.rolling(200).mean()

    trades = []
    in_pos = False
    entry_idx = None
    entry_price = None
    entry_atr = None

    for i in range(210, len(df)):
        cur_close = close.iloc[i]
        if not in_pos:
            if (contracting.iloc[i] and breakout.iloc[i] and vol_ok.iloc[i]
                    and cur_close > sma200.iloc[i]):
                in_pos = True
                entry_idx = i
                entry_price = cur_close
                entry_atr = atr14.iloc[i] if pd.notna(atr14.iloc[i]) else cur_close * 0.02
        else:
            hold_days = i - entry_idx
            # Minervini exit: 3-ATR stop, 25% profit, or 8-week timeout
            stop_price = entry_price - 3 * entry_atr
            profit_target = entry_price * 1.25
            if cur_close <= stop_price or cur_close >= profit_target or hold_days >= 40:
                exit_price = cur_close
                r_multiple = (exit_price - entry_price) / (3 * entry_atr)
                trades.append({
                    "strategy": "S7_vcp_minervini",
                    "entry_date": df.index[entry_idx],
                    "exit_date": df.index[i],
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "r_multiple": r_multiple,
                    "outcome": "WIN" if r_multiple > 0 else "LOSS",
                    "hold_days": hold_days,
                    "weight": 1.0,
                })
                in_pos = False
    return trades


# ═══════════════════════════════════════════════════════════════════════
# STRATEGY 5 — Buy-and-hold benchmark
# ═══════════════════════════════════════════════════════════════════════

def strategy_buyhold(df: pd.DataFrame) -> list[dict]:
    close = df["close"]
    entry_price = close.iloc[0]
    exit_price = close.iloc[-1]
    # R multiple with a nominal 20% "stop distance" for comparability
    r_multiple = (exit_price - entry_price) / (entry_price * 0.20)
    return [{
        "strategy": "S5_buyhold",
        "entry_date": df.index[0],
        "exit_date": df.index[-1],
        "entry_price": entry_price,
        "exit_price": exit_price,
        "r_multiple": r_multiple,
        "outcome": "WIN" if r_multiple > 0 else "LOSS",
        "hold_days": len(df),
        "weight": 1.0,
    }]


# ═══════════════════════════════════════════════════════════════════════
# BAKE-OFF
# ═══════════════════════════════════════════════════════════════════════

def analyze(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0, "wr": 0, "r": 0, "avg_r": 0}
    n = len(trades)
    w = sum(1 for t in trades if t["outcome"] == "WIN")
    l = sum(1 for t in trades if t["outcome"] == "LOSS")
    r = sum(t["r_multiple"] for t in trades)
    wr = 100 * w / max(1, w + l)
    return {"n": n, "w": w, "l": l, "wr": wr, "r": r, "avg_r": r / n}


def main():
    df = load_ticker(DATA_CSV)
    years = (df.index[-1] - df.index[0]).days / 365.25
    print(f"Ticker: TSLA · bars: {len(df):,} · period: {df.index[0].date()} → {df.index[-1].date()} ({years:.1f} yrs)")
    print("=" * 90)

    strategies = [
        ("S1 vol-scaled 12mo momentum",      strategy_vol_scaled_momentum),
        ("S2 RSI(2) mean reversion",         strategy_rsi2_meanrev),
        ("S3 Donchian 20/10 breakout",       strategy_donchian),
        ("S4 TTM squeeze breakout",          strategy_ttm_squeeze),
        ("S4b TTM squeeze + volume confirm", strategy_ttm_squeeze_v2),
        ("S6 MA cross 10/50",                strategy_ma_cross),
        ("S7 VCP (Minervini)",               strategy_vcp),
        ("S5 Buy-and-hold",                  strategy_buyhold),
    ]

    results = []
    for name, fn in strategies:
        trades = fn(df)
        stats = analyze(trades)
        results.append({"name": name, "stats": stats, "trades": trades})

    # Raw ranking
    print(f"\n{'Strategy':<35} {'N':>5} {'WR%':>6} {'Total R':>10} {'Avg R':>8}")
    print("-" * 90)
    for r in sorted(results, key=lambda x: -x["stats"]["r"]):
        s = r["stats"]
        print(f"{r['name']:<35} {s['n']:>5} {s['wr']:>5.1f}% {s['r']:>+9.1f}R {s['avg_r']:>+7.3f}R")

    # Hygiene-gate each strategy
    print("\n" + "=" * 90)
    print("HYGIENE-GATED (McLean-Pontiff × 0.35 + Robinhood exec drag + 0.70× options gap)")
    print("=" * 90)
    print(f"\n{'Strategy':<35} {'Raw R':>8} {'Realistic':>18} {'Kelly-safe':>12} {'CAGR@safe':>16}")
    print("-" * 90)

    hygiene_rows = []
    for r in results:
        s = r["stats"]
        if s["n"] == 0:
            continue
        hc = compute_haircut(
            raw_r=s["r"],
            n_trades=s["n"],
            wr_pct=s["wr"],
            avg_rr=abs(s["avg_r"]) if s["avg_r"] != 0 else 1.0,
            declared_sizing_pct=5.0,
            # Parameters are from published research (Barroso, Connors, Bollinger, Carter, etc.)
            # NOT fit to this TSLA data — so in-sample decay doesn't apply the same way.
            in_sample_derived=False,
            execution_scenario="robinhood",
            years=years,
        )
        hygiene_rows.append({
            "name": r["name"],
            "raw_r": s["r"],
            "r_low": hc.realistic_r_low,
            "r_high": hc.realistic_r_high,
            "kelly": hc.kelly_safe_sizing_pct,
            "cagr_low": hc.realistic_annual_cagr_low * 100,
            "cagr_high": hc.realistic_annual_cagr_high * 100,
        })

    for h in sorted(hygiene_rows, key=lambda x: -x["r_high"]):
        rng = f"{h['r_low']:+6.1f}R to {h['r_high']:+6.1f}R"
        cagr = f"{h['cagr_low']:+5.1f}% to {h['cagr_high']:+5.1f}%"
        print(f"{h['name']:<35} {h['raw_r']:>+7.1f}R {rng:>18} {h['kelly']:>10.2f}% {cagr:>16}")

    # Winner
    winner = max(hygiene_rows, key=lambda x: x["r_high"])
    print("\n" + "=" * 90)
    print(f"🏆 WINNER (best realistic-high): {winner['name']}")
    print(f"   Realistic live: {winner['r_low']:+.1f}R to {winner['r_high']:+.1f}R over {years:.1f} yrs")
    print(f"   Annual CAGR at Kelly-safe {winner['kelly']:.2f}%: {winner['cagr_low']:+.1f}% to {winner['cagr_high']:+.1f}%")
    print("=" * 90)

    return results, hygiene_rows, winner


if __name__ == "__main__":
    main()
