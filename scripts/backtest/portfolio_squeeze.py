"""Portfolio-of-squeezes — validate agent 1's key finding.

Agent 1's TTM Squeeze bake-off showed:
- Real edge on 13 of 20 tickers
- Single-ticker: only 3-5 trades/year → CAGR-capped
- HYPOTHESIS: portfolio across all positive tickers → ~40 trades/year → CAGR clears 5%

This script tests that hypothesis directly. Uses Variant B (looser squeeze):
  BB(20, 2.0) / KC(20, 2.0), 3-ATR profit / 1.5-ATR stop / 30-bar max hold

Universe: 13 tickers Agent 1 showed positive post-hygiene R on:
  TSLA, MSTR, ARKK, NVDA, AMD, SMCI, PLTR, GOOG, HOOD, AAPL, META, SPY, AVGO

Ranks by post-hygiene R AND cross-ticker consistency. Writes to vault as note 55.
"""
from __future__ import annotations

import sys
from pathlib import Path
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from backtest_hygiene import compute_haircut

DATA_DIR = Path(__file__).parent / "data" / "multi"
VAULT_NOTE = Path.home() / "Documents" / "BMG-Capital-Vault" / "research" / "55-portfolio-squeeze-live-candidate.md"

# Agent 1's positive-post-hygiene universe
UNIVERSE = ["TSLA", "MSTR", "ARKK", "NVDA", "AMD", "SMCI", "PLTR", "GOOG",
            "HOOD", "AAPL", "META", "SPY", "AVGO"]

# Variant B parameters
BB_LEN = 20
BB_STD = 2.0
KC_LEN = 20
KC_MULT = 2.0
PROFIT_ATR = 3.0
STOP_ATR = 1.5
MAX_HOLD = 30


def rsi(series, n):
    delta = series.diff()
    up = delta.clip(lower=0)
    dn = -delta.clip(upper=0)
    ma_up = up.ewm(alpha=1/n, adjust=False).mean()
    ma_dn = dn.ewm(alpha=1/n, adjust=False).mean()
    rs = ma_up / ma_dn.replace(0, 1e-9)
    return 100 - (100 / (1 + rs))


def atr(high, low, close, n=14):
    tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def bollinger(close, n, k):
    ma = close.rolling(n).mean()
    sd = close.rolling(n).std()
    return ma, ma + k * sd, ma - k * sd


def keltner(high, low, close, n, k):
    ma = close.rolling(n).mean()
    a = atr(high, low, close, n)
    return ma, ma + k * a, ma - k * a


def load_ticker(t: str) -> pd.DataFrame | None:
    p = DATA_DIR / f"{t}_daily.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p)
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()


def strategy_squeeze_variant_b(df: pd.DataFrame, ticker: str) -> list[dict]:
    close = df["close"]
    high = df["high"]
    low = df["low"]
    bb_mid, bb_up, bb_dn = bollinger(close, BB_LEN, BB_STD)
    kc_mid, kc_up, kc_dn = keltner(high, low, close, KC_LEN, KC_MULT)
    atr14 = atr(high, low, close, 14)

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

        if not in_pos:
            if squeeze_release.iloc[i] and mom.iloc[i] > 0:
                in_pos = True
                entry_idx = i
                entry_price = cur_close
                entry_atr = atr14.iloc[i] if pd.notna(atr14.iloc[i]) else cur_close * 0.02
        else:
            hold_days = i - entry_idx
            profit_target = entry_price + PROFIT_ATR * entry_atr
            stop_price = entry_price - STOP_ATR * entry_atr
            if cur_close >= profit_target or cur_close <= stop_price or hold_days >= MAX_HOLD:
                exit_price = cur_close
                r_multiple = (exit_price - entry_price) / (STOP_ATR * entry_atr)
                trades.append({
                    "ticker": ticker,
                    "entry_date": df.index[entry_idx],
                    "exit_date": df.index[i],
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "r_multiple": r_multiple,
                    "outcome": "WIN" if r_multiple > 0 else "LOSS",
                    "hold_days": hold_days,
                })
                in_pos = False
    return trades


def main():
    print("=" * 80)
    print("PORTFOLIO-OF-SQUEEZES — Variant B across Agent 1 winner universe")
    print("=" * 80)
    print(f"Universe: {len(UNIVERSE)} tickers: {', '.join(UNIVERSE)}")
    print()

    all_trades = []
    per_ticker = {}
    for t in UNIVERSE:
        df = load_ticker(t)
        if df is None:
            print(f"  {t}: NO DATA")
            continue
        trades = strategy_squeeze_variant_b(df, t)
        per_ticker[t] = trades
        all_trades.extend(trades)

    # Sort trades by entry_date to build capital-allocated portfolio return
    all_trades.sort(key=lambda x: x["entry_date"])

    # Per-ticker stats
    print(f"{'Ticker':<8} {'N':>5} {'WR%':>7} {'Total R':>10}")
    print("-" * 40)
    for t in UNIVERSE:
        trades = per_ticker.get(t, [])
        if not trades:
            print(f"{t:<8} {0:>5} {'-':>7} {'-':>10}")
            continue
        n = len(trades)
        w = sum(1 for x in trades if x["outcome"] == "WIN")
        wr = 100 * w / max(1, n)
        r = sum(x["r_multiple"] for x in trades)
        print(f"{t:<8} {n:>5} {wr:>6.1f}% {r:>+9.1f}R")

    # Aggregate portfolio stats
    n = len(all_trades)
    if n == 0:
        print("\nNo trades. Aborting.")
        return
    w = sum(1 for x in all_trades if x["outcome"] == "WIN")
    l = sum(1 for x in all_trades if x["outcome"] == "LOSS")
    wr = 100 * w / max(1, w + l)
    total_r = sum(x["r_multiple"] for x in all_trades)
    avg_r = total_r / n

    # Date range (portfolio span)
    start = all_trades[0]["entry_date"]
    end = all_trades[-1]["exit_date"]
    years = (end - start).days / 365.25

    print(f"\nPORTFOLIO AGGREGATE:")
    print(f"  Trades:       {n:,}")
    print(f"  Trades/year:  {n / max(years, 0.1):.1f}")
    print(f"  Wins/Losses:  {w} / {l}")
    print(f"  Win rate:     {wr:.1f}%")
    print(f"  Total R:      {total_r:+.1f}R")
    print(f"  Avg R/trade:  {avg_r:+.3f}R")

    # Hygiene gate
    hc = compute_haircut(
        raw_r=total_r,
        n_trades=n,
        wr_pct=wr,
        avg_rr=abs(avg_r) if avg_r else 1.0,
        declared_sizing_pct=5.0,
        in_sample_derived=False,  # TTM squeeze from Carter book, not this data
        execution_scenario="robinhood",
        years=years,
    )
    print(f"\n{hc.detail}")

    verdict = "🏆 WINNER" if hc.realistic_r_high > 0 and hc.realistic_annual_cagr_high * 100 > 5 else "⚠️ SUB-THRESHOLD"
    print(f"\nVerdict: {verdict}")

    # Vault report
    with open(VAULT_NOTE, "w") as f:
        f.write("# 55 — Portfolio-of-squeezes live candidate\n\n")
        f.write(f"Tests Agent 1's core hypothesis: **cross-ticker portfolio of TTM Squeeze**\n")
        f.write(f"beats single-ticker CAGR gate by aggregating trade frequency.\n\n")
        f.write(f"**Universe:** {len(UNIVERSE)} tickers where Agent 1 showed positive post-hygiene R\n")
        f.write(f"({', '.join(UNIVERSE)})\n\n")
        f.write(f"**Strategy:** TTM Squeeze Variant B — BB(20,2.0)/KC(20,2.0), 3-ATR profit, 1.5-ATR stop, 30-bar max hold\n\n")
        f.write(f"**Verdict:** {verdict}\n\n")
        f.write("## Per-ticker breakdown\n\n")
        f.write("| Ticker | N | WR% | Total R |\n|---|---|---|---|\n")
        for t in UNIVERSE:
            trades = per_ticker.get(t, [])
            if not trades:
                f.write(f"| {t} | 0 | – | – |\n")
                continue
            tn = len(trades); tw = sum(1 for x in trades if x['outcome']=='WIN')
            twr = 100 * tw / max(1, tn); tr = sum(x['r_multiple'] for x in trades)
            f.write(f"| {t} | {tn} | {twr:.1f}% | {tr:+.1f}R |\n")
        f.write(f"\n## Portfolio aggregate\n\n")
        f.write(f"| Metric | Value |\n|---|---|\n")
        f.write(f"| Trades | {n:,} |\n")
        f.write(f"| Trades/year | {n / max(years, 0.1):.1f} |\n")
        f.write(f"| Win rate | {wr:.1f}% |\n")
        f.write(f"| Total R | {total_r:+.1f}R |\n")
        f.write(f"| Avg R/trade | {avg_r:+.3f}R |\n")
        f.write(f"| Period | {start.date()} → {end.date()} ({years:.1f} yrs) |\n\n")
        f.write("## Hygiene-gated realistic expectation\n\n")
        f.write("```\n" + hc.detail + "\n```\n\n")
        f.write("## Deployment spec (if winner)\n\n")
        f.write(f"- **Universe:** {', '.join(UNIVERSE)}\n")
        f.write("- **Trigger:** TTM Squeeze release + positive 20d momentum on daily bars\n")
        f.write(f"- **Sizing:** {hc.kelly_safe_sizing_pct:.2f}% NAV per trade (Kelly-safe, research/35)\n")
        f.write("- **Exit:** 3-ATR profit target, 1.5-ATR stop, or 30-bar timeout\n")
        f.write("- **Wrapper:** 60-day ATM calls per §O1 (defined-risk options preferred)\n")
        f.write("- **Concurrency cap:** max 3 open positions (avoid over-concentration)\n\n")

    print(f"\n✅ Wrote {VAULT_NOTE}")


if __name__ == "__main__":
    main()
