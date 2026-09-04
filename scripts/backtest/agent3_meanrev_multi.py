"""Agent-3 mean-reversion multi-ticker bakeoff.

Task: find whether ANY mean-reversion strategy has real edge across multiple tickers.

Strategies (all daily bars, all long-only unless noted):
  R1  Connors RSI(2)<10  + price>200SMA → buy; exit RSI(2)>65
  R2  RSI(2)<5           + price>200SMA → buy; exit RSI(2)>65  (stricter oversold)
  R3  Bollinger 2σ oversold reversal — close<BB_dn(20,2) two days in a row +
      close>BB_dn today → buy; exit BB_mid touch
  R4  3-day rolling drawdown > 6% → buy at close;
      exit at first daily close > entry
  R5  VWAP-fade SHORT — close > 20d VWAP + 1σ AND RSI(14) > 70 → short;
      exit at VWAP touch (rolling 20-day session-VWAP proxy)
  R6  Overnight gap reversal — gap down > 3% at open → buy at open;
      exit at close (Fama-French disposition-effect proxy)

Runs each strategy × 20 tickers, applies hygiene haircut (in_sample_derived=False),
ranks all (strategy, ticker) combos by post-hygiene R_high, and writes results to
`~/Documents/BMG-Capital-Vault/research/51-meanrev-multi-ticker-agent.md`.

Winner = post-hygiene R_high > 0 AND CAGR at Kelly-safe sizing > 5%.
"""
from __future__ import annotations

import sys
from pathlib import Path
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from backtest_hygiene import compute_haircut


# ═══════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════

DATA_DIR = Path(__file__).parent / "data" / "multi"
TICKERS = [
    "TSLA", "NVDA", "MSTR", "COIN", "SMCI", "PLTR", "AMD", "META", "GOOG",
    "AAPL", "MSFT", "QQQ", "SPY", "IWM", "XLE", "ARKK", "SOFI", "HOOD",
    "GME", "AVGO",
]

VAULT_OUT = Path.home() / "Documents" / "BMG-Capital-Vault" / "research" / "51-meanrev-multi-ticker-agent.md"


# ═══════════════════════════════════════════════════════════════════════
# LOAD DATA
# ═══════════════════════════════════════════════════════════════════════

def load_ticker(ticker: str) -> pd.DataFrame:
    csv_path = DATA_DIR / f"{ticker}_daily.csv"
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


def rolling_vwap(close, high, low, volume, n=20):
    """Rolling n-day session-VWAP proxy using typical price × volume."""
    tp = (high + low + close) / 3.0
    tpv = tp * volume
    num = tpv.rolling(n).sum()
    den = volume.rolling(n).sum().replace(0, 1e-9)
    vwap = num / den
    # 1-sigma band using typical-price stddev over same window
    sd = tp.rolling(n).std()
    return vwap, sd


# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _open_r(entry_atr: float) -> float:
    """Denominator for R-multiple = 2 × ATR."""
    return 2.0 * entry_atr if entry_atr and entry_atr > 0 else 1e-9


def _mk_trade(name, df, ei, xi, ep, xp, atr_val, side="LONG"):
    r_stop = _open_r(atr_val)
    if side == "LONG":
        r_multiple = (xp - ep) / r_stop
    else:  # SHORT
        r_multiple = (ep - xp) / r_stop
    return {
        "strategy": name,
        "entry_date": df.index[ei],
        "exit_date": df.index[xi],
        "entry_price": ep,
        "exit_price": xp,
        "r_multiple": r_multiple,
        "outcome": "WIN" if r_multiple > 0 else "LOSS",
        "hold_days": xi - ei,
        "side": side,
    }


# ═══════════════════════════════════════════════════════════════════════
# R1 — Connors RSI(2) < 10 + 200SMA
# ═══════════════════════════════════════════════════════════════════════

def strategy_r1_rsi2_lt10(df: pd.DataFrame) -> list[dict]:
    close = df["close"]
    rsi2 = rsi(close, 2)
    sma200 = close.rolling(200).mean()
    atr14 = atr(df["high"], df["low"], close, 14)

    trades = []
    in_pos = False
    ei = ep = ea = None

    for i in range(200, len(df)):
        cur_close = close.iloc[i]
        cur_rsi = rsi2.iloc[i]
        cur_sma = sma200.iloc[i]

        if not in_pos:
            if pd.notna(cur_rsi) and pd.notna(cur_sma) and cur_rsi < 10 and cur_close > cur_sma:
                in_pos = True
                ei = i
                ep = cur_close
                ea = atr14.iloc[i] if pd.notna(atr14.iloc[i]) else cur_close * 0.02
        else:
            if pd.notna(cur_rsi) and cur_rsi > 65:
                trades.append(_mk_trade("R1_rsi2_lt10", df, ei, i, ep, cur_close, ea))
                in_pos = False
    return trades


# ═══════════════════════════════════════════════════════════════════════
# R2 — RSI(2) < 5 + 200SMA (stricter oversold)
# ═══════════════════════════════════════════════════════════════════════

def strategy_r2_rsi2_lt5(df: pd.DataFrame) -> list[dict]:
    close = df["close"]
    rsi2 = rsi(close, 2)
    sma200 = close.rolling(200).mean()
    atr14 = atr(df["high"], df["low"], close, 14)

    trades = []
    in_pos = False
    ei = ep = ea = None

    for i in range(200, len(df)):
        cur_close = close.iloc[i]
        cur_rsi = rsi2.iloc[i]
        cur_sma = sma200.iloc[i]

        if not in_pos:
            if pd.notna(cur_rsi) and pd.notna(cur_sma) and cur_rsi < 5 and cur_close > cur_sma:
                in_pos = True
                ei = i
                ep = cur_close
                ea = atr14.iloc[i] if pd.notna(atr14.iloc[i]) else cur_close * 0.02
        else:
            if pd.notna(cur_rsi) and cur_rsi > 65:
                trades.append(_mk_trade("R2_rsi2_lt5", df, ei, i, ep, cur_close, ea))
                in_pos = False
    return trades


# ═══════════════════════════════════════════════════════════════════════
# R3 — Bollinger 2σ oversold reversal
# ═══════════════════════════════════════════════════════════════════════

def strategy_r3_bollinger_reversal(df: pd.DataFrame) -> list[dict]:
    close = df["close"]
    bb_mid, bb_up, bb_dn = bollinger(close, 20, 2.0)
    atr14 = atr(df["high"], df["low"], close, 14)

    trades = []
    in_pos = False
    ei = ep = ea = None

    for i in range(21, len(df)):
        cur_close = close.iloc[i]
        prev_close = close.iloc[i - 1]
        prev2_close = close.iloc[i - 2]
        cur_bb_dn = bb_dn.iloc[i]
        prev_bb_dn = bb_dn.iloc[i - 1]
        prev2_bb_dn = bb_dn.iloc[i - 2]
        cur_bb_mid = bb_mid.iloc[i]

        if pd.isna(cur_bb_dn) or pd.isna(prev_bb_dn) or pd.isna(prev2_bb_dn):
            continue

        if not in_pos:
            two_day_oversold = (prev_close < prev_bb_dn) and (prev2_close < prev2_bb_dn)
            reversal_today = cur_close > cur_bb_dn
            if two_day_oversold and reversal_today:
                in_pos = True
                ei = i
                ep = cur_close
                ea = atr14.iloc[i] if pd.notna(atr14.iloc[i]) else cur_close * 0.02
        else:
            if pd.notna(cur_bb_mid) and cur_close >= cur_bb_mid:
                trades.append(_mk_trade("R3_bb_reversal", df, ei, i, ep, cur_close, ea))
                in_pos = False
    return trades


# ═══════════════════════════════════════════════════════════════════════
# R4 — 3-day rolling drawdown > 6%
# ═══════════════════════════════════════════════════════════════════════

def strategy_r4_ndaydrop(df: pd.DataFrame) -> list[dict]:
    close = df["close"]
    high3 = close.rolling(3).max()
    dd_3d = (close / high3) - 1.0  # negative when drawdown
    atr14 = atr(df["high"], df["low"], close, 14)

    trades = []
    in_pos = False
    ei = ep = ea = None

    for i in range(3, len(df)):
        cur_close = close.iloc[i]
        cur_dd = dd_3d.iloc[i]

        if not in_pos:
            if pd.notna(cur_dd) and cur_dd <= -0.06:
                in_pos = True
                ei = i
                ep = cur_close
                ea = atr14.iloc[i] if pd.notna(atr14.iloc[i]) else cur_close * 0.02
        else:
            if cur_close > ep:
                trades.append(_mk_trade("R4_ndaydrop", df, ei, i, ep, cur_close, ea))
                in_pos = False
    return trades


# ═══════════════════════════════════════════════════════════════════════
# R5 — VWAP-fade short (close > VWAP+1σ AND RSI(14)>70)
# ═══════════════════════════════════════════════════════════════════════

def strategy_r5_vwap_fade_short(df: pd.DataFrame) -> list[dict]:
    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]
    rsi14 = rsi(close, 14)
    vwap, tp_sd = rolling_vwap(close, high, low, volume, n=20)
    atr14 = atr(high, low, close, 14)

    trades = []
    in_pos = False
    ei = ep = ea = None

    for i in range(21, len(df)):
        cur_close = close.iloc[i]
        cur_vwap = vwap.iloc[i]
        cur_sd = tp_sd.iloc[i]
        cur_rsi = rsi14.iloc[i]

        if pd.isna(cur_vwap) or pd.isna(cur_sd) or pd.isna(cur_rsi):
            continue

        upper = cur_vwap + cur_sd  # 1-sigma band

        if not in_pos:
            if cur_close > upper and cur_rsi > 70:
                in_pos = True
                ei = i
                ep = cur_close
                ea = atr14.iloc[i] if pd.notna(atr14.iloc[i]) else cur_close * 0.02
        else:
            # exit at VWAP touch (close crosses back to/below VWAP)
            if cur_close <= cur_vwap:
                trades.append(_mk_trade("R5_vwap_fade_short", df, ei, i, ep, cur_close, ea, side="SHORT"))
                in_pos = False
    return trades


# ═══════════════════════════════════════════════════════════════════════
# R6 — Overnight gap-down reversal (buy at open, exit at close)
# ═══════════════════════════════════════════════════════════════════════

def strategy_r6_gap_reversal(df: pd.DataFrame) -> list[dict]:
    close = df["close"]
    open_ = df["open"]
    high = df["high"]
    low = df["low"]
    atr14 = atr(high, low, close, 14)

    prev_close = close.shift(1)
    gap_pct = (open_ - prev_close) / prev_close

    trades = []

    for i in range(15, len(df)):
        g = gap_pct.iloc[i]
        if pd.isna(g):
            continue
        if g <= -0.03:
            ep = open_.iloc[i]
            xp = close.iloc[i]
            ea = atr14.iloc[i - 1] if pd.notna(atr14.iloc[i - 1]) else ep * 0.02
            trades.append(_mk_trade("R6_gap_reversal", df, i, i, ep, xp, ea, side="LONG"))
    return trades


# ═══════════════════════════════════════════════════════════════════════
# BAKE-OFF DRIVER
# ═══════════════════════════════════════════════════════════════════════

STRATEGIES = [
    ("R1_rsi2_lt10",         strategy_r1_rsi2_lt10),
    ("R2_rsi2_lt5",          strategy_r2_rsi2_lt5),
    ("R3_bb_reversal",       strategy_r3_bollinger_reversal),
    ("R4_ndaydrop",          strategy_r4_ndaydrop),
    ("R5_vwap_fade_short",   strategy_r5_vwap_fade_short),
    ("R6_gap_reversal",      strategy_r6_gap_reversal),
]


def analyze(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0, "w": 0, "l": 0, "wr": 0.0, "r": 0.0, "avg_r": 0.0}
    n = len(trades)
    w = sum(1 for t in trades if t["outcome"] == "WIN")
    l = sum(1 for t in trades if t["outcome"] == "LOSS")
    r_total = sum(t["r_multiple"] for t in trades)
    wr = 100 * w / max(1, w + l)
    return {"n": n, "w": w, "l": l, "wr": wr, "r": r_total, "avg_r": r_total / n}


def run_all():
    rows = []
    per_ticker_years = {}

    for ticker in TICKERS:
        try:
            df = load_ticker(ticker)
        except FileNotFoundError:
            print(f"[skip] no data for {ticker}")
            continue

        years = (df.index[-1] - df.index[0]).days / 365.25
        per_ticker_years[ticker] = years

        for strat_name, fn in STRATEGIES:
            trades = fn(df)
            stats = analyze(trades)
            if stats["n"] == 0:
                rows.append({
                    "ticker": ticker,
                    "strategy": strat_name,
                    "years": years,
                    "n": 0, "wr": 0.0, "raw_r": 0.0, "avg_r": 0.0,
                    "r_low": 0.0, "r_high": 0.0,
                    "kelly_safe_pct": 0.0,
                    "cagr_low_pct": 0.0, "cagr_high_pct": 0.0,
                })
                continue

            hc = compute_haircut(
                raw_r=stats["r"],
                n_trades=stats["n"],
                wr_pct=stats["wr"],
                avg_rr=abs(stats["avg_r"]) if stats["avg_r"] != 0 else 1.0,
                declared_sizing_pct=5.0,
                in_sample_derived=False,  # strategies published — not fit to this data
                execution_scenario="robinhood",
                years=years,
            )
            rows.append({
                "ticker": ticker,
                "strategy": strat_name,
                "years": years,
                "n": stats["n"],
                "wr": stats["wr"],
                "raw_r": stats["r"],
                "avg_r": stats["avg_r"],
                "r_low": hc.realistic_r_low,
                "r_high": hc.realistic_r_high,
                "kelly_safe_pct": hc.kelly_safe_sizing_pct,
                "cagr_low_pct": hc.realistic_annual_cagr_low * 100,
                "cagr_high_pct": hc.realistic_annual_cagr_high * 100,
            })
    return rows, per_ticker_years


# ═══════════════════════════════════════════════════════════════════════
# REPORT
# ═══════════════════════════════════════════════════════════════════════

def _winner(row) -> bool:
    return row["r_high"] > 0 and row["cagr_high_pct"] > 5.0


def write_report(rows: list[dict], per_ticker_years: dict[str, float]) -> tuple[int, list[dict]]:
    # Sort by post-hygiene R_high desc
    ranked = sorted(rows, key=lambda r: -r["r_high"])
    winners = [r for r in ranked if _winner(r)]

    # Per-strategy aggregates (mean across tickers where n>0)
    strat_agg = {}
    for name, _ in STRATEGIES:
        subset = [r for r in rows if r["strategy"] == name and r["n"] > 0]
        if not subset:
            strat_agg[name] = None
            continue
        total_n = sum(r["n"] for r in subset)
        total_raw_r = sum(r["raw_r"] for r in subset)
        total_r_high = sum(r["r_high"] for r in subset)
        total_r_low = sum(r["r_low"] for r in subset)
        wr_weighted = sum(r["wr"] * r["n"] for r in subset) / max(1, total_n)
        n_winners = sum(1 for r in subset if _winner(r))
        strat_agg[name] = {
            "tickers_traded": len(subset),
            "total_trades": total_n,
            "sum_raw_r": total_raw_r,
            "sum_r_low": total_r_low,
            "sum_r_high": total_r_high,
            "weighted_wr": wr_weighted,
            "n_winner_tickers": n_winners,
            "avg_cagr_high_pct": np.mean([r["cagr_high_pct"] for r in subset]),
        }

    lines = []
    lines.append("# Mean-Reversion Multi-Ticker Bakeoff — Agent-3")
    lines.append("")
    lines.append("Automated experiment: **6 mean-reversion strategies × 20 tickers = 120 backtests.**")
    lines.append("")
    lines.append("**Script:** `scripts/backtest/agent3_meanrev_multi.py`  ")
    lines.append("**Hygiene:** `backtest_hygiene.compute_haircut(..., in_sample_derived=False, execution_scenario='robinhood')`  ")
    lines.append("**Winner def:** post-hygiene `R_high > 0` **AND** CAGR at Kelly-safe sizing `> 5%`.")
    lines.append("")
    lines.append(f"**Result:** {len(winners)} of {len(rows)} (strategy, ticker) combos qualify as winners.")
    lines.append("")

    # ── Strategies tested ────────────────────────────────────────────────
    lines.append("## Strategies")
    lines.append("")
    lines.append("| ID  | Rule |")
    lines.append("|-----|------|")
    lines.append("| R1  | RSI(2)<10 + close>200SMA → buy; exit RSI(2)>65 (Connors) |")
    lines.append("| R2  | RSI(2)<5  + close>200SMA → buy; exit RSI(2)>65 (stricter oversold) |")
    lines.append("| R3  | 2 consecutive closes < BB_dn(20,2), then close > BB_dn today → buy; exit BB_mid |")
    lines.append("| R4  | 3-day drawdown > 6% → buy at close; exit first daily close > entry |")
    lines.append("| R5  | close > 20d VWAP + 1σ AND RSI(14)>70 → short; exit VWAP touch |")
    lines.append("| R6  | Gap-down > 3% at open → buy at open; exit at close |")
    lines.append("")

    # ── Per-strategy summary ─────────────────────────────────────────────
    lines.append("## Per-strategy aggregate (all tickers)")
    lines.append("")
    lines.append("| Strategy | Tickers | Trades | Weighted WR | Sum Raw R | Sum R_low | Sum R_high | Winner tickers |")
    lines.append("|----------|--------:|-------:|------------:|----------:|----------:|-----------:|---------------:|")
    for name, _ in STRATEGIES:
        a = strat_agg.get(name)
        if a is None:
            lines.append(f"| {name} | 0 | 0 | — | — | — | — | 0 |")
            continue
        lines.append(
            f"| {name} | {a['tickers_traded']} | {a['total_trades']} | "
            f"{a['weighted_wr']:.1f}% | {a['sum_raw_r']:+.1f}R | {a['sum_r_low']:+.1f}R | "
            f"{a['sum_r_high']:+.1f}R | {a['n_winner_tickers']} |"
        )
    lines.append("")

    # ── Top 20 winners overall ───────────────────────────────────────────
    lines.append("## Top 20 (strategy, ticker) combos ranked by post-hygiene R_high")
    lines.append("")
    lines.append("| Rank | Strategy | Ticker | N | WR% | Raw R | R_low | R_high | Kelly-safe % | CAGR low..high |")
    lines.append("|-----:|----------|--------|--:|----:|------:|------:|-------:|-------------:|---------------|")
    for i, r in enumerate(ranked[:20], 1):
        lines.append(
            f"| {i} | {r['strategy']} | {r['ticker']} | {r['n']} | {r['wr']:.1f}% | "
            f"{r['raw_r']:+.1f}R | {r['r_low']:+.1f}R | {r['r_high']:+.1f}R | "
            f"{r['kelly_safe_pct']:.2f}% | {r['cagr_low_pct']:+.1f}% .. {r['cagr_high_pct']:+.1f}% |"
        )
    lines.append("")

    # ── Winners section ──────────────────────────────────────────────────
    lines.append(f"## Winners ({len(winners)} combos meeting R_high > 0 AND CAGR > 5%)")
    lines.append("")
    if not winners:
        lines.append("_No (strategy, ticker) combos cleared the winner definition._")
    else:
        lines.append("| Strategy | Ticker | N | WR% | Raw R | R_high | CAGR high |")
        lines.append("|----------|--------|--:|----:|------:|-------:|----------:|")
        for r in winners:
            lines.append(
                f"| {r['strategy']} | {r['ticker']} | {r['n']} | {r['wr']:.1f}% | "
                f"{r['raw_r']:+.1f}R | {r['r_high']:+.1f}R | {r['cagr_high_pct']:+.1f}% |"
            )
    lines.append("")

    # ── Full 120-row table ───────────────────────────────────────────────
    lines.append("## Full results — all 120 (strategy, ticker) combos")
    lines.append("")
    lines.append("| Strategy | Ticker | Years | N | WR% | Raw R | R_low | R_high | Kelly-safe % | CAGR high % | Winner? |")
    lines.append("|----------|--------|------:|--:|----:|------:|------:|-------:|-------------:|------------:|:-------:|")
    # sort by strategy then ticker for readability
    for r in sorted(rows, key=lambda x: (x["strategy"], x["ticker"])):
        win = "✅" if _winner(r) else ""
        lines.append(
            f"| {r['strategy']} | {r['ticker']} | {r['years']:.1f} | {r['n']} | {r['wr']:.1f}% | "
            f"{r['raw_r']:+.1f}R | {r['r_low']:+.1f}R | {r['r_high']:+.1f}R | "
            f"{r['kelly_safe_pct']:.2f}% | {r['cagr_high_pct']:+.1f}% | {win} |"
        )
    lines.append("")

    # ── Interpretation ───────────────────────────────────────────────────
    lines.append("## Interpretation")
    lines.append("")
    # top 3 combos summary
    top3 = ranked[:3]
    if top3 and top3[0]["r_high"] > 0:
        lines.append("**Top 3 by post-hygiene R_high:**")
        lines.append("")
        for i, r in enumerate(top3, 1):
            lines.append(
                f"{i}. **{r['strategy']} on {r['ticker']}** — "
                f"{r['n']} trades, WR {r['wr']:.1f}%, raw {r['raw_r']:+.1f}R, "
                f"realistic {r['r_low']:+.1f}R .. {r['r_high']:+.1f}R over {r['years']:.1f} yrs, "
                f"CAGR at Kelly-safe {r['kelly_safe_pct']:.2f}%: {r['cagr_low_pct']:+.1f}% .. {r['cagr_high_pct']:+.1f}%."
            )
        lines.append("")

    # per-strategy narrative
    best_strat = None
    best_val = -1e18
    for name, a in strat_agg.items():
        if a is None:
            continue
        if a["sum_r_high"] > best_val:
            best_val = a["sum_r_high"]
            best_strat = name
    if best_strat is not None:
        lines.append(f"**Best strategy across the ticker universe (sum R_high):** `{best_strat}` — "
                     f"{strat_agg[best_strat]['n_winner_tickers']} winner tickers of "
                     f"{strat_agg[best_strat]['tickers_traded']} traded.")
        lines.append("")

    lines.append("**Caveat (hygiene):** haircut assumes strategies were NOT derived from this data "
                 "(rules come from Connors, Bollinger, Fama-French, etc.), so `in_sample_derived=False` "
                 "and no McLean-Pontiff 0.35× is applied. Execution drag is Robinhood-worst-case "
                 "(0.06R/trade). Options-gap multiplier NOT applied (these are equity strategies).")
    lines.append("")
    lines.append("**Winner definition recap:** post-hygiene `R_high > 0` AND CAGR at Kelly-safe sizing "
                 "`> 5%`. Kelly-safe is capped at 1.5% per research/35.")
    lines.append("")

    VAULT_OUT.parent.mkdir(parents=True, exist_ok=True)
    VAULT_OUT.write_text("\n".join(lines))
    return len(winners), ranked[:3]


# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════

def main():
    print(f"Mean-reversion multi-ticker bakeoff — {len(STRATEGIES)} strategies × {len(TICKERS)} tickers")
    print("=" * 90)
    rows, per_ticker_years = run_all()

    # console summary
    print(f"\nTotal (strategy, ticker) combos: {len(rows)}")
    n_winners = sum(1 for r in rows if _winner(r))
    print(f"Winners (R_high>0 AND CAGR_high>5%): {n_winners}")

    print(f"\n{'Strategy':<22} {'Ticker':<6} {'N':>4} {'WR%':>6} {'RawR':>8} "
          f"{'R_high':>8} {'CAGRhi':>8} Win?")
    print("-" * 90)
    for r in sorted(rows, key=lambda x: -x["r_high"])[:25]:
        win = "✅" if _winner(r) else ""
        print(f"{r['strategy']:<22} {r['ticker']:<6} {r['n']:>4} {r['wr']:>5.1f}% "
              f"{r['raw_r']:>+7.1f}R {r['r_high']:>+7.1f}R {r['cagr_high_pct']:>+7.1f}% {win}")

    n_winners, top3 = write_report(rows, per_ticker_years)
    print(f"\nReport written: {VAULT_OUT}")
    print(f"Winners: {n_winners}")
    if top3 and top3[0]["r_high"] > 0:
        print("\nTop 3:")
        for i, r in enumerate(top3, 1):
            print(f"  {i}. {r['strategy']} / {r['ticker']} — R_high={r['r_high']:+.1f}R, "
                  f"CAGR_high={r['cagr_high_pct']:+.1f}%")


if __name__ == "__main__":
    main()
