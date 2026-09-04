"""Wave 3 — AI infrastructure basket + VIX regime filter on momentum winners.

TESTS TWO HYPOTHESES:

H1 (AI basket): Does an equal-weight basket of {SMCI, NVDA, AVGO, PLTR, AMD}
    with monthly rebalance BEAT holding individual winners? Also tests top-K
    variant (hold only 3 highest-momentum names).

H2 (VIX filter): Does adding a "VIX < 25" filter to 6mo momentum + 200SMA
    strategy IMPROVE Sharpe / REDUCE max DD on the 4 confirmed winners?

Data pulled from `scripts/backtest/data/multi/{TICKER}_daily.csv` + vix_daily.parquet.
Writes results to research/66-wave3-basket-and-filters.md.
"""
from __future__ import annotations

import sys
from pathlib import Path
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from backtest_hygiene import compute_haircut

DATA_MULTI = Path(__file__).parent / "data" / "multi"
VIX_PATH = Path(__file__).parent / "data" / "vix_daily.parquet"
VAULT_NOTE = Path.home() / "Documents" / "BMG-Capital-Vault" / "research" / "66-wave3-basket-and-filters.md"

AI_UNIVERSE = ["SMCI", "NVDA", "AVGO", "PLTR", "AMD"]
MOMENTUM_TICKERS = ["SMCI", "NVDA", "AVGO", "PLTR"]  # wave 2 confirmed winners


def load_ticker(t: str) -> pd.DataFrame | None:
    p = DATA_MULTI / f"{t}_daily.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p)
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()


def load_vix() -> pd.DataFrame:
    df = pd.read_parquet(VIX_PATH)
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    return df


def atr(high, low, close, n=14):
    tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


# ═══════════════════════════════════════════════════════════════════════
# H1: AI INFRASTRUCTURE BASKET
# ═══════════════════════════════════════════════════════════════════════

def strategy_basket_monthly_rebalance(dfs: dict, variant: str = "equal") -> pd.Series:
    """Simulate monthly rebalance of AI basket.

    variant:
      "equal"  → equal weight across all universe names
      "risk_parity" → 1/vol weighted
      "top_k"  → hold only top-3 by 6mo momentum
    Returns daily portfolio return series.
    """
    # Build joint frame of closes
    closes = pd.DataFrame({t: df["close"] for t, df in dfs.items()}).dropna()
    daily_ret = closes.pct_change().fillna(0)

    n_names = len(closes.columns)
    weights = pd.DataFrame(0.0, index=closes.index, columns=closes.columns)

    # Compute rolling 6mo momentum
    mom6 = closes.shift(21) / closes.shift(126) - 1
    sma200 = closes.rolling(200).mean()

    # Monthly rebalance dates
    month_ends = closes.resample("ME").last().index

    current_weights = pd.Series(0.0, index=closes.columns)
    for i, dt in enumerate(closes.index):
        if dt in month_ends or i == 200:
            # Determine which names qualify (mom6 > 0 AND close > 200sma)
            row_mom = mom6.loc[dt]
            row_sma = sma200.loc[dt]
            row_close = closes.loc[dt]
            qualifying = [t for t in closes.columns
                          if pd.notna(row_mom[t]) and row_mom[t] > 0
                          and pd.notna(row_sma[t]) and row_close[t] > row_sma[t]]

            if len(qualifying) == 0:
                current_weights = pd.Series(0.0, index=closes.columns)
            elif variant == "equal":
                w = 1.0 / len(qualifying)
                current_weights = pd.Series({t: (w if t in qualifying else 0.0) for t in closes.columns})
            elif variant == "risk_parity":
                vols = daily_ret[qualifying].iloc[-60:].std() * np.sqrt(252)
                inv_vol = 1.0 / vols.replace(0, np.nan)
                inv_vol = inv_vol / inv_vol.sum()
                current_weights = pd.Series({t: (inv_vol.get(t, 0.0) if t in qualifying else 0.0) for t in closes.columns})
            elif variant == "top_k":
                # Hold only top-3 by momentum
                q_moms = row_mom[qualifying].sort_values(ascending=False)
                top_names = q_moms.head(3).index.tolist()
                w = 1.0 / len(top_names) if top_names else 0.0
                current_weights = pd.Series({t: (w if t in top_names else 0.0) for t in closes.columns})
        weights.loc[dt] = current_weights.values

    # Portfolio daily return = sum(weight_t-1 * ret_t)
    port_ret = (weights.shift(1) * daily_ret).sum(axis=1)
    return port_ret


def perf_stats(returns: pd.Series, label: str) -> dict:
    r = returns.dropna()
    if len(r) == 0:
        return {"label": label, "n": 0}
    cum = (1 + r).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    years = (r.index[-1] - r.index[0]).days / 365.25
    total_ret = cum.iloc[-1] - 1
    cagr = (cum.iloc[-1]) ** (1 / years) - 1 if years > 0 else 0
    sharpe = r.mean() / r.std() * np.sqrt(252) if r.std() > 0 else 0
    return {
        "label": label,
        "n_bars": len(r),
        "total_return": total_ret,
        "cagr": cagr,
        "sharpe": sharpe,
        "max_dd": dd.min(),
        "years": years,
    }


# ═══════════════════════════════════════════════════════════════════════
# H2: MOMENTUM + VIX REGIME FILTER
# ═══════════════════════════════════════════════════════════════════════

def strategy_momentum(df: pd.DataFrame, ticker: str, vix_daily: pd.DataFrame | None = None,
                      vix_max: float | None = None) -> list[dict]:
    """6mo momentum + 200SMA, optionally with VIX < vix_max filter."""
    close = df["close"]
    mom6 = close.shift(21) / close.shift(126) - 1
    sma200 = close.rolling(200).mean()
    atr14 = atr(df["high"], df["low"], close, 14)

    # Align VIX if provided (daily-close lookup)
    vix_series = None
    if vix_daily is not None:
        v = vix_daily["close"].copy()
        # Map by date
        vix_series = pd.Series(index=close.index, dtype=float)
        for d in close.index:
            d_date = d.normalize()
            # Find closest VIX date <= d
            mask = v.index <= d_date
            if mask.any():
                vix_series.loc[d] = v[mask].iloc[-1]

    trades = []
    in_pos = False
    entry_idx = None
    entry_price = None
    entry_atr = None
    HOLD_BARS = 40  # ~8 weeks

    for i in range(200, len(df)):
        cur_close = close.iloc[i]
        cur_mom = mom6.iloc[i]
        cur_sma = sma200.iloc[i]

        if not in_pos:
            entry_ok = (pd.notna(cur_mom) and cur_mom > 0
                        and pd.notna(cur_sma) and cur_close > cur_sma)
            if entry_ok and vix_max is not None and vix_series is not None:
                v = vix_series.iloc[i]
                if pd.notna(v) and v > vix_max:
                    entry_ok = False
            if entry_ok:
                in_pos = True
                entry_idx = i
                entry_price = cur_close
                entry_atr = atr14.iloc[i] if pd.notna(atr14.iloc[i]) else cur_close * 0.02
        else:
            hold = i - entry_idx
            stop_price = entry_price - 2 * entry_atr
            # Exit conditions: hold ≥ 40 bars, or break below 200sma×0.95, or ATR stop
            exit_now = (hold >= HOLD_BARS
                        or cur_close < cur_sma * 0.95
                        or df["low"].iloc[i] < stop_price)
            if exit_now:
                exit_price = min(cur_close, stop_price) if df["low"].iloc[i] < stop_price else cur_close
                r = (exit_price - entry_price) / (2 * entry_atr)
                trades.append({
                    "ticker": ticker,
                    "entry_date": df.index[entry_idx],
                    "exit_date": df.index[i],
                    "r_multiple": r,
                    "outcome": "WIN" if r > 0 else "LOSS",
                    "hold_days": hold,
                })
                in_pos = False
    return trades


def analyze_trades(trades: list[dict], label: str) -> dict:
    if not trades:
        return {"label": label, "n": 0, "wr": 0, "r": 0, "sharpe": 0, "max_dd": 0}
    n = len(trades)
    w = sum(1 for t in trades if t["outcome"] == "WIN")
    r = sum(t["r_multiple"] for t in trades)
    # Equity curve for Sharpe/DD
    equity = [0.0]
    for t in trades:
        equity.append(equity[-1] + t["r_multiple"])
    eq = np.array(equity)
    peak = np.maximum.accumulate(eq)
    dd = (eq - peak).min()  # max drawdown in R
    returns = np.diff(eq)
    sharpe = returns.mean() / returns.std() * np.sqrt(len(returns) / max(1, (trades[-1]["exit_date"] - trades[0]["entry_date"]).days / 365.25)) if returns.std() > 0 else 0
    return {
        "label": label,
        "n": n,
        "wr": 100 * w / n,
        "r": r,
        "avg_r": r / n,
        "max_dd_r": dd,
        "sharpe": sharpe,
    }


def main():
    print("=" * 80)
    print("WAVE 3 — AI Infrastructure Basket + VIX Regime Filter")
    print("=" * 80)

    # Load data
    ai_dfs = {t: load_ticker(t) for t in AI_UNIVERSE}
    ai_dfs = {t: d for t, d in ai_dfs.items() if d is not None}
    print(f"\nLoaded {len(ai_dfs)} tickers: {list(ai_dfs.keys())}")

    try:
        vix = load_vix()
        print(f"Loaded VIX: {len(vix)} bars, {vix.index[0].date()} → {vix.index[-1].date()}")
    except Exception as e:
        print(f"VIX load failed: {e}")
        vix = None

    # ── H1: AI BASKET ────────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("H1 — AI INFRASTRUCTURE BASKET")
    print("=" * 80)

    basket_variants = {}
    for variant in ["equal", "risk_parity", "top_k"]:
        ret = strategy_basket_monthly_rebalance(ai_dfs, variant)
        stats = perf_stats(ret, f"basket_{variant}")
        basket_variants[variant] = stats
        print(f"  basket_{variant:12}: CAGR {stats['cagr']*100:+.1f}%  Sharpe {stats['sharpe']:+.2f}  MaxDD {stats['max_dd']*100:.1f}%")

    # Benchmarks
    print("\nBenchmarks:")
    # SPY buy-and-hold
    spy = load_ticker("SPY")
    if spy is not None:
        spy_ret = spy["close"].pct_change().dropna()
        s = perf_stats(spy_ret, "SPY_bhold")
        print(f"  SPY buy-hold:        CAGR {s['cagr']*100:+.1f}%  Sharpe {s['sharpe']:+.2f}  MaxDD {s['max_dd']*100:.1f}%")
    smh = load_ticker("SMH")
    if smh is not None:
        smh_ret = smh["close"].pct_change().dropna()
        s = perf_stats(smh_ret, "SMH_bhold")
        print(f"  SMH buy-hold:        CAGR {s['cagr']*100:+.1f}%  Sharpe {s['sharpe']:+.2f}  MaxDD {s['max_dd']*100:.1f}%")

    # ── H2: MOMENTUM + VIX FILTER ────────────────────────────────────────
    print("\n" + "=" * 80)
    print("H2 — MOMENTUM + VIX < 25 FILTER on 4 confirmed winners")
    print("=" * 80)
    print(f"\n{'Ticker':<8} {'Config':<20} {'N':>4} {'WR%':>6} {'R':>8} {'Sharpe':>7} {'MaxDD_R':>8}")
    print("-" * 80)

    filter_results = {}
    for tkr in MOMENTUM_TICKERS:
        df = load_ticker(tkr)
        if df is None:
            continue
        # Baseline (no filter)
        base_trades = strategy_momentum(df, tkr, vix_daily=None, vix_max=None)
        base_stats = analyze_trades(base_trades, f"{tkr}_base")
        # With VIX filter
        vix_trades = strategy_momentum(df, tkr, vix_daily=vix, vix_max=25.0)
        vix_stats = analyze_trades(vix_trades, f"{tkr}_vixlt25")
        filter_results[tkr] = {"base": base_stats, "filtered": vix_stats}
        print(f"{tkr:<8} {'baseline':<20} {base_stats['n']:>4} {base_stats['wr']:>5.1f}% {base_stats['r']:>+7.1f}R {base_stats['sharpe']:>+6.2f} {base_stats['max_dd_r']:>+7.1f}R")
        print(f"{tkr:<8} {'VIX<25 filter':<20} {vix_stats['n']:>4} {vix_stats['wr']:>5.1f}% {vix_stats['r']:>+7.1f}R {vix_stats['sharpe']:>+6.2f} {vix_stats['max_dd_r']:>+7.1f}R")

    # Aggregate
    total_base_r = sum(r["base"]["r"] for r in filter_results.values())
    total_vix_r = sum(r["filtered"]["r"] for r in filter_results.values())
    total_base_dd = sum(r["base"]["max_dd_r"] for r in filter_results.values())
    total_vix_dd = sum(r["filtered"]["max_dd_r"] for r in filter_results.values())
    print(f"\nTotal R: baseline {total_base_r:+.1f}R vs VIX-filtered {total_vix_r:+.1f}R")
    print(f"Total MaxDD_R: baseline {total_base_dd:+.1f}R vs VIX-filtered {total_vix_dd:+.1f}R")

    verdict_h1_winner = max(basket_variants.items(), key=lambda x: x[1]["cagr"])
    print(f"\n🏆 H1 winner: {verdict_h1_winner[0]} (CAGR {verdict_h1_winner[1]['cagr']*100:+.1f}%)")
    h2_winner = "VIX filter HELPS" if (total_vix_r > total_base_r * 0.85 and total_vix_dd > total_base_dd) else "VIX filter HURTS (cuts too many trades)"
    print(f"🏆 H2 verdict: {h2_winner}")

    # Vault report
    with open(VAULT_NOTE, "w") as f:
        f.write("# 66 — Wave 3: AI Basket + VIX Regime Filter\n\n")
        f.write("Tests two Wave 3 hypotheses inline (background agents kept stalling).\n\n")
        f.write("## H1 — AI Infrastructure Basket (SMCI/NVDA/AVGO/PLTR/AMD)\n\n")
        f.write("Monthly-rebal equal-weight vs risk-parity vs top-K on 6mo momentum + 200SMA trigger.\n\n")
        f.write("| Variant | CAGR | Sharpe | MaxDD |\n|---|---|---|---|\n")
        for v, s in basket_variants.items():
            f.write(f"| basket_{v} | {s['cagr']*100:+.1f}% | {s['sharpe']:+.2f} | {s['max_dd']*100:.1f}% |\n")
        if spy is not None:
            spy_s = perf_stats(spy["close"].pct_change().dropna(), "SPY")
            f.write(f"| SPY buy-hold (benchmark) | {spy_s['cagr']*100:+.1f}% | {spy_s['sharpe']:+.2f} | {spy_s['max_dd']*100:.1f}% |\n")
        if smh is not None:
            smh_s = perf_stats(smh["close"].pct_change().dropna(), "SMH")
            f.write(f"| SMH buy-hold (benchmark) | {smh_s['cagr']*100:+.1f}% | {smh_s['sharpe']:+.2f} | {smh_s['max_dd']*100:.1f}% |\n")
        f.write(f"\n**H1 winner:** basket_{verdict_h1_winner[0]} — CAGR {verdict_h1_winner[1]['cagr']*100:+.1f}%, Sharpe {verdict_h1_winner[1]['sharpe']:+.2f}\n\n")

        f.write("## H2 — VIX < 25 Regime Filter\n\n")
        f.write("Compares 6mo Momentum + 200SMA baseline vs adding a `VIX daily close < 25` entry filter.\n\n")
        f.write("| Ticker | Config | N | WR% | Total R | Sharpe | MaxDD_R |\n|---|---|---|---|---|---|---|\n")
        for tkr, res in filter_results.items():
            b = res["base"]
            v = res["filtered"]
            f.write(f"| {tkr} | baseline | {b['n']} | {b['wr']:.1f}% | {b['r']:+.1f}R | {b['sharpe']:+.2f} | {b['max_dd_r']:+.1f}R |\n")
            f.write(f"| {tkr} | VIX<25 | {v['n']} | {v['wr']:.1f}% | {v['r']:+.1f}R | {v['sharpe']:+.2f} | {v['max_dd_r']:+.1f}R |\n")
        f.write(f"\n**Aggregate:** baseline {total_base_r:+.1f}R (DD {total_base_dd:+.1f}R) vs VIX-filtered {total_vix_r:+.1f}R (DD {total_vix_dd:+.1f}R)\n\n")
        f.write(f"**H2 verdict:** {h2_winner}\n\n")

    print(f"\n✅ Wrote {VAULT_NOTE}")


if __name__ == "__main__":
    main()
