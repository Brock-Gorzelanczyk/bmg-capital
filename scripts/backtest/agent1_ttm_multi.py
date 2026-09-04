"""agent1_ttm_multi.py — TTM Squeeze breakout across 20 tickers × 3 variants.

Purpose: was the +19.4R TSLA result TSLA-specific overfitting, or does TTM Squeeze
have real edge across a basket? Run 60 (ticker × variant) combos, rank by
post-hygiene R_high, apply Kelly-safe CAGR gate.

Variants:
  A — BB(20, 2.0) / KC(20, 1.5), 2-ATR profit / 1-ATR stop / 20-bar max (baseline)
  B — BB(20, 2.0) / KC(20, 2.0), 3-ATR profit / 1.5-ATR stop / 30-bar max (looser)
  C — BB(20, 2.0) / KC(20, 1.0), 2-ATR profit / 1-ATR stop / 15-bar max (tighter)

Parameters come from Carter's book (research/34), NOT fit to this data →
`in_sample_derived=False` in the haircut.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from backtest_hygiene import compute_haircut


TICKERS = [
    "TSLA", "NVDA", "MSTR", "COIN", "SMCI", "PLTR", "AMD", "META", "GOOG", "AAPL",
    "MSFT", "QQQ", "SPY", "IWM", "XLE", "ARKK", "SOFI", "HOOD", "GME", "AVGO",
]

DATA_DIR = Path(__file__).parent / "data" / "multi"


# ═══════════════════════════════════════════════════════════════════════
# Indicators (verbatim from strategy_bakeoff.py)
# ═══════════════════════════════════════════════════════════════════════

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
# Parameterized TTM Squeeze
# ═══════════════════════════════════════════════════════════════════════

def strategy_ttm_squeeze_param(
    df: pd.DataFrame,
    *,
    bb_n: int = 20,
    bb_k: float = 2.0,
    kc_n: int = 20,
    kc_k: float = 1.5,
    profit_atr: float = 2.0,
    stop_atr: float = 1.0,
    max_bars: int = 20,
) -> list[dict]:
    close = df["close"]
    high = df["high"]
    low = df["low"]
    _, bb_up, bb_dn = bollinger(close, bb_n, bb_k)
    _, kc_up, kc_dn = keltner(high, low, close, kc_n, kc_k)
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
            profit_target = entry_price + profit_atr * entry_atr
            stop_price = entry_price - stop_atr * entry_atr
            if cur_close >= profit_target or cur_close <= stop_price or hold_days >= max_bars:
                exit_price = cur_close
                # R = P&L / (initial risk per share). Initial risk = stop_atr * entry_atr.
                r_multiple = (exit_price - entry_price) / (stop_atr * entry_atr)
                trades.append({
                    "entry_date": df.index[entry_idx],
                    "exit_date": df.index[i],
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "r_multiple": r_multiple,
                    "hold_days": hold_days,
                    "outcome": "WIN" if r_multiple > 0 else "LOSS",
                })
                in_pos = False
    return trades


# ═══════════════════════════════════════════════════════════════════════
# Variants
# ═══════════════════════════════════════════════════════════════════════

VARIANTS = {
    "A": dict(bb_n=20, bb_k=2.0, kc_n=20, kc_k=1.5, profit_atr=2.0, stop_atr=1.0, max_bars=20),
    "B": dict(bb_n=20, bb_k=2.0, kc_n=20, kc_k=2.0, profit_atr=3.0, stop_atr=1.5, max_bars=30),
    "C": dict(bb_n=20, bb_k=2.0, kc_n=20, kc_k=1.0, profit_atr=2.0, stop_atr=1.0, max_bars=15),
}


# ═══════════════════════════════════════════════════════════════════════
# Load + run
# ═══════════════════════════════════════════════════════════════════════

def load_ticker(sym: str) -> pd.DataFrame:
    path = DATA_DIR / f"{sym}_daily.csv"
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    return df


def years_from_df(df: pd.DataFrame) -> float:
    return (df.index[-1] - df.index[0]).days / 365.25


def run_all() -> pd.DataFrame:
    rows = []
    for sym in TICKERS:
        try:
            df = load_ticker(sym)
        except FileNotFoundError:
            print(f"[skip] {sym}: no data file")
            continue
        yrs = years_from_df(df)

        for vkey, params in VARIANTS.items():
            trades = strategy_ttm_squeeze_param(df, **params)
            n = len(trades)
            if n == 0:
                rows.append(dict(
                    ticker=sym, variant=vkey, n_trades=0, raw_r=0.0, wr_pct=0.0,
                    years=yrs, hc_r_low=0.0, hc_r_high=0.0,
                    kelly_safe_pct=0.5, cagr_low_pct=0.0, cagr_high_pct=0.0,
                ))
                continue
            r_series = pd.Series([t["r_multiple"] for t in trades])
            raw_r = float(r_series.sum())
            wr_pct = float((r_series > 0).mean() * 100.0)
            # avg_rr per variant = profit_atr / stop_atr
            avg_rr = params["profit_atr"] / params["stop_atr"]

            hc = compute_haircut(
                raw_r=raw_r,
                n_trades=n,
                wr_pct=wr_pct,
                avg_rr=avg_rr,
                declared_sizing_pct=5.0,
                in_sample_derived=False,   # Carter's book params, not fit to this data
                execution_scenario="robinhood",
                years=yrs,
            )
            rows.append(dict(
                ticker=sym, variant=vkey, n_trades=n, raw_r=raw_r, wr_pct=wr_pct,
                years=yrs,
                hc_r_low=hc.realistic_r_low,
                hc_r_high=hc.realistic_r_high,
                kelly_safe_pct=hc.kelly_safe_sizing_pct,
                cagr_low_pct=hc.realistic_annual_cagr_low * 100.0,
                cagr_high_pct=hc.realistic_annual_cagr_high * 100.0,
            ))
    return pd.DataFrame(rows)


def make_report(res: pd.DataFrame) -> str:
    res = res.copy()
    res["winner"] = (res["hc_r_high"] > 0) & (res["cagr_high_pct"] > 5.0)
    ranked = res.sort_values("hc_r_high", ascending=False).reset_index(drop=True)

    lines: list[str] = []
    lines.append("# 49 — TTM Squeeze Multi-Ticker Discovery (agent1)")
    lines.append("")
    lines.append("**Question:** was TSLA's +19.4R TTM Squeeze result a real edge, or TSLA-specific overfit?")
    lines.append("")
    lines.append(f"**Universe:** {res['ticker'].nunique()} tickers × 3 variants = {len(res)} combos.")
    lines.append("**Parameters:** from Carter's *Mastering the Trade* (research/34) — NOT fit to this data.")
    lines.append("**Hygiene:** `compute_haircut(in_sample_derived=False)` → light 0.40× / heavy 0.30× overfit haircut, execution drag, options 65–75% gap.")
    lines.append("**Winner def:** post-hygiene R_high > 0 AND Kelly-safe CAGR_high > 5%.")
    lines.append("")
    n_winners = int(res["winner"].sum())
    lines.append(f"## Verdict: **{n_winners}/{len(res)} combos win**.")
    lines.append("")

    # Per-variant summary
    lines.append("## Per-variant summary")
    lines.append("")
    lines.append("| Variant | Combos | Winners | Median raw R | Median post-hyg R_high | Median WR% |")
    lines.append("|---|---|---|---|---|---|")
    for v in ("A", "B", "C"):
        sub = res[res["variant"] == v]
        lines.append(
            f"| {v} | {len(sub)} | {int(sub['winner'].sum())} | "
            f"{sub['raw_r'].median():+.2f} | {sub['hc_r_high'].median():+.2f} | "
            f"{sub['wr_pct'].median():.1f}% |"
        )
    lines.append("")

    # Full ranked table
    lines.append("## Full ranked results (by post-hygiene R_high, descending)")
    lines.append("")
    lines.append("| Rank | Ticker | Variant | Trades | WR% | Raw R | Post-hyg R_low | Post-hyg R_high | Kelly-safe % | CAGR_low % | CAGR_high % | Winner? |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for i, row in ranked.iterrows():
        lines.append(
            f"| {i+1} | {row['ticker']} | {row['variant']} | {int(row['n_trades'])} | "
            f"{row['wr_pct']:.1f}% | {row['raw_r']:+.2f} | "
            f"{row['hc_r_low']:+.2f} | {row['hc_r_high']:+.2f} | "
            f"{row['kelly_safe_pct']:.2f}% | {row['cagr_low_pct']:+.2f}% | "
            f"{row['cagr_high_pct']:+.2f}% | {'YES' if row['winner'] else '-'} |"
        )
    lines.append("")

    winners = ranked[ranked["winner"]]
    if not winners.empty:
        lines.append("## Winners only")
        lines.append("")
        lines.append("| Ticker | Variant | Trades | WR% | Raw R | R_high | CAGR_high |")
        lines.append("|---|---|---|---|---|---|---|")
        for _, row in winners.iterrows():
            lines.append(
                f"| {row['ticker']} | {row['variant']} | {int(row['n_trades'])} | "
                f"{row['wr_pct']:.1f}% | {row['raw_r']:+.2f} | {row['hc_r_high']:+.2f} | "
                f"{row['cagr_high_pct']:+.2f}% |"
            )
        lines.append("")
    else:
        lines.append("## Winners only")
        lines.append("")
        lines.append("**None.** No (ticker, variant) pair cleared both gates.")
        lines.append("")

    # TSLA-specific check
    tsla = ranked[ranked["ticker"] == "TSLA"]
    lines.append("## TSLA sanity check (was +19.4R real or lucky?)")
    lines.append("")
    if not tsla.empty:
        lines.append("| Variant | Trades | WR% | Raw R | Post-hyg R_high | CAGR_high |")
        lines.append("|---|---|---|---|---|---|")
        for _, row in tsla.iterrows():
            lines.append(
                f"| {row['variant']} | {int(row['n_trades'])} | {row['wr_pct']:.1f}% | "
                f"{row['raw_r']:+.2f} | {row['hc_r_high']:+.2f} | "
                f"{row['cagr_high_pct']:+.2f}% |"
            )
        lines.append("")

    # Aggregate stats
    lines.append("## Aggregate stats (across ALL 60 combos)")
    lines.append("")
    lines.append(f"- Median raw R: **{res['raw_r'].median():+.2f}**")
    lines.append(f"- Mean raw R: **{res['raw_r'].mean():+.2f}**")
    lines.append(f"- % combos with raw R > 0: **{(res['raw_r'] > 0).mean() * 100:.1f}%**")
    lines.append(f"- % combos with post-hyg R_high > 0: **{(res['hc_r_high'] > 0).mean() * 100:.1f}%**")
    lines.append(f"- % combos with CAGR_high > 5%: **{(res['cagr_high_pct'] > 5.0).mean() * 100:.1f}%**")
    lines.append(f"- Median trades per combo: **{res['n_trades'].median():.0f}** over ~{res['years'].median():.1f} years")
    lines.append("")

    lines.append("## Notes")
    lines.append("")
    lines.append("- R multiple defined as `(exit − entry) / (stop_atr × entry_atr)` so a variant with wider stop dampens R proportionally — this is intentional; it lets R compare across variants on the same risk-unit basis.")
    lines.append("- CAGR estimate is `R_per_year × Kelly-safe sizing`, which is a rough linear approximation, not a compounded return. Use as a coarse gate, not a headline.")
    lines.append("- Execution drag applied at **Robinhood** cost (0.06 R/trade). IBKR would give a modestly better number.")
    lines.append("- `in_sample_derived=False` because parameters come from Carter's book — the hygiene module still applies the 0.30–0.40× multiplier as a conservative anchor (McLean-Pontiff out-of-sample decay is real even for published rules).")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    res = run_all()
    print("\n=== RAW RESULTS ===")
    print(res.to_string(index=False))

    out_path = Path("/Users/brockgorzelanczyk/Documents/BMG-Capital-Vault/research/49-ttm-squeeze-multi-ticker-agent.md")
    md = make_report(res)
    out_path.write_text(md)
    print(f"\nWrote report → {out_path}")
    # also stash the numeric CSV alongside for reproducibility
    csv_path = Path(__file__).parent / "agent1_ttm_multi_results.csv"
    res.to_csv(csv_path, index=False)
    print(f"Wrote CSV    → {csv_path}")
