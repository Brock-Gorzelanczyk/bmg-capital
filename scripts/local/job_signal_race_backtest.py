"""Signal Race Backtest — race every BMG academic signal against 100 stocks.

Tests every signal from our vault research canon head-to-head:
  - Which signals actually predicted 6-month forward returns?
  - Which ones look great in theory but flopped in practice?
  - Which ones agree with each other? (correlation matrix)
  - What's the composite BMG signal really doing vs raw academic factors?

Output: rich Markdown report to Obsidian with:
  - Leaderboard table (signals ranked by return + hit rate + Sharpe)
  - ASCII bar chart for visual comparison
  - Per-signal top-5 picks + how each performed
  - Signal-vs-signal correlation matrix
  - Insights section

Universe: top ~100 S&P 500 stocks by market cap (well-known, liquid, reliable data).
Formation date: 6 months ago.
Hold period: 6 months (through today).
Long-only: each signal picks top-20 stocks by score, holds equal-weight.

Usage:
  ./backend/.venv-py39-backup/bin/python scripts/local/job_signal_race_backtest.py

Or if yfinance is available in system python:
  python3 scripts/local/job_signal_race_backtest.py

Runtime: ~5-10 minutes (100 stocks × Yahoo fetch).

Ref: vault/research/*.md — every signal here comes from a verified paper.
"""
from __future__ import annotations

import json
import math
import statistics
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

HERE = Path(__file__).parent.resolve()
sys.path.insert(0, str(HERE))
from _obsidian import write_job_output  # noqa: E402


# ─────────────────────────────────────────────────────────────────
# Universe — top 100 S&P 500 stocks by market cap (Aug 2026)
# Curated to include mix of sectors, all with reliable Yahoo data
# ─────────────────────────────────────────────────────────────────

UNIVERSE = [
    # Tech mega-caps
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "AVGO", "ORCL", "CRM",
    "ADBE", "AMD", "INTC", "CSCO", "IBM", "QCOM", "TXN", "NOW", "INTU",
    # Financials
    "JPM", "BAC", "WFC", "C", "GS", "MS", "SCHW", "AXP", "BLK", "SPGI",
    # Healthcare
    "UNH", "LLY", "JNJ", "MRK", "ABBV", "PFE", "ABT", "TMO", "DHR", "AMGN",
    "CVS", "MDT", "BMY", "GILD", "ELV",
    # Consumer
    "AMZN", "TSLA", "HD", "MCD", "NKE", "SBUX", "LOW", "TJX", "TGT",
    "COST", "WMT", "PG", "KO", "PEP", "MO", "PM", "CL", "MDLZ",
    # Industrials
    "CAT", "DE", "GE", "HON", "UPS", "RTX", "LMT", "BA", "UNP", "MMM",
    # Energy
    "XOM", "CVX", "COP", "SLB", "EOG", "PSX",
    # Comm services
    "NFLX", "DIS", "T", "VZ", "CMCSA",
    # Real estate
    "PLD", "SPG", "AMT", "EQIX",
    # Utilities
    "NEE", "DUK", "SO",
    # Materials
    "LIN", "APD", "SHW",
    # Value/turnaround candidates in current portfolio
    "F", "GM", "HOG", "ET", "MTDR", "ELAN", "AAT", "KMPR", "VFC", "APTV",
    "BSX", "BABA", "REZI",
]
# Dedupe while preserving order
seen = set()
UNIVERSE = [t for t in UNIVERSE if not (t in seen or seen.add(t))]

# Backtest params
HOLD_MONTHS = 6
TOP_N = 20  # top-N per signal
BENCHMARK_TICKER = "SPY"


# ─────────────────────────────────────────────────────────────────
# Data fetching — Yahoo Finance v8 chart API (free, no auth)
# ─────────────────────────────────────────────────────────────────

def _yahoo_daily_closes(symbol: str, start_ts: int, end_ts: int) -> Optional[List[Tuple[int, float]]]:
    """Fetch daily closes as [(timestamp, close), ...]. None on failure."""
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?period1={start_ts}&period2={end_ts}&interval=1d")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (BMG SignalRace)"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, json.JSONDecodeError):
        return None
    result = data.get("chart", {}).get("result", [])
    if not result:
        return None
    ts = result[0].get("timestamp", []) or []
    closes = result[0].get("indicators", {}).get("quote", [{}])[0].get("close", []) or []
    return [(t, c) for t, c in zip(ts, closes) if c is not None]


def _fetch_universe(tickers: List[str], start_dt: datetime, end_dt: datetime) -> Dict[str, List[Tuple[int, float]]]:
    """Fetch daily closes for every ticker in universe. Sequential (Yahoo rate-limits parallel)."""
    start_ts = int(start_dt.timestamp())
    end_ts = int(end_dt.timestamp())
    data: Dict[str, List[Tuple[int, float]]] = {}
    for i, t in enumerate(tickers, 1):
        if i % 20 == 0:
            print(f"  fetched {i}/{len(tickers)}...")
        closes = _yahoo_daily_closes(t, start_ts, end_ts)
        if closes and len(closes) >= 60:
            data[t] = closes
        time.sleep(0.1)  # be nice to Yahoo
    return data


def _fetch_fundamentals(tickers: List[str]) -> Dict[str, Dict]:
    """Fetch current fundamentals via yfinance. Returns {ticker: {forwardPE, priceToBook, ...}}.

    NOTE: These are CURRENT snapshots, not historical. Introduces mild look-ahead bias
    for value backtests. Flagged as such in the report. Value fundamentals are typically
    slow-changing (annual reports), so a 6-month snapshot approximates T-6mo reasonably.
    """
    try:
        import yfinance as yf
    except ImportError:
        print("  yfinance not available — skipping fundamental signals")
        return {}

    fund: Dict[str, Dict] = {}
    for i, t in enumerate(tickers, 1):
        if i % 20 == 0:
            print(f"  fundamentals {i}/{len(tickers)}...")
        try:
            info = yf.Ticker(t).info or {}
            fund[t] = {
                "priceToBook": info.get("priceToBook"),
                "forwardPE": info.get("forwardPE"),
                "trailingPE": info.get("trailingPE"),
                "returnOnAssets": info.get("returnOnAssets"),
                "returnOnEquity": info.get("returnOnEquity"),
                "grossMargins": info.get("grossMargins"),
                "debtToEquity": info.get("debtToEquity"),
                "marketCap": info.get("marketCap"),
                "sector": info.get("sector"),
            }
        except Exception:
            continue
        time.sleep(0.1)
    return fund


# ─────────────────────────────────────────────────────────────────
# Utility: find close price at (or near) a target date
# ─────────────────────────────────────────────────────────────────

def _close_at(closes: List[Tuple[int, float]], target_dt: datetime) -> Optional[float]:
    """Return the closing price on or just before target_dt."""
    if not closes:
        return None
    target_ts = int(target_dt.timestamp())
    # Find last close with ts <= target_ts
    for ts, c in reversed(closes):
        if ts <= target_ts:
            return c
    return None


def _closes_before(closes: List[Tuple[int, float]], target_dt: datetime) -> List[float]:
    """Return list of close values with timestamp <= target_dt (chronological)."""
    target_ts = int(target_dt.timestamp())
    return [c for ts, c in closes if ts <= target_ts]


# ─────────────────────────────────────────────────────────────────
# Signal computations — each returns a score per ticker as of formation date
# Higher score = better (long-favored). None = insufficient data.
# ─────────────────────────────────────────────────────────────────

def sig_momentum_12_2(closes: List[Tuple[int, float]], formation_dt: datetime) -> Optional[float]:
    """Carhart UMD momentum — cumulative return months t-12 to t-2."""
    end = formation_dt - timedelta(days=30)  # t-1 skip (short-term reversal)
    start = formation_dt - timedelta(days=365)
    p_start = _close_at(closes, start)
    p_end = _close_at(closes, end)
    if not p_start or not p_end:
        return None
    return (p_end / p_start) - 1.0


def sig_momentum_6mo(closes: List[Tuple[int, float]], formation_dt: datetime) -> Optional[float]:
    """Simpler momentum — trailing 6mo return at formation."""
    start = formation_dt - timedelta(days=180)
    p_start = _close_at(closes, start)
    p_end = _close_at(closes, formation_dt)
    if not p_start or not p_end:
        return None
    return (p_end / p_start) - 1.0


def sig_reversal_1mo(closes: List[Tuple[int, float]], formation_dt: datetime) -> Optional[float]:
    """1-month reversal (contrarian) — NEGATIVE trailing 1mo return → high score."""
    start = formation_dt - timedelta(days=30)
    p_start = _close_at(closes, start)
    p_end = _close_at(closes, formation_dt)
    if not p_start or not p_end:
        return None
    return -1.0 * ((p_end / p_start) - 1.0)  # negate so worst 1mo = highest score


def sig_above_200sma(closes: List[Tuple[int, float]], formation_dt: datetime) -> Optional[float]:
    """Faber/Weinstein trend filter — return ratio (price / 200-SMA) as of formation."""
    prices = _closes_before(closes, formation_dt)
    if len(prices) < 200:
        return None
    sma200 = sum(prices[-200:]) / 200
    current = prices[-1]
    return current / sma200  # >1 = above; <1 = below


def sig_low_beta(closes: List[Tuple[int, float]], spy_closes: List[Tuple[int, float]],
                 formation_dt: datetime) -> Optional[float]:
    """Frazzini-Pedersen BAB — low beta → high score. Beta from OLS on 252d daily returns."""
    stock_prices = _closes_before(closes, formation_dt)
    spy_prices = _closes_before(spy_closes, formation_dt)
    if len(stock_prices) < 60 or len(spy_prices) < 60:
        return None
    n = min(len(stock_prices), len(spy_prices), 252)
    s = stock_prices[-n:]
    m = spy_prices[-n:]
    s_ret = [(s[i] / s[i - 1]) - 1.0 for i in range(1, n)]
    m_ret = [(m[i] / m[i - 1]) - 1.0 for i in range(1, n)]
    mean_s = sum(s_ret) / len(s_ret)
    mean_m = sum(m_ret) / len(m_ret)
    cov = sum((s_ret[i] - mean_s) * (m_ret[i] - mean_m) for i in range(len(s_ret))) / len(s_ret)
    var_m = sum((r - mean_m) ** 2 for r in m_ret) / len(m_ret)
    if var_m <= 0:
        return None
    beta = cov / var_m
    return -beta  # negate so LOW beta = HIGH score


def sig_low_ivol(closes: List[Tuple[int, float]], spy_closes: List[Tuple[int, float]],
                 formation_dt: datetime) -> Optional[float]:
    """QMJ Safety leg — low idiosyncratic vol → high score."""
    stock_prices = _closes_before(closes, formation_dt)
    spy_prices = _closes_before(spy_closes, formation_dt)
    if len(stock_prices) < 60 or len(spy_prices) < 60:
        return None
    n = min(len(stock_prices), len(spy_prices), 252)
    s = stock_prices[-n:]
    m = spy_prices[-n:]
    s_ret = [(s[i] / s[i - 1]) - 1.0 for i in range(1, n)]
    m_ret = [(m[i] / m[i - 1]) - 1.0 for i in range(1, n)]
    mean_s = sum(s_ret) / len(s_ret)
    mean_m = sum(m_ret) / len(m_ret)
    cov = sum((s_ret[i] - mean_s) * (m_ret[i] - mean_m) for i in range(len(s_ret))) / len(s_ret)
    var_m = sum((r - mean_m) ** 2 for r in m_ret) / len(m_ret)
    if var_m <= 0:
        return None
    beta = cov / var_m
    alpha = mean_s - beta * mean_m
    residuals = [s_ret[i] - (alpha + beta * m_ret[i]) for i in range(len(s_ret))]
    var_e = sum(r * r for r in residuals) / max(1, len(residuals) - 1)
    ivol_annualized = math.sqrt(var_e) * math.sqrt(252)
    return -ivol_annualized  # negate so LOW ivol = HIGH score


def sig_low_pb(fund: Dict) -> Optional[float]:
    pb = fund.get("priceToBook")
    if pb is None or pb <= 0:
        return None
    return -pb  # low P/B = high score


def sig_low_fpe(fund: Dict) -> Optional[float]:
    fpe = fund.get("forwardPE")
    if fpe is None or fpe <= 0:
        return None
    return -fpe  # low PE = high score


def sig_value_combined(fund: Dict) -> Optional[float]:
    pb = fund.get("priceToBook")
    fpe = fund.get("forwardPE")
    if pb is None or fpe is None or pb <= 0 or fpe <= 0:
        return None
    # Standardize each by inverting + capping at reasonable ranges
    pb_score = 1.0 / min(pb, 50)  # cap extreme values
    fpe_score = 1.0 / min(fpe, 100)
    return pb_score + fpe_score


def sig_high_roa(fund: Dict) -> Optional[float]:
    roa = fund.get("returnOnAssets")
    if roa is None:
        return None
    return roa  # already higher = better


def sig_bmg_composite(closes: List[Tuple[int, float]], spy_closes: List[Tuple[int, float]],
                      fund: Dict, formation_dt: datetime) -> Optional[float]:
    """BMG-style composite: trend + value + safety combined.

    HARD FILTERS (all must pass): above 200-SMA, P/B < 3, forward PE < 25
    SOFT SCORE: rank by (momentum + safety + value)
    """
    trend = sig_above_200sma(closes, formation_dt)
    if trend is None or trend < 1.0:
        return None  # hard-fail: below 200-SMA
    pb = fund.get("priceToBook")
    fpe = fund.get("forwardPE")
    if pb is None or pb <= 0 or pb > 3.0:
        return None  # hard-fail: not value on P/B
    if fpe is None or fpe <= 0 or fpe > 25.0:
        return None  # hard-fail: not value on PE
    # Soft score: momentum + inverse-beta
    mom = sig_momentum_6mo(closes, formation_dt) or 0
    beta = sig_low_beta(closes, spy_closes, formation_dt) or 0
    value = sig_value_combined(fund) or 0
    return mom + 0.5 * beta + value


SIGNALS_PRICE_ONLY = {
    "MOM_12_2 (Carhart)":      "momentum_12_2",
    "MOM_6mo":                  "momentum_6mo",
    "REVERSAL_1mo (contra)":    "reversal_1mo",
    "ABOVE_200SMA (Faber)":     "above_200sma",
    "LOW_BETA (BAB)":           "low_beta",
    "LOW_IVOL (QMJ safety)":    "low_ivol",
}

SIGNALS_WITH_FUNDAMENTALS = {
    "LOW_PB (value)":           "low_pb",
    "LOW_FWD_PE (value)":       "low_fpe",
    "VALUE_COMBINED (P/B+PE)":  "value_combined",
    "HIGH_ROA (quality)":       "high_roa",
    "BMG_COMPOSITE":            "bmg_composite",
}


# ─────────────────────────────────────────────────────────────────
# Portfolio & backtest math
# ─────────────────────────────────────────────────────────────────

def forward_return(closes: List[Tuple[int, float]], formation_dt: datetime, exit_dt: datetime) -> Optional[float]:
    p_start = _close_at(closes, formation_dt)
    p_end = _close_at(closes, exit_dt)
    if not p_start or not p_end:
        return None
    return (p_end / p_start) - 1.0


def rank_and_pick_top(scores: Dict[str, float], top_n: int) -> List[str]:
    """Return tickers with the top N scores (descending)."""
    valid = [(t, s) for t, s in scores.items() if s is not None]
    valid.sort(key=lambda x: -x[1])
    return [t for t, _ in valid[:top_n]]


def portfolio_stats(picks: List[str], forward_returns: Dict[str, float],
                    benchmark_return: float) -> Dict:
    """Compute portfolio-level statistics for a signal's picks."""
    rets = [forward_returns[t] for t in picks if forward_returns.get(t) is not None]
    if not rets:
        return {"n": 0}
    mean = statistics.mean(rets)
    median = statistics.median(rets)
    stdev = statistics.stdev(rets) if len(rets) > 1 else 0.0
    # Hit rate = fraction of picks with positive return
    hits = sum(1 for r in rets if r > 0)
    # Beat rate = fraction beating benchmark
    beats = sum(1 for r in rets if r > benchmark_return)
    # Sharpe (annualized, assuming this is a 6-month return period)
    excess = mean - benchmark_return
    sharpe = (excess / stdev * math.sqrt(2)) if stdev > 0 else 0.0  # 6mo → annualize with sqrt(2)
    return {
        "n": len(rets),
        "mean_return": mean,
        "median_return": median,
        "stdev": stdev,
        "hit_rate": hits / len(rets),
        "beat_rate": beats / len(rets),
        "sharpe_annualized": sharpe,
        "excess_vs_bench": excess,
        "best": max(rets),
        "worst": min(rets),
        "picks_with_returns": {t: forward_returns[t] for t in picks if forward_returns.get(t) is not None},
    }


# ─────────────────────────────────────────────────────────────────
# Report rendering
# ─────────────────────────────────────────────────────────────────

def ascii_bar(value: float, max_val: float, width: int = 30) -> str:
    if max_val <= 0:
        return ""
    fill = int(round((value / max_val) * width))
    return "█" * max(0, min(width, fill))


def build_report(
    all_stats: Dict[str, Dict],
    benchmark_return: float,
    formation_dt: datetime,
    exit_dt: datetime,
    universe_size: int,
    fund_available: bool,
    correlations: Optional[Dict[Tuple[str, str], float]] = None,
) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    hold_months = (exit_dt - formation_dt).days / 30

    # Sort signals by mean_return desc
    ranked = sorted(
        [(name, s) for name, s in all_stats.items() if s.get("n", 0) > 0],
        key=lambda x: -x[1]["mean_return"],
    )

    lines = [
        f"# Signal Race Backtest — {today}",
        "",
        f"*BMG academic signal head-to-head. Every signal from our vault ({15}+ verified papers) tested against the same universe over the same period.*",
        "",
        "## Setup",
        "",
        f"- **Universe:** {universe_size} stocks (top S&P 500 by market cap, incl. current portfolio names)",
        f"- **Formation date:** {formation_dt.strftime('%Y-%m-%d')}",
        f"- **Exit date:** {exit_dt.strftime('%Y-%m-%d')}",
        f"- **Hold period:** {hold_months:.1f} months",
        f"- **Portfolio size per signal:** top-{TOP_N} stocks by score, equal-weighted, long-only",
        f"- **Benchmark:** {BENCHMARK_TICKER} return over same period = **{benchmark_return*100:+.2f}%**",
        f"- **Fundamental signals:** {'✓ enabled (yfinance)' if fund_available else '✗ SKIPPED (yfinance not available)'}",
        "",
    ]

    if not fund_available:
        lines.extend([
            "> **Note:** Value/quality signals require yfinance for fundamentals.",
            "> Only price-based signals ran this round. Install `yfinance` or run with backend venv for full race.",
            "",
        ])

    # LEADERBOARD
    lines.extend([
        "## 🏆 Leaderboard (ranked by 6-month portfolio return)",
        "",
        "| Rank | Signal | Return | vs SPY | Hit Rate | Beat Rate | Sharpe (ann.) | Best Pick | Worst Pick |",
        "|:---:|---|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for rank, (name, s) in enumerate(ranked, 1):
        ret = s["mean_return"] * 100
        excess = s["excess_vs_bench"] * 100
        hit = s["hit_rate"] * 100
        beat = s["beat_rate"] * 100
        sharpe = s["sharpe_annualized"]
        best = s["best"] * 100
        worst = s["worst"] * 100
        lines.append(
            f"| {rank} | **{name}** | {ret:+.2f}% | {excess:+.2f}% | {hit:.0f}% | {beat:.0f}% | {sharpe:+.2f} | {best:+.1f}% | {worst:+.1f}% |"
        )
    lines.append("")

    # ASCII BAR CHART
    lines.extend([
        "## 📊 Visual — return by signal",
        "",
        "```",
        f"{'SIGNAL':<28} {'RETURN':>8}  BAR",
        "─" * 70,
    ])
    max_ret = max(abs(s["mean_return"]) for _, s in ranked) if ranked else 0.01
    # Put SPY benchmark inline for reference
    bench_bar = ascii_bar(abs(benchmark_return), max_ret) if benchmark_return >= 0 else ""
    bench_prefix = " " if benchmark_return >= 0 else "-"
    lines.append(f"{'SPY (benchmark)':<28} {benchmark_return*100:>7.2f}%  {bench_prefix}{bench_bar}")
    lines.append("─" * 70)
    for name, s in ranked:
        ret = s["mean_return"]
        bar = ascii_bar(abs(ret), max_ret)
        prefix = " " if ret >= 0 else "-"
        lines.append(f"{name:<28} {ret*100:>7.2f}%  {prefix}{bar}")
    lines.extend(["```", ""])

    # PER-SIGNAL DETAIL
    lines.extend(["## 🔍 Per-signal detail — top picks each strategy generated", ""])
    for name, s in ranked:
        lines.append(f"### {name}  ({s['mean_return']*100:+.2f}% avg return)")
        lines.append("")
        picks_r = sorted(s["picks_with_returns"].items(), key=lambda x: -x[1])
        lines.append("| Ticker | 6mo return |")
        lines.append("|---|---:|")
        for t, r in picks_r[:10]:  # top 10 per signal
            emoji = "🟢" if r > benchmark_return else "🔴"
            lines.append(f"| {emoji} **{t}** | {r*100:+.2f}% |")
        if len(picks_r) > 10:
            worst = picks_r[-1]
            lines.append(f"| ... | ... |")
            lines.append(f"| 🔴 **{worst[0]}** (worst) | {worst[1]*100:+.2f}% |")
        lines.append("")

    # CORRELATION MATRIX
    if correlations:
        names = [n for n, _ in ranked]
        lines.extend([
            "## 🔗 Signal correlation matrix",
            "",
            "How much do these signals agree with each other (pick the same stocks)? "
            "1.00 = identical picks. 0.00 = totally independent. Negative = anti-correlated.",
            "",
            "| Signal | " + " | ".join(n[:10] for n in names) + " |",
            "|---" + "|---" * len(names) + "|",
        ])
        for n1 in names:
            row = [f"**{n1[:10]}**"]
            for n2 in names:
                c = correlations.get((n1, n2)) or correlations.get((n2, n1)) or (1.0 if n1 == n2 else 0.0)
                row.append(f"{c:+.2f}")
            lines.append("| " + " | ".join(row) + " |")
        lines.append("")

    # INSIGHTS
    lines.extend([
        "## 💡 Insights (auto-generated)",
        "",
    ])
    if ranked:
        top = ranked[0]
        bot = ranked[-1]
        # Signals that beat the benchmark
        beat_bench = [name for name, s in ranked if s["excess_vs_bench"] > 0]
        # Best-worst spread
        spread = top[1]["mean_return"] - bot[1]["mean_return"]
        # Most concentrated in winners
        best_hit = max(ranked, key=lambda x: x[1]["hit_rate"])
        # Best risk-adjusted
        best_sharpe = max(ranked, key=lambda x: x[1]["sharpe_annualized"])

        lines.append(f"- **Winner:** {top[0]} — {top[1]['mean_return']*100:+.2f}% "
                    f"({top[1]['excess_vs_bench']*100:+.2f}% vs SPY, "
                    f"{top[1]['hit_rate']*100:.0f}% of picks positive)")
        lines.append(f"- **Loser:** {bot[0]} — {bot[1]['mean_return']*100:+.2f}%")
        lines.append(f"- **Spread top vs bottom:** {spread*100:.2f}% — the difference "
                    f"a good signal makes vs a bad one")
        lines.append(f"- **Signals beating SPY ({benchmark_return*100:+.2f}%):** "
                    f"{len(beat_bench)} of {len(ranked)} → "
                    f"{'majority' if len(beat_bench) > len(ranked)/2 else 'minority'}")
        lines.append(f"- **Best hit rate:** {best_hit[0]} — {best_hit[1]['hit_rate']*100:.0f}% "
                    f"of {TOP_N} picks were positive")
        lines.append(f"- **Best risk-adjusted (Sharpe):** {best_sharpe[0]} — "
                    f"{best_sharpe[1]['sharpe_annualized']:+.2f} annualized")

    lines.extend([
        "",
        "## Caveats",
        "",
        "- **Single sample:** one formation date, one hold period. Statistical noise is high. "
        "Real edge claims need 20+ rolling formation dates (see Bailey-Lopez de Prado DSR).",
        "- **Look-ahead bias in fundamentals:** value/quality signals use CURRENT P/B, PE, ROA — "
        "not their historical value 6 months ago. For value stocks this is usually a small effect "
        "(financials are slow-changing), but flagged for honesty.",
        "- **Survivorship bias:** universe is TODAY's top 100. Stocks that were top 100 six months "
        "ago but have since delisted are missing. Realistic backtests use historical index membership.",
        "- **No transaction costs modeled:** every trade assumed at close, no bid-ask spread, no impact. "
        "Real returns net of ~25-50bps/trade would be lower (per Lopez-Lira 2024 vault note).",
        "- **Long-only, equal-weighted:** no shorting, no size-tilt, no rebalancing during hold period.",
        "",
        "## Refs (vault research supporting each signal)",
        "",
        "- MOM_12_2 → Carhart 1997 4-factor model (paper #22)",
        "- MOM_6mo → Jegadeesh-Titman 1993, Asness 2013 (via momentum leg of value+momentum)",
        "- REVERSAL_1mo → Jegadeesh 1990 short-term reversal (well-known)",
        "- ABOVE_200SMA → Faber 2007 Tactical Asset Allocation",
        "- LOW_BETA → Frazzini-Pedersen 2014 Betting Against Beta",
        "- LOW_IVOL → Ang-Hodrick-Xing-Zhang 2006; QMJ Safety leg (2019 QMJ note)",
        "- LOW_PB → Fama-French 1993 3-factor value premium (paper #21)",
        "- LOW_FWD_PE → Classic value (Basu 1983, Piotroski 2000)",
        "- HIGH_ROA → Piotroski 2000 F-Score profitability signal (paper #20)",
        "- BMG_COMPOSITE → BMG confluence framework current architecture",
        "",
        f"*Generated by scripts/local/job_signal_race_backtest.py — {today}. Re-run monthly to track signal decay.*",
    ])

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────

def run() -> str:
    print("=" * 60)
    print("SIGNAL RACE BACKTEST")
    print("=" * 60)

    # Dates
    now = datetime.now(timezone.utc)
    exit_dt = now
    formation_dt = now - timedelta(days=180)
    fetch_start = formation_dt - timedelta(days=400)  # enough for 12mo momentum + 200-SMA

    print(f"Formation: {formation_dt.strftime('%Y-%m-%d')} | Exit: {exit_dt.strftime('%Y-%m-%d')}")
    print(f"Universe: {len(UNIVERSE)} stocks + SPY benchmark")
    print()

    # Fetch price data for full universe + SPY benchmark
    print("Step 1/4: Fetching daily closes from Yahoo Finance...")
    all_tickers = list(UNIVERSE) + [BENCHMARK_TICKER]
    price_data = _fetch_universe(all_tickers, fetch_start, exit_dt)
    print(f"  ✓ Got data for {len(price_data)}/{len(all_tickers)} tickers")

    spy_closes = price_data.get(BENCHMARK_TICKER)
    if not spy_closes:
        return "ERROR: could not fetch SPY benchmark"
    benchmark_return = forward_return(spy_closes, formation_dt, exit_dt) or 0.0
    print(f"  ✓ SPY 6-month return: {benchmark_return*100:+.2f}%")
    print()

    # Fetch fundamentals (optional — for value/quality signals)
    print("Step 2/4: Fetching current fundamentals (P/B, PE, ROA)...")
    fund_data = _fetch_fundamentals(list(UNIVERSE))
    fund_available = len(fund_data) > 0
    print(f"  ✓ Got fundamentals for {len(fund_data)}/{len(UNIVERSE)} tickers")
    print()

    # Compute forward returns for every ticker in universe
    print("Step 3/4: Computing forward 6-month returns for every ticker...")
    forward_returns: Dict[str, float] = {}
    for t in UNIVERSE:
        closes = price_data.get(t)
        if not closes:
            continue
        fr = forward_return(closes, formation_dt, exit_dt)
        if fr is not None:
            forward_returns[t] = fr
    print(f"  ✓ Computed forward returns for {len(forward_returns)} tickers")
    print()

    # Compute all signal scores + run backtest for each
    print("Step 4/4: Racing signals...")
    all_stats: Dict[str, Dict] = {}
    signal_picks: Dict[str, List[str]] = {}  # For correlation matrix

    signal_dispatch = {
        "momentum_12_2": lambda t: sig_momentum_12_2(price_data.get(t, []), formation_dt),
        "momentum_6mo":  lambda t: sig_momentum_6mo(price_data.get(t, []), formation_dt),
        "reversal_1mo":  lambda t: sig_reversal_1mo(price_data.get(t, []), formation_dt),
        "above_200sma":  lambda t: sig_above_200sma(price_data.get(t, []), formation_dt),
        "low_beta":      lambda t: sig_low_beta(price_data.get(t, []), spy_closes, formation_dt),
        "low_ivol":      lambda t: sig_low_ivol(price_data.get(t, []), spy_closes, formation_dt),
        "low_pb":        lambda t: sig_low_pb(fund_data.get(t, {})),
        "low_fpe":       lambda t: sig_low_fpe(fund_data.get(t, {})),
        "value_combined":lambda t: sig_value_combined(fund_data.get(t, {})),
        "high_roa":      lambda t: sig_high_roa(fund_data.get(t, {})),
        "bmg_composite": lambda t: sig_bmg_composite(price_data.get(t, []), spy_closes,
                                                     fund_data.get(t, {}), formation_dt),
    }

    signals_to_run = dict(SIGNALS_PRICE_ONLY)
    if fund_available:
        signals_to_run.update(SIGNALS_WITH_FUNDAMENTALS)

    for display_name, key in signals_to_run.items():
        fn = signal_dispatch[key]
        scores = {t: fn(t) for t in UNIVERSE if t in price_data}
        picks = rank_and_pick_top(scores, TOP_N)
        if not picks:
            print(f"  {display_name}: no picks (signal returned None for all tickers)")
            continue
        stats = portfolio_stats(picks, forward_returns, benchmark_return)
        all_stats[display_name] = stats
        signal_picks[display_name] = picks
        print(f"  {display_name}: n={stats['n']}, ret={stats['mean_return']*100:+.2f}%, "
              f"hit={stats['hit_rate']*100:.0f}%")

    # Signal-vs-signal correlation (Jaccard-like: overlap of picks)
    correlations: Dict[Tuple[str, str], float] = {}
    signal_names = list(signal_picks.keys())
    for i, n1 in enumerate(signal_names):
        for n2 in signal_names[i:]:
            p1 = set(signal_picks[n1])
            p2 = set(signal_picks[n2])
            if not p1 or not p2:
                continue
            intersection = len(p1 & p2)
            union = len(p1 | p2)
            correlations[(n1, n2)] = intersection / union if union > 0 else 0.0

    # Render report + write to Obsidian
    body = build_report(
        all_stats=all_stats,
        benchmark_return=benchmark_return,
        formation_dt=formation_dt,
        exit_dt=exit_dt,
        universe_size=len(forward_returns),
        fund_available=fund_available,
        correlations=correlations,
    )
    path = write_job_output("signal_race_backtest", body)
    return (f"wrote {path}\n"
            f"universe: {len(forward_returns)} stocks | benchmark SPY: {benchmark_return*100:+.2f}% | "
            f"signals raced: {len(all_stats)}")


if __name__ == "__main__":
    print(run())
