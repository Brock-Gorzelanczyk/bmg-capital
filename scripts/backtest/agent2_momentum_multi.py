"""Agent 2: momentum / trend-following bake-off across 20 tickers.

Goal: find whether ANY momentum/trend strategy has real edge (post-hygiene) on
individual names, and where the edge concentrates.

Six strategies (all long-only, daily bars, published rules — NOT in-sample fit):
  M1  Vol-scaled 12mo momentum + 200SMA filter (Barroso-Santa-Clara 2015, research/17)
  M2  6mo momentum + 100SMA filter (shorter lookback trend)
  M3  3mo momentum + 50SMA filter (short-term momentum)
  M4  Kaufman Efficiency Ratio (KER > 0.3 enter on breakout, KER < 0.15 exit)
  M5  ADX(14) > 25 + DMI+ crosses DMI- → long, exit on DMI- cross
  M6  Weekly momentum on daily bars (5-day return > 2%, exit after 10 days)

Per (strategy × ticker): raw R, WR, N, post-hygiene R range, CAGR at Kelly-safe.
Ranking: all 120 combos by post-hygiene R_high.
Winner: post-hygiene R_high > 0 AND CAGR at Kelly-safe sizing > 5%.
"""
from __future__ import annotations

import sys
from pathlib import Path
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from backtest_hygiene import compute_haircut


# ═══════════════════════════════════════════════════════════════════════
# DATA
# ═══════════════════════════════════════════════════════════════════════

DATA_DIR = Path(__file__).parent / "data" / "multi"
TICKERS = [
    "TSLA", "NVDA", "MSTR", "COIN", "SMCI", "PLTR", "AMD", "META", "GOOG", "AAPL",
    "MSFT", "QQQ", "SPY", "IWM", "XLE", "ARKK", "SOFI", "HOOD", "GME", "AVGO",
]
VAULT_OUT = Path.home() / "Documents" / "BMG-Capital-Vault" / "research" / "50-momentum-multi-ticker-agent.md"


def load_ticker(ticker: str) -> pd.DataFrame:
    df = pd.read_csv(DATA_DIR / f"{ticker}_daily.csv")
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()


# ═══════════════════════════════════════════════════════════════════════
# INDICATORS
# ═══════════════════════════════════════════════════════════════════════

def atr(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    tr = pd.concat([
        (high - low),
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def kaufman_efficiency(close: pd.Series, n: int = 10) -> pd.Series:
    """KER = |close - close.shift(n)| / sum(|close.diff|, n).

    Range [0, 1]. High = trending; low = choppy.
    """
    direction = (close - close.shift(n)).abs()
    volatility = close.diff().abs().rolling(n).sum()
    return direction / volatility.replace(0, np.nan)


def dmi_adx(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14):
    """Wilder-smoothed +DI, -DI, ADX."""
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr = pd.concat([
        (high - low),
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)

    # Wilder smoothing = EMA with alpha=1/n
    tr_smooth = tr.ewm(alpha=1 / n, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm, index=high.index).ewm(alpha=1 / n, adjust=False).mean() / tr_smooth.replace(0, np.nan)
    minus_di = 100 * pd.Series(minus_dm, index=high.index).ewm(alpha=1 / n, adjust=False).mean() / tr_smooth.replace(0, np.nan)

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=1 / n, adjust=False).mean()
    return plus_di, minus_di, adx


# ═══════════════════════════════════════════════════════════════════════
# STRATEGIES
# ═══════════════════════════════════════════════════════════════════════

def m1_vol_scaled_12mo(df: pd.DataFrame, target_vol_ann: float = 0.15) -> list[dict]:
    close = df["close"]
    momentum = close.shift(21) / close.shift(252) - 1  # 12-1 mo momentum
    sma200 = close.rolling(200).mean()
    daily_ret = close.pct_change()
    real_vol_ann = daily_ret.rolling(20).std() * np.sqrt(252)
    weight = (target_vol_ann / real_vol_ann.replace(0, 1e-9)).clip(0.3, 2.0)
    atr14 = atr(df["high"], df["low"], close, 14)

    trades, in_pos = [], False
    entry_idx = entry_price = entry_atr = entry_weight = None

    for i in range(252, len(df)):
        cur_close = close.iloc[i]
        cur_sma = sma200.iloc[i]
        cur_mom = momentum.iloc[i]
        if not in_pos:
            if pd.notna(cur_mom) and cur_mom > 0 and cur_close > cur_sma:
                in_pos = True
                entry_idx, entry_price = i, cur_close
                entry_atr = atr14.iloc[i] if pd.notna(atr14.iloc[i]) else cur_close * 0.02
                entry_weight = weight.iloc[i] if pd.notna(weight.iloc[i]) else 1.0
        else:
            if (pd.notna(cur_mom) and cur_mom < 0) or (cur_close < cur_sma * 0.95):
                r_multiple = (cur_close - entry_price) / (2 * entry_atr) * entry_weight
                trades.append(_make_trade("M1_vol_scaled_12mo", df, entry_idx, i,
                                          entry_price, cur_close, r_multiple, entry_weight))
                in_pos = False
    return trades


def m2_mom_6mo(df: pd.DataFrame) -> list[dict]:
    close = df["close"]
    momentum = close.shift(10) / close.shift(126) - 1  # ~6mo skip most recent 2wk
    sma100 = close.rolling(100).mean()
    atr14 = atr(df["high"], df["low"], close, 14)

    trades, in_pos = [], False
    entry_idx = entry_price = entry_atr = None

    for i in range(126, len(df)):
        cur_close = close.iloc[i]
        cur_sma = sma100.iloc[i]
        cur_mom = momentum.iloc[i]
        if not in_pos:
            if pd.notna(cur_mom) and cur_mom > 0 and cur_close > cur_sma:
                in_pos = True
                entry_idx, entry_price = i, cur_close
                entry_atr = atr14.iloc[i] if pd.notna(atr14.iloc[i]) else cur_close * 0.02
        else:
            if (pd.notna(cur_mom) and cur_mom < 0) or (cur_close < cur_sma * 0.95):
                r_multiple = (cur_close - entry_price) / (2 * entry_atr)
                trades.append(_make_trade("M2_mom_6mo", df, entry_idx, i,
                                          entry_price, cur_close, r_multiple, 1.0))
                in_pos = False
    return trades


def m3_mom_3mo(df: pd.DataFrame) -> list[dict]:
    close = df["close"]
    momentum = close.shift(5) / close.shift(63) - 1  # ~3mo skip most recent week
    sma50 = close.rolling(50).mean()
    atr14 = atr(df["high"], df["low"], close, 14)

    trades, in_pos = [], False
    entry_idx = entry_price = entry_atr = None

    for i in range(63, len(df)):
        cur_close = close.iloc[i]
        cur_sma = sma50.iloc[i]
        cur_mom = momentum.iloc[i]
        if not in_pos:
            if pd.notna(cur_mom) and cur_mom > 0 and cur_close > cur_sma:
                in_pos = True
                entry_idx, entry_price = i, cur_close
                entry_atr = atr14.iloc[i] if pd.notna(atr14.iloc[i]) else cur_close * 0.02
        else:
            if (pd.notna(cur_mom) and cur_mom < 0) or (cur_close < cur_sma * 0.95):
                r_multiple = (cur_close - entry_price) / (2 * entry_atr)
                trades.append(_make_trade("M3_mom_3mo", df, entry_idx, i,
                                          entry_price, cur_close, r_multiple, 1.0))
                in_pos = False
    return trades


def m4_ker(df: pd.DataFrame) -> list[dict]:
    """Kaufman Efficiency Ratio. Enter when KER > 0.3 AND breakout of 20d high.
    Exit when KER < 0.15 (regime shift to chop) OR 2-ATR stop.
    """
    close = df["close"]
    high = df["high"]
    low = df["low"]
    ker = kaufman_efficiency(close, n=10)
    dc_up = high.rolling(20).max()
    atr14 = atr(high, low, close, 14)

    trades, in_pos = [], False
    entry_idx = entry_price = entry_atr = None

    for i in range(20, len(df)):
        cur_close = close.iloc[i]
        prior_dc = dc_up.iloc[i - 1]
        cur_ker = ker.iloc[i]
        cur_low = low.iloc[i]
        if not in_pos:
            if (pd.notna(cur_ker) and cur_ker > 0.3
                    and pd.notna(prior_dc) and cur_close > prior_dc):
                in_pos = True
                entry_idx, entry_price = i, cur_close
                entry_atr = atr14.iloc[i] if pd.notna(atr14.iloc[i]) else cur_close * 0.02
        else:
            stop_price = entry_price - 2 * entry_atr
            if (pd.notna(cur_ker) and cur_ker < 0.15) or cur_low < stop_price:
                exit_price = min(cur_close, stop_price) if cur_low < stop_price else cur_close
                r_multiple = (exit_price - entry_price) / (2 * entry_atr)
                trades.append(_make_trade("M4_ker", df, entry_idx, i,
                                          entry_price, exit_price, r_multiple, 1.0))
                in_pos = False
    return trades


def m5_adx_dmi(df: pd.DataFrame) -> list[dict]:
    """ADX(14) > 25 + DMI+ crosses above DMI- → long. Exit on DMI- crosses above DMI+."""
    close = df["close"]
    high = df["high"]
    low = df["low"]
    plus_di, minus_di, adx = dmi_adx(high, low, close, 14)
    atr14 = atr(high, low, close, 14)

    trades, in_pos = [], False
    entry_idx = entry_price = entry_atr = None

    for i in range(30, len(df)):
        cur_close = close.iloc[i]
        cur_plus = plus_di.iloc[i]
        cur_minus = minus_di.iloc[i]
        prev_plus = plus_di.iloc[i - 1]
        prev_minus = minus_di.iloc[i - 1]
        cur_adx = adx.iloc[i]
        if any(pd.isna(x) for x in (cur_plus, cur_minus, prev_plus, prev_minus, cur_adx)):
            continue
        if not in_pos:
            bull_cross = (cur_plus > cur_minus) and (prev_plus <= prev_minus)
            if bull_cross and cur_adx > 25:
                in_pos = True
                entry_idx, entry_price = i, cur_close
                entry_atr = atr14.iloc[i] if pd.notna(atr14.iloc[i]) else cur_close * 0.02
        else:
            bear_cross = (cur_minus > cur_plus) and (prev_minus <= prev_plus)
            if bear_cross:
                r_multiple = (cur_close - entry_price) / (2 * entry_atr)
                trades.append(_make_trade("M5_adx_dmi", df, entry_idx, i,
                                          entry_price, cur_close, r_multiple, 1.0))
                in_pos = False
    return trades


def m6_weekly_mom(df: pd.DataFrame) -> list[dict]:
    """5-day return > 2% → enter next bar. Exit after 10 days OR 2-ATR stop."""
    close = df["close"]
    low = df["low"]
    ret5 = close / close.shift(5) - 1
    atr14 = atr(df["high"], df["low"], close, 14)

    trades, in_pos = [], False
    entry_idx = entry_price = entry_atr = None

    for i in range(6, len(df)):
        cur_close = close.iloc[i]
        cur_low = low.iloc[i]
        prev_ret5 = ret5.iloc[i - 1]
        if not in_pos:
            if pd.notna(prev_ret5) and prev_ret5 > 0.02:
                in_pos = True
                entry_idx, entry_price = i, cur_close
                entry_atr = atr14.iloc[i] if pd.notna(atr14.iloc[i]) else cur_close * 0.02
        else:
            hold_days = i - entry_idx
            stop_price = entry_price - 2 * entry_atr
            if hold_days >= 10 or cur_low < stop_price:
                exit_price = min(cur_close, stop_price) if cur_low < stop_price else cur_close
                r_multiple = (exit_price - entry_price) / (2 * entry_atr)
                trades.append(_make_trade("M6_weekly_mom", df, entry_idx, i,
                                          entry_price, exit_price, r_multiple, 1.0))
                in_pos = False
    return trades


def _make_trade(name, df, entry_idx, exit_idx, entry_p, exit_p, r, weight):
    return {
        "strategy": name,
        "entry_date": df.index[entry_idx],
        "exit_date": df.index[exit_idx],
        "entry_price": entry_p,
        "exit_price": exit_p,
        "r_multiple": r,
        "outcome": "WIN" if r > 0 else "LOSS",
        "hold_days": exit_idx - entry_idx,
        "weight": weight,
    }


STRATEGIES = [
    ("M1_vol_scaled_12mo", m1_vol_scaled_12mo),
    ("M2_mom_6mo",         m2_mom_6mo),
    ("M3_mom_3mo",         m3_mom_3mo),
    ("M4_ker",             m4_ker),
    ("M5_adx_dmi",         m5_adx_dmi),
    ("M6_weekly_mom",      m6_weekly_mom),
]


# ═══════════════════════════════════════════════════════════════════════
# STATS + HYGIENE
# ═══════════════════════════════════════════════════════════════════════

def analyze(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0, "w": 0, "l": 0, "wr": 0.0, "r": 0.0, "avg_r": 0.0}
    n = len(trades)
    w = sum(1 for t in trades if t["outcome"] == "WIN")
    l = n - w
    r = sum(t["r_multiple"] for t in trades)
    return {"n": n, "w": w, "l": l, "wr": 100 * w / n, "r": r, "avg_r": r / n}


# ═══════════════════════════════════════════════════════════════════════
# RUN
# ═══════════════════════════════════════════════════════════════════════

def main() -> None:
    all_rows: list[dict] = []
    ticker_years: dict[str, float] = {}
    ticker_bars: dict[str, int] = {}

    for ticker in TICKERS:
        df = load_ticker(ticker)
        years = (df.index[-1] - df.index[0]).days / 365.25
        ticker_years[ticker] = years
        ticker_bars[ticker] = len(df)

        for name, fn in STRATEGIES:
            trades = fn(df)
            stats = analyze(trades)
            if stats["n"] == 0:
                # Still record — but hygiene needs n>0. Skip haircut with sentinels.
                all_rows.append({
                    "ticker": ticker, "strategy": name, "years": years,
                    "n": 0, "wr": 0.0, "raw_r": 0.0, "avg_r": 0.0,
                    "r_low": 0.0, "r_high": 0.0, "kelly": 0.0,
                    "cagr_low": 0.0, "cagr_high": 0.0,
                })
                continue

            hc = compute_haircut(
                raw_r=stats["r"], n_trades=stats["n"], wr_pct=stats["wr"],
                avg_rr=abs(stats["avg_r"]) if stats["avg_r"] != 0 else 1.0,
                declared_sizing_pct=5.0,
                in_sample_derived=False,  # published rules, not fit here
                execution_scenario="robinhood",
                years=years,
            )
            all_rows.append({
                "ticker": ticker, "strategy": name, "years": years,
                "n": stats["n"], "wr": stats["wr"], "raw_r": stats["r"], "avg_r": stats["avg_r"],
                "r_low": hc.realistic_r_low, "r_high": hc.realistic_r_high,
                "kelly": hc.kelly_safe_sizing_pct,
                "cagr_low": hc.realistic_annual_cagr_low * 100,
                "cagr_high": hc.realistic_annual_cagr_high * 100,
            })

    # Rank by post-hygiene R_high
    ranked = sorted(all_rows, key=lambda x: -x["r_high"])
    winners = [r for r in ranked if r["r_high"] > 0 and r["cagr_high"] > 5.0]

    # Print top of console for sanity
    print(f"Ran {len(all_rows)} combos ({len(TICKERS)} tickers × {len(STRATEGIES)} strategies)")
    print(f"Winners (R_high>0 AND CAGR@Kelly-safe>5%): {len(winners)}")
    print("\nTop 10 by post-hygiene R_high:")
    print(f"{'Rank':>4} {'Ticker':<8} {'Strategy':<20} {'N':>4} {'WR%':>6} {'RawR':>7} {'R_low':>7} {'R_high':>7} {'CAGR_h%':>8}")
    for i, r in enumerate(ranked[:10], 1):
        print(f"{i:>4} {r['ticker']:<8} {r['strategy']:<20} {r['n']:>4} {r['wr']:>5.1f}% "
              f"{r['raw_r']:>+6.1f}R {r['r_low']:>+6.1f}R {r['r_high']:>+6.1f}R {r['cagr_high']:>+7.2f}%")

    # Write vault note
    _write_vault_note(ranked, winners, ticker_years, ticker_bars)
    print(f"\nWrote vault note: {VAULT_OUT}")


def _write_vault_note(ranked, winners, ticker_years, ticker_bars):
    lines: list[str] = []
    lines.append("# Momentum Multi-Ticker Bake-off (Agent 2)")
    lines.append("")
    lines.append(f"**Run date:** 2026-09-03")
    lines.append(f"**Script:** `scripts/backtest/agent2_momentum_multi.py`")
    lines.append(f"**Tickers:** {len(TICKERS)}  ·  **Strategies:** {len(STRATEGIES)}  ·  **Combos:** {len(ranked)}")
    lines.append("")
    lines.append("## Question")
    lines.append("")
    lines.append("Does any momentum/trend-following strategy have real edge (post-hygiene) "
                 "across the 20-ticker universe, and where does the edge concentrate?")
    lines.append("")
    lines.append("## Method")
    lines.append("")
    lines.append("- Six published momentum strategies (M1–M6), long-only, daily bars.")
    lines.append("- `in_sample_derived=False` in `compute_haircut` — rules are from academic/practitioner "
                 "literature (Barroso-Santa-Clara, Kaufman, Wilder DMI/ADX), NOT fit to this data.")
    lines.append("- Hygiene: McLean-Pontiff (0.30–0.40) × Robinhood exec drag (0.06R/trade) × options gap (0.65–0.75).")
    lines.append("  Note: options gap does not really apply to underlying-only equity strats — it's a conservative floor.")
    lines.append("- Kelly-safe sizing: quarter-Kelly capped at 1.5% (research/35).")
    lines.append("")
    lines.append("### Strategies")
    lines.append("")
    lines.append("| ID | Rule |")
    lines.append("|----|------|")
    lines.append("| M1 | Vol-scaled 12-1mo momentum + 200SMA (Barroso-Santa-Clara 2015). Weight = 15%/realized_vol, clamped [0.3, 2.0]. Exit: momentum flip or 5%-below-200SMA. |")
    lines.append("| M2 | 6mo momentum (skip last 2wk) + 100SMA filter. Same exit as M1. |")
    lines.append("| M3 | 3mo momentum (skip last week) + 50SMA filter. Same exit as M1. |")
    lines.append("| M4 | Kaufman Efficiency Ratio > 0.3 AND 20d high breakout. Exit: KER < 0.15 or 2-ATR stop. |")
    lines.append("| M5 | ADX(14) > 25 + DMI+ crosses DMI- → long. Exit: DMI- crosses DMI+. |")
    lines.append("| M6 | 5-day return > 2% → enter next bar. Exit: 10-day timeout or 2-ATR stop. |")
    lines.append("")

    # Winner verdict
    lines.append("## Verdict")
    lines.append("")
    if not winners:
        lines.append("**NO WINNERS.** No (strategy × ticker) combo cleared post-hygiene R_high > 0 AND "
                     "CAGR at Kelly-safe sizing > 5%. Long-only momentum on individual names does not survive "
                     "the standard haircut on this 6-year sample.")
    else:
        lines.append(f"**{len(winners)} winners** cleared post-hygiene R_high > 0 AND CAGR at Kelly-safe > 5%.")
        top3 = winners[:3]
        lines.append("")
        lines.append("**Top 3 (post-hygiene R_high):**")
        for i, w in enumerate(top3, 1):
            lines.append(f"{i}. **{w['ticker']} × {w['strategy']}** — "
                         f"raw {w['raw_r']:+.1f}R over {w['n']} trades ({w['wr']:.0f}% WR), "
                         f"post-hygiene {w['r_low']:+.1f}R to {w['r_high']:+.1f}R, "
                         f"CAGR @{w['kelly']:.2f}%: {w['cagr_low']:+.2f}% to {w['cagr_high']:+.2f}%.")
    lines.append("")

    # Top 10 by hygiene R_high
    lines.append("## Top 10 by post-hygiene R_high")
    lines.append("")
    lines.append("| Rank | Ticker | Strategy | N | WR% | Raw R | R_low | R_high | Kelly% | CAGR low–high |")
    lines.append("|-----:|:-------|:---------|--:|----:|------:|------:|-------:|-------:|--------------:|")
    for i, r in enumerate(ranked[:10], 1):
        lines.append(f"| {i} | {r['ticker']} | {r['strategy']} | {r['n']} | {r['wr']:.1f} | "
                     f"{r['raw_r']:+.2f} | {r['r_low']:+.2f} | {r['r_high']:+.2f} | "
                     f"{r['kelly']:.2f} | {r['cagr_low']:+.2f}% – {r['cagr_high']:+.2f}% |")
    lines.append("")

    # Bottom 10 (worst raw R) for context
    worst = sorted(ranked, key=lambda x: x["raw_r"])[:10]
    lines.append("## Bottom 10 by raw R (worst combos, for context)")
    lines.append("")
    lines.append("| Rank | Ticker | Strategy | N | WR% | Raw R | R_high |")
    lines.append("|-----:|:-------|:---------|--:|----:|------:|-------:|")
    for i, r in enumerate(worst, 1):
        lines.append(f"| {i} | {r['ticker']} | {r['strategy']} | {r['n']} | {r['wr']:.1f} | "
                     f"{r['raw_r']:+.2f} | {r['r_high']:+.2f} |")
    lines.append("")

    # Per-strategy summary
    lines.append("## Per-strategy aggregate")
    lines.append("")
    lines.append("| Strategy | Combos | Total N | Total raw R | Avg raw R | # positive raw | # winners (post-hygiene) |")
    lines.append("|:---------|-------:|--------:|------------:|----------:|---------------:|-------------------------:|")
    for name, _ in STRATEGIES:
        rows = [r for r in ranked if r["strategy"] == name]
        total_n = sum(r["n"] for r in rows)
        total_r = sum(r["raw_r"] for r in rows)
        avg_r = total_r / len(rows) if rows else 0.0
        n_pos = sum(1 for r in rows if r["raw_r"] > 0)
        n_win = sum(1 for r in rows if r["r_high"] > 0 and r["cagr_high"] > 5.0)
        lines.append(f"| {name} | {len(rows)} | {total_n} | {total_r:+.1f} | {avg_r:+.2f} | {n_pos} | {n_win} |")
    lines.append("")

    # Per-ticker summary
    lines.append("## Per-ticker aggregate")
    lines.append("")
    lines.append("| Ticker | Years | Total raw R (all 6 strats) | Best strat | Best strat raw R | # winners |")
    lines.append("|:-------|------:|---------------------------:|:-----------|-----------------:|----------:|")
    for ticker in TICKERS:
        rows = [r for r in ranked if r["ticker"] == ticker]
        total_r = sum(r["raw_r"] for r in rows)
        best = max(rows, key=lambda x: x["raw_r"]) if rows else None
        n_win = sum(1 for r in rows if r["r_high"] > 0 and r["cagr_high"] > 5.0)
        yrs = ticker_years.get(ticker, 0.0)
        if best:
            lines.append(f"| {ticker} | {yrs:.1f} | {total_r:+.1f} | {best['strategy']} | {best['raw_r']:+.2f} | {n_win} |")
        else:
            lines.append(f"| {ticker} | {yrs:.1f} | — | — | — | 0 |")
    lines.append("")

    # Full table (all 120)
    lines.append("## Full table — all combos")
    lines.append("")
    lines.append("| Ticker | Strategy | Years | N | WR% | Raw R | Avg R | R_low | R_high | Kelly% | CAGR_low% | CAGR_high% |")
    lines.append("|:-------|:---------|------:|--:|----:|------:|------:|------:|-------:|-------:|----------:|-----------:|")
    # Ordered by ticker, then strategy for readability
    for ticker in TICKERS:
        for name, _ in STRATEGIES:
            r = next((x for x in ranked if x["ticker"] == ticker and x["strategy"] == name), None)
            if not r:
                continue
            lines.append(f"| {r['ticker']} | {r['strategy']} | {r['years']:.1f} | {r['n']} | {r['wr']:.1f} | "
                         f"{r['raw_r']:+.2f} | {r['avg_r']:+.3f} | {r['r_low']:+.2f} | {r['r_high']:+.2f} | "
                         f"{r['kelly']:.2f} | {r['cagr_low']:+.2f} | {r['cagr_high']:+.2f} |")
    lines.append("")

    # Interpretation guardrails
    lines.append("## Caveats")
    lines.append("")
    lines.append("- Sample: 6 years (max, 2020-07 → 2026-08). Not survivorship-corrected but universe is a "
                 "fixed watchlist, not a screened basket — mild selection bias is present (all names Brock "
                 "is already familiar with, most large-cap growth or index).")
    lines.append("- Hygiene includes an options-gap multiplier (0.70) which is CONSERVATIVE for underlying-only "
                 "strats. Real live expectation is closer to the mid-to-upper end of the R_low–R_high range.")
    lines.append("- R math uses 2-ATR reference stop, but strategies don't actually stop at 2 ATR — the R "
                 "multiple is a normalisation, not a live-loss cap. Kelly sizing assumes the R distribution "
                 "translates cleanly; deep-drawdown paths in tail-heavy names (SMCI, GME, MSTR) will breach.")
    lines.append("- No overlay / portfolio-level backtest. Kelly-safe sizing is single-position; running "
                 "5-10 of these simultaneously requires vol-scaling at the portfolio layer.")
    lines.append("- `M1_vol_scaled_12mo` already appears in `strategy_bakeoff.py`; this note ports it to "
                 "the multi-ticker set as a stress test — a strategy that only worked on TSLA would be "
                 "an in-sample tell.")
    lines.append("")
    lines.append("## Next actions (if winners exist)")
    lines.append("")
    lines.append("1. Cross-check top 3 combos against `research/17-next-level-alpha-playbook.md` "
                 "(is Barroso-Santa-Clara vol-scaling doing the work, or is one ticker's regime doing it?).")
    lines.append("2. Split each top-3 combo train/test at 2024-01-01 — if edge concentrates in one half, kill.")
    lines.append("3. Simulate portfolio of top 5 uncorrelated combos at Kelly-safe sizing — compare vs SPY buy-and-hold.")
    lines.append("")

    VAULT_OUT.parent.mkdir(parents=True, exist_ok=True)
    VAULT_OUT.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
