"""Agent 4 — Breakout / Volatility-Expansion Multi-Ticker Bakeoff.

Six breakout strategies × 20 tickers = 120 backtests.
All parameters come from published literature (turtle, VCP, NR7, Jegadeesh-Titman,
Bollinger consolidation) so `in_sample_derived=False` for the hygiene gate.

Winner definition: post-hygiene R_high > 0 AND CAGR at Kelly-safe sizing > 5%.

Strategies:
  B1  Donchian 20/10 (turtle, short)
  B2  Donchian 55/20 (turtle, long)
  B3  ATR expansion breakout with volume + ATR trail
  B4  52-week high breakout with volume, hold 60 bars
  B5  NR7 breakout, hold 3 bars
  B6  Bollinger consolidation breakout, exit at BB mid touch
"""
from __future__ import annotations

import sys
from pathlib import Path
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from backtest_hygiene import compute_haircut


DATA_DIR = Path(__file__).parent / "data" / "multi"
TICKERS = [
    "TSLA", "NVDA", "MSTR", "COIN", "SMCI", "PLTR", "AMD", "META", "GOOG",
    "AAPL", "MSFT", "QQQ", "SPY", "IWM", "XLE", "ARKK", "SOFI", "HOOD",
    "GME", "AVGO",
]


# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════

def load_ticker(ticker: str) -> pd.DataFrame:
    df = pd.read_csv(DATA_DIR / f"{ticker}_daily.csv")
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    return df


def true_range(high, low, close):
    return pd.concat([
        (high - low),
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)


def atr(high, low, close, n=14):
    return true_range(high, low, close).rolling(n).mean()


def bollinger(close, n=20, k=2.0):
    ma = close.rolling(n).mean()
    sd = close.rolling(n).std()
    return ma, ma + k * sd, ma - k * sd


# ═══════════════════════════════════════════════════════════════════════
# B1 — Donchian 20/10 (turtle, short) — port from bakeoff
# ═══════════════════════════════════════════════════════════════════════

def strategy_b1_donchian_20_10(df: pd.DataFrame, ticker: str) -> list[dict]:
    high, low, close = df["high"], df["low"], df["close"]
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
        cur_low = low.iloc[i]
        prior_dc_up = dc_up.iloc[i - 1]
        prior_dc_dn = dc_dn_exit.iloc[i - 1]

        if not in_pos:
            if pd.notna(prior_dc_up) and cur_close > prior_dc_up:
                in_pos = True
                entry_idx = i
                entry_price = cur_close
                entry_atr = atr14.iloc[i] if pd.notna(atr14.iloc[i]) else cur_close * 0.02
        else:
            stop_price = entry_price - 2 * entry_atr
            if (pd.notna(prior_dc_dn) and cur_close < prior_dc_dn) or cur_low < stop_price:
                exit_price = min(cur_close, stop_price) if cur_low < stop_price else cur_close
                r_multiple = (exit_price - entry_price) / (2 * entry_atr)
                trades.append(_trade("B1_donchian_20_10", ticker, df, entry_idx, i,
                                     entry_price, exit_price, r_multiple))
                in_pos = False
    return trades


# ═══════════════════════════════════════════════════════════════════════
# B2 — Donchian 55/20 (long-turtle, slower)
# ═══════════════════════════════════════════════════════════════════════

def strategy_b2_donchian_55_20(df: pd.DataFrame, ticker: str) -> list[dict]:
    high, low, close = df["high"], df["low"], df["close"]
    dc_up = high.rolling(55).max()
    dc_dn_exit = low.rolling(20).min()
    atr20 = atr(high, low, close, 20)

    trades = []
    in_pos = False
    entry_idx = None
    entry_price = None
    entry_atr = None

    for i in range(55, len(df)):
        cur_close = close.iloc[i]
        cur_low = low.iloc[i]
        prior_dc_up = dc_up.iloc[i - 1]
        prior_dc_dn = dc_dn_exit.iloc[i - 1]

        if not in_pos:
            if pd.notna(prior_dc_up) and cur_close > prior_dc_up:
                in_pos = True
                entry_idx = i
                entry_price = cur_close
                entry_atr = atr20.iloc[i] if pd.notna(atr20.iloc[i]) else cur_close * 0.02
        else:
            stop_price = entry_price - 2 * entry_atr
            if (pd.notna(prior_dc_dn) and cur_close < prior_dc_dn) or cur_low < stop_price:
                exit_price = min(cur_close, stop_price) if cur_low < stop_price else cur_close
                r_multiple = (exit_price - entry_price) / (2 * entry_atr)
                trades.append(_trade("B2_donchian_55_20", ticker, df, entry_idx, i,
                                     entry_price, exit_price, r_multiple))
                in_pos = False
    return trades


# ═══════════════════════════════════════════════════════════════════════
# B3 — ATR expansion breakout with volume + ATR trail stop
# ═══════════════════════════════════════════════════════════════════════

def strategy_b3_atr_expansion(df: pd.DataFrame, ticker: str) -> list[dict]:
    high, low, close, volume = df["high"], df["low"], df["close"], df["volume"]
    dc_up = high.rolling(20).max()
    atr20 = atr(high, low, close, 20)
    tr = true_range(high, low, close)
    tr_avg20 = tr.rolling(20).mean()
    vol_avg = volume.rolling(20).mean()

    trades = []
    in_pos = False
    entry_idx = None
    entry_price = None
    entry_atr = None
    trail_high = None  # highest high since entry for trailing stop

    for i in range(21, len(df)):
        cur_close = close.iloc[i]
        cur_high = high.iloc[i]
        cur_low = low.iloc[i]
        cur_tr = tr.iloc[i]
        cur_vol = volume.iloc[i]
        prior_dc_up = dc_up.iloc[i - 1]
        cur_tr_avg = tr_avg20.iloc[i - 1]
        cur_vol_avg = vol_avg.iloc[i - 1]

        if not in_pos:
            cond = (
                pd.notna(prior_dc_up)
                and pd.notna(cur_tr_avg)
                and pd.notna(cur_vol_avg)
                and cur_close > prior_dc_up
                and cur_tr > 2 * cur_tr_avg
                and cur_vol > 1.3 * cur_vol_avg
            )
            if cond:
                in_pos = True
                entry_idx = i
                entry_price = cur_close
                entry_atr = atr20.iloc[i] if pd.notna(atr20.iloc[i]) else cur_close * 0.02
                trail_high = cur_high
        else:
            trail_high = max(trail_high, cur_high)
            # 3-ATR trailing stop below rolling high
            trail_stop = trail_high - 3 * entry_atr
            if cur_low < trail_stop:
                exit_price = min(cur_close, trail_stop)
                r_multiple = (exit_price - entry_price) / (2 * entry_atr)
                trades.append(_trade("B3_atr_expansion", ticker, df, entry_idx, i,
                                     entry_price, exit_price, r_multiple))
                in_pos = False
    return trades


# ═══════════════════════════════════════════════════════════════════════
# B4 — 52-week high breakout with volume (Jegadeesh-Titman momentum)
# ═══════════════════════════════════════════════════════════════════════

def strategy_b4_52w_high(df: pd.DataFrame, ticker: str) -> list[dict]:
    high, low, close, volume = df["high"], df["low"], df["close"], df["volume"]
    # 252 trading days ≈ 52 weeks
    dc_52w = high.rolling(252).max()
    atr20 = atr(high, low, close, 20)
    vol_avg = volume.rolling(50).mean()

    trades = []
    in_pos = False
    entry_idx = None
    entry_price = None
    entry_atr = None
    hold_target = 60  # hold 60 bars

    for i in range(252, len(df)):
        cur_close = close.iloc[i]
        cur_vol = volume.iloc[i]
        prior_52w = dc_52w.iloc[i - 1]
        cur_vol_avg = vol_avg.iloc[i - 1]

        if not in_pos:
            cond = (
                pd.notna(prior_52w)
                and pd.notna(cur_vol_avg)
                and cur_close > prior_52w
                and cur_vol > 1.3 * cur_vol_avg
            )
            if cond:
                in_pos = True
                entry_idx = i
                entry_price = cur_close
                entry_atr = atr20.iloc[i] if pd.notna(atr20.iloc[i]) else cur_close * 0.02
        else:
            hold_days = i - entry_idx
            if hold_days >= hold_target or i == len(df) - 1:
                exit_price = cur_close
                r_multiple = (exit_price - entry_price) / (2 * entry_atr)
                trades.append(_trade("B4_52w_high_60bar", ticker, df, entry_idx, i,
                                     entry_price, exit_price, r_multiple))
                in_pos = False
    return trades


# ═══════════════════════════════════════════════════════════════════════
# B5 — NR7 breakout (narrow-range 7)
# ═══════════════════════════════════════════════════════════════════════

def strategy_b5_nr7(df: pd.DataFrame, ticker: str) -> list[dict]:
    high, low, close = df["high"], df["low"], df["close"]
    daily_range = high - low
    # NR7 = today's range is the min of last 7 (inclusive)
    is_nr7 = daily_range == daily_range.rolling(7).min()
    atr14 = atr(high, low, close, 14)

    trades = []
    in_pos = False
    entry_idx = None
    entry_price = None
    entry_atr = None
    signal_high = None  # NR7 bar's high for trigger
    days_since_signal = 0
    exit_bar_target = None

    for i in range(7, len(df)):
        cur_close = close.iloc[i]
        cur_high = high.iloc[i]

        if not in_pos:
            # Signal fired on prior day? Check today for breakout above prior's NR7 high.
            if signal_high is not None:
                days_since_signal += 1
                if cur_high > signal_high:
                    # Enter at breakout — approximate fill at prior NR7 high
                    in_pos = True
                    entry_idx = i
                    entry_price = signal_high
                    entry_atr = atr14.iloc[i] if pd.notna(atr14.iloc[i]) else cur_close * 0.02
                    exit_bar_target = i + 3  # exit at close 3 days later
                    signal_high = None
                elif days_since_signal >= 2:
                    signal_high = None  # signal expires
            # Set today's signal if NR7 fires
            if is_nr7.iloc[i] and signal_high is None:
                signal_high = cur_high
                days_since_signal = 0
        else:
            if i >= exit_bar_target or i == len(df) - 1:
                exit_price = cur_close
                r_multiple = (exit_price - entry_price) / (2 * entry_atr)
                trades.append(_trade("B5_nr7_3bar", ticker, df, entry_idx, i,
                                     entry_price, exit_price, r_multiple))
                in_pos = False
                signal_high = None
                exit_bar_target = None
    return trades


# ═══════════════════════════════════════════════════════════════════════
# B6 — Bollinger consolidation breakout
# ═══════════════════════════════════════════════════════════════════════

def strategy_b6_bb_consolidation(df: pd.DataFrame, ticker: str) -> list[dict]:
    high, low, close = df["high"], df["low"], df["close"]
    bb_mid, bb_up, bb_dn = bollinger(close, 20, 2.0)
    bb_width = (bb_up - bb_dn) / bb_mid.replace(0, np.nan)
    bb_width_min20 = bb_width.rolling(20).min()
    # Squeeze condition: BW < 20d min BW × 0.7 (i.e., recent BW is at least 30% tighter)
    # Note: min itself IS the min; so BW < min * 0.7 requires BW < 70% of past 20d minimum
    # This is the exact spec — treats "current 20d min * 0.7" as a very-tight threshold.
    squeeze = bb_width < bb_width_min20.shift(1) * 0.7
    # 3+ consecutive days
    squeeze_3d = squeeze & squeeze.shift(1) & squeeze.shift(2)
    atr14 = atr(high, low, close, 14)

    trades = []
    in_pos = False
    entry_idx = None
    entry_price = None
    entry_atr = None

    for i in range(30, len(df)):
        cur_close = close.iloc[i]
        cur_bb_up = bb_up.iloc[i]
        cur_bb_mid = bb_mid.iloc[i]

        if not in_pos:
            # Squeeze fired recently (within last 5 bars) AND close > BB_up today
            recent_squeeze = squeeze_3d.iloc[max(0, i - 5):i + 1].any()
            if recent_squeeze and pd.notna(cur_bb_up) and cur_close > cur_bb_up:
                in_pos = True
                entry_idx = i
                entry_price = cur_close
                entry_atr = atr14.iloc[i] if pd.notna(atr14.iloc[i]) else cur_close * 0.02
        else:
            # Exit on BB mid touch (close <= bb_mid) OR 2-ATR stop OR 30-bar timeout
            stop_price = entry_price - 2 * entry_atr
            hold_days = i - entry_idx
            hit_stop = df["low"].iloc[i] < stop_price
            mid_touch = pd.notna(cur_bb_mid) and cur_close <= cur_bb_mid
            if hit_stop or mid_touch or hold_days >= 30 or i == len(df) - 1:
                exit_price = min(cur_close, stop_price) if hit_stop else cur_close
                r_multiple = (exit_price - entry_price) / (2 * entry_atr)
                trades.append(_trade("B6_bb_consolidation", ticker, df, entry_idx, i,
                                     entry_price, exit_price, r_multiple))
                in_pos = False
    return trades


# ═══════════════════════════════════════════════════════════════════════
# TRADE RECORD HELPER
# ═══════════════════════════════════════════════════════════════════════

def _trade(strategy, ticker, df, entry_idx, exit_idx, entry_price, exit_price, r):
    return {
        "strategy": strategy,
        "ticker": ticker,
        "entry_date": df.index[entry_idx],
        "exit_date": df.index[exit_idx],
        "entry_price": float(entry_price),
        "exit_price": float(exit_price),
        "r_multiple": float(r),
        "outcome": "WIN" if r > 0 else "LOSS",
        "hold_days": exit_idx - entry_idx,
        "weight": 1.0,
    }


# ═══════════════════════════════════════════════════════════════════════
# ANALYSIS
# ═══════════════════════════════════════════════════════════════════════

def analyze(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0, "wr": 0.0, "r": 0.0, "avg_r": 0.0}
    n = len(trades)
    w = sum(1 for t in trades if t["outcome"] == "WIN")
    l = sum(1 for t in trades if t["outcome"] == "LOSS")
    r = sum(t["r_multiple"] for t in trades)
    wr = 100 * w / max(1, w + l)
    return {"n": n, "w": w, "l": l, "wr": wr, "r": r, "avg_r": r / n}


STRATEGIES = [
    ("B1_donchian_20_10",    strategy_b1_donchian_20_10),
    ("B2_donchian_55_20",    strategy_b2_donchian_55_20),
    ("B3_atr_expansion",     strategy_b3_atr_expansion),
    ("B4_52w_high_60bar",    strategy_b4_52w_high),
    ("B5_nr7_3bar",          strategy_b5_nr7),
    ("B6_bb_consolidation",  strategy_b6_bb_consolidation),
]


# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════

def run_all() -> tuple[list[dict], float]:
    """Run all 120 combos and return (rows, avg_years)."""
    rows = []
    years_seen = []
    for ticker in TICKERS:
        try:
            df = load_ticker(ticker)
        except FileNotFoundError:
            print(f"⚠️  {ticker}: data missing, skipping")
            continue
        years = (df.index[-1] - df.index[0]).days / 365.25
        years_seen.append(years)

        for strat_name, strat_fn in STRATEGIES:
            trades = strat_fn(df, ticker)
            stats = analyze(trades)
            if stats["n"] == 0:
                rows.append({
                    "ticker": ticker, "strategy": strat_name,
                    "n": 0, "wr": 0.0, "r": 0.0, "avg_r": 0.0,
                    "r_low": 0.0, "r_high": 0.0,
                    "kelly": 0.0, "cagr_low": 0.0, "cagr_high": 0.0,
                    "years": years, "winner": False,
                })
                continue

            hc = compute_haircut(
                raw_r=stats["r"],
                n_trades=stats["n"],
                wr_pct=stats["wr"],
                avg_rr=abs(stats["avg_r"]) if stats["avg_r"] != 0 else 1.0,
                declared_sizing_pct=5.0,
                in_sample_derived=False,  # published parameters
                execution_scenario="robinhood",
                years=years,
            )
            cagr_high_pct = hc.realistic_annual_cagr_high * 100
            cagr_low_pct = hc.realistic_annual_cagr_low * 100
            winner = (hc.realistic_r_high > 0) and (cagr_high_pct > 5.0)
            rows.append({
                "ticker": ticker,
                "strategy": strat_name,
                "n": stats["n"],
                "wr": stats["wr"],
                "r": stats["r"],
                "avg_r": stats["avg_r"],
                "r_low": hc.realistic_r_low,
                "r_high": hc.realistic_r_high,
                "kelly": hc.kelly_safe_sizing_pct,
                "cagr_low": cagr_low_pct,
                "cagr_high": cagr_high_pct,
                "years": years,
                "winner": winner,
            })
    avg_years = float(np.mean(years_seen)) if years_seen else 0.0
    return rows, avg_years


def write_vault_note(rows: list[dict], avg_years: float, out_path: Path) -> None:
    # Rank by post-hygiene R_high
    ranked = sorted(rows, key=lambda r: -r["r_high"])
    winners = [r for r in ranked if r["winner"]]

    lines = []
    lines.append("# 52 — Breakout / Volatility-Expansion Multi-Ticker Bakeoff")
    lines.append("")
    lines.append("**Agent 4 output.** 6 breakout strategies × 20 tickers = 120 backtests.")
    lines.append("")
    lines.append(f"- Data: `scripts/backtest/data/multi/{{TICKER}}_daily.csv` (20 tickers)")
    lines.append(f"- Average history per ticker: {avg_years:.1f} years")
    lines.append("- All strategies use published parameters → `in_sample_derived=False` for the hygiene gate")
    lines.append("- Execution scenario: `robinhood` (0.06R/trade drag)")
    lines.append("- Winner = post-hygiene R_high > 0 AND CAGR at Kelly-safe sizing > 5%")
    lines.append("")
    lines.append("## Strategies")
    lines.append("")
    lines.append("| ID | Name | Entry | Exit |")
    lines.append("|----|------|-------|------|")
    lines.append("| B1 | Donchian 20/10 (turtle short) | close > 20d high | close < 10d low OR 2-ATR stop |")
    lines.append("| B2 | Donchian 55/20 (turtle long)  | close > 55d high | close < 20d low OR 2-ATR stop |")
    lines.append("| B3 | ATR expansion + volume        | close > 20d high AND TR > 2×20d avg AND vol > 1.3× | 3-ATR trailing stop |")
    lines.append("| B4 | 52w high + volume             | close > 252d high AND vol > 1.3× | hold 60 bars |")
    lines.append("| B5 | NR7 breakout                  | prior day NR7, today high > prior high | exit at close +3 bars |")
    lines.append("| B6 | Bollinger consolidation       | BBW < 20d min BBW × 0.7 for 3+ days, then close > BB_up | BB mid touch OR 2-ATR stop OR 30 bars |")
    lines.append("")

    lines.append(f"## Winners ({len(winners)} / {len(rows)})")
    lines.append("")
    if winners:
        lines.append("| # | Strategy | Ticker | N | WR% | Raw R | R_low | R_high | Kelly% | CAGR low | CAGR high |")
        lines.append("|---|----------|--------|---|-----|-------|-------|--------|--------|----------|-----------|")
        for i, r in enumerate(sorted(winners, key=lambda r: -r["cagr_high"]), 1):
            lines.append(
                f"| {i} | {r['strategy']} | {r['ticker']} | {r['n']} | {r['wr']:.1f} | "
                f"{r['r']:+.1f} | {r['r_low']:+.1f} | {r['r_high']:+.1f} | "
                f"{r['kelly']:.2f} | {r['cagr_low']:+.1f}% | {r['cagr_high']:+.1f}% |"
            )
    else:
        lines.append("_No combos passed the winner gate (post-hygiene R_high > 0 AND CAGR_high > 5%)._")
    lines.append("")

    lines.append("## Top 20 by post-hygiene R_high")
    lines.append("")
    lines.append("| # | Strategy | Ticker | N | WR% | Raw R | R_low | R_high | Kelly% | CAGR low | CAGR high | Winner |")
    lines.append("|---|----------|--------|---|-----|-------|-------|--------|--------|----------|-----------|--------|")
    for i, r in enumerate(ranked[:20], 1):
        w_mark = "yes" if r["winner"] else ""
        lines.append(
            f"| {i} | {r['strategy']} | {r['ticker']} | {r['n']} | {r['wr']:.1f} | "
            f"{r['r']:+.1f} | {r['r_low']:+.1f} | {r['r_high']:+.1f} | "
            f"{r['kelly']:.2f} | {r['cagr_low']:+.1f}% | {r['cagr_high']:+.1f}% | {w_mark} |"
        )
    lines.append("")

    # Per-strategy summary
    lines.append("## Per-strategy summary (mean across tickers)")
    lines.append("")
    lines.append("| Strategy | mean N | mean WR% | sum R | mean R_high | winners |")
    lines.append("|----------|--------|----------|-------|-------------|---------|")
    for strat_name, _ in STRATEGIES:
        srows = [r for r in rows if r["strategy"] == strat_name]
        active = [r for r in srows if r["n"] > 0]
        if not active:
            lines.append(f"| {strat_name} | 0 | — | 0 | 0 | 0 |")
            continue
        mean_n = np.mean([r["n"] for r in active])
        mean_wr = np.mean([r["wr"] for r in active])
        sum_r = sum(r["r"] for r in active)
        mean_rh = np.mean([r["r_high"] for r in active])
        n_win = sum(1 for r in srows if r["winner"])
        lines.append(
            f"| {strat_name} | {mean_n:.1f} | {mean_wr:.1f} | {sum_r:+.1f} | "
            f"{mean_rh:+.1f} | {n_win} |"
        )
    lines.append("")

    # Full table
    lines.append("## Full 120-combo table (ranked by R_high)")
    lines.append("")
    lines.append("| Strategy | Ticker | N | WR% | Raw R | R_low | R_high | Kelly% | CAGR_high | Winner |")
    lines.append("|----------|--------|---|-----|-------|-------|--------|--------|-----------|--------|")
    for r in ranked:
        w_mark = "yes" if r["winner"] else ""
        lines.append(
            f"| {r['strategy']} | {r['ticker']} | {r['n']} | {r['wr']:.1f} | "
            f"{r['r']:+.1f} | {r['r_low']:+.1f} | {r['r_high']:+.1f} | "
            f"{r['kelly']:.2f} | {r['cagr_high']:+.1f}% | {w_mark} |"
        )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("Generated by `scripts/backtest/agent4_breakout_multi.py`.")
    lines.append("Hygiene gate = McLean-Pontiff × 0.35 + Robinhood exec drag + 0.70× options gap "
                 "(see `scripts/backtest/backtest_hygiene.py`).")
    lines.append("`in_sample_derived=False` because all breakout params are from published sources "
                 "(turtle rules, Jegadeesh-Titman 1993, VCP/Minervini, NR7/Crabel, Bollinger).")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines))


def main():
    print("Agent 4 — Breakout Multi-Ticker Bakeoff")
    print("=" * 90)
    print(f"Tickers: {len(TICKERS)} · Strategies: {len(STRATEGIES)} · Total combos: {len(TICKERS)*len(STRATEGIES)}")
    print()

    rows, avg_years = run_all()

    ranked = sorted(rows, key=lambda r: -r["r_high"])
    winners = [r for r in ranked if r["winner"]]

    print(f"\n{'Rank':<5} {'Strategy':<24} {'Ticker':<7} {'N':>4} {'WR%':>6} {'Raw R':>8} {'R_high':>8} {'CAGR_h':>8} {'W?':>3}")
    print("-" * 90)
    for i, r in enumerate(ranked[:25], 1):
        w = "yes" if r["winner"] else ""
        print(f"{i:<5} {r['strategy']:<24} {r['ticker']:<7} {r['n']:>4} {r['wr']:>5.1f}% "
              f"{r['r']:>+7.1f}R {r['r_high']:>+7.1f}R {r['cagr_high']:>+6.1f}% {w:>3}")

    print()
    print(f"WINNERS: {len(winners)} / {len(rows)}")
    if winners:
        print("Top 3 by CAGR_high:")
        for r in sorted(winners, key=lambda r: -r["cagr_high"])[:3]:
            print(f"  {r['strategy']:<24} {r['ticker']:<7} "
                  f"CAGR_high={r['cagr_high']:+.1f}% R_high={r['r_high']:+.1f}R "
                  f"N={r['n']} WR={r['wr']:.1f}%")

    out_path = Path.home() / "Documents" / "BMG-Capital-Vault" / "research" / "52-breakout-multi-ticker-agent.md"
    write_vault_note(rows, avg_years, out_path)
    print(f"\nVault note written: {out_path}")


if __name__ == "__main__":
    main()
