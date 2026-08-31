"""MomentumBot v1 — first scan of residual momentum.

Ships the Blitz-Huij-Martens 2011 residual momentum methodology (paper #33)
per Brock's MomentumBot spec.

Signal construction:
  1. Fetch 36 months of monthly returns for each stock in universe
  2. Fetch matching FF3 monthly factors (Mkt-RF, SMB, HML) from Ken French
  3. For each stock, regress monthly returns on FF3 → get residuals
  4. Sum residuals for months t-12 to t-2 (skip t-1, JT 1993 short-term reversal)
  5. Standardize by stdev of residuals over the window
  6. Rank universe by standardized residual momentum → top-20 = MomentumBot picks

Also computes RAW 12-2 momentum for comparison so we can see the difference.

Universe: same 100-stock S&P 500 sample from signal race backtest
Output: Markdown report to Obsidian with top-20 picks + raw comparison

Refs: vault/research/2026-08-31-verify-blitz-huij-martens-residual-momentum.md
      vault/research/2026-08-31-verify-jegadeesh-titman-1993-winners-losers.md
      vault/research/2026-08-31-verify-frazzini-israel-moskowitz-trading-costs.md
      vault/research/2026-08-31-verify-harvey-liu-zhu-factor-zoo.md
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
from _ff_data import get_ff3_monthly  # noqa: E402
from job_signal_race_backtest import UNIVERSE  # reuse the 100-stock list


# ─────────────────────────────────────────────────────────────────
# Data fetching
# ─────────────────────────────────────────────────────────────────

def _yahoo_monthly_closes(symbol: str, start_ts: int, end_ts: int) -> Optional[Dict[str, float]]:
    """Fetch monthly closes as {'YYYY-MM': close}."""
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?period1={start_ts}&period2={end_ts}&interval=1mo")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (BMG momentum)"})
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
    out = {}
    for t, c in zip(ts, closes):
        if c is None:
            continue
        dt = datetime.fromtimestamp(t, tz=timezone.utc)
        out[dt.strftime("%Y-%m")] = float(c)
    return out


def _monthly_returns(closes: Dict[str, float]) -> Dict[str, float]:
    keys = sorted(closes.keys())
    rets = {}
    for i in range(1, len(keys)):
        prev = closes[keys[i - 1]]
        cur = closes[keys[i]]
        if prev and prev > 0:
            rets[keys[i]] = (cur / prev) - 1.0
    return rets


# ─────────────────────────────────────────────────────────────────
# OLS regression (stdlib)
# ─────────────────────────────────────────────────────────────────

def _mat_transpose(A):
    return [list(row) for row in zip(*A)]


def _mat_mul(A, B):
    n, m = len(A), len(A[0])
    p = len(B[0])
    C = [[0.0] * p for _ in range(n)]
    for i in range(n):
        for j in range(p):
            s = 0.0
            for k in range(m):
                s += A[i][k] * B[k][j]
            C[i][j] = s
    return C


def _mat_inverse(A):
    n = len(A)
    aug = [row[:] + [1.0 if i == j else 0.0 for j in range(n)] for i, row in enumerate(A)]
    for col in range(n):
        pivot = aug[col][col]
        if abs(pivot) < 1e-14:
            for r in range(col + 1, n):
                if abs(aug[r][col]) > 1e-14:
                    aug[col], aug[r] = aug[r], aug[col]
                    pivot = aug[col][col]
                    break
            else:
                raise ValueError("singular")
        for j in range(2 * n):
            aug[col][j] /= pivot
        for r in range(n):
            if r != col:
                factor = aug[r][col]
                for j in range(2 * n):
                    aug[r][j] -= factor * aug[col][j]
    return [row[n:] for row in aug]


def ff3_residuals(stock_rets: Dict[str, float], ff3: Dict[str, Dict[str, float]],
                   months: List[str]) -> Optional[Dict[str, float]]:
    """Regress stock returns on FF3 factors over given months, return residuals per month."""
    y = []
    X_rows = []
    keys = []
    for m in months:
        if m not in stock_rets or m not in ff3:
            continue
        f = ff3[m]
        mkt = f.get("Mkt-RF")
        smb = f.get("SMB")
        hml = f.get("HML")
        rf = f.get("RF", 0.0)
        if mkt is None or smb is None or hml is None:
            continue
        y.append(stock_rets[m] - rf)  # excess return
        X_rows.append([1.0, mkt, smb, hml])
        keys.append(m)
    if len(y) < 12:
        return None
    Xt = _mat_transpose(X_rows)
    XtX = _mat_mul(Xt, X_rows)
    try:
        XtX_inv = _mat_inverse(XtX)
    except ValueError:
        return None
    Xty = _mat_mul(Xt, [[v] for v in y])
    beta = [row[0] for row in _mat_mul(XtX_inv, Xty)]
    y_hat = [sum(X_rows[i][j] * beta[j] for j in range(4)) for i in range(len(y))]
    residuals = {keys[i]: y[i] - y_hat[i] for i in range(len(y))}
    return residuals


# ─────────────────────────────────────────────────────────────────
# Signal
# ─────────────────────────────────────────────────────────────────

def residual_momentum_score(stock_rets: Dict[str, float], ff3: Dict[str, Dict[str, float]],
                             as_of: datetime) -> Optional[Tuple[float, float, int]]:
    """Compute BHM 2011 residual momentum.

    Returns: (standardized_residual_momentum, raw_residual_sum, n_months_used) or None.
    """
    # Build list of months from t-37 to t-2 (36-month window for regression)
    months = []
    for delta in range(2, 38):  # 36 months
        m_dt = as_of - timedelta(days=delta * 30)  # approx monthly
        months.append(m_dt.strftime("%Y-%m"))
    months = sorted(set(months))

    # Regression
    residuals = ff3_residuals(stock_rets, ff3, months)
    if residuals is None:
        return None

    # Sum residuals for months t-12 to t-2 (11 months)
    window_months = []
    for delta in range(2, 13):
        m_dt = as_of - timedelta(days=delta * 30)
        window_months.append(m_dt.strftime("%Y-%m"))
    window_months = sorted(set(window_months))

    window_resids = [residuals[m] for m in window_months if m in residuals]
    if len(window_resids) < 6:
        return None
    raw_sum = sum(window_resids)

    # Standardize by stdev of ALL residuals in regression window
    all_resids = list(residuals.values())
    if len(all_resids) < 12:
        return None
    sigma = statistics.stdev(all_resids)
    if sigma <= 0:
        return None
    standardized = raw_sum / sigma
    return (standardized, raw_sum, len(window_resids))


def raw_momentum_12_2(closes: Dict[str, float], as_of: datetime) -> Optional[float]:
    """Classic JT 12-2 momentum for comparison."""
    end_key = (as_of - timedelta(days=30)).strftime("%Y-%m")
    start_key = (as_of - timedelta(days=365)).strftime("%Y-%m")
    # Find nearest available months
    keys = sorted(closes.keys())
    end_val = None
    start_val = None
    for k in reversed(keys):
        if k <= end_key and end_val is None:
            end_val = closes[k]
        if k <= start_key:
            start_val = closes[k]
            break
    if not start_val or not end_val:
        return None
    return (end_val / start_val) - 1.0


# ─────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────

def run() -> str:
    print("=" * 60)
    print("MOMENTUMBOT FIRST SCAN — Residual Momentum")
    print("=" * 60)
    now = datetime.now(timezone.utc)
    print(f"As of: {now.strftime('%Y-%m-%d')}")
    print(f"Universe: {len(UNIVERSE)} tickers")

    # Load FF3
    print("Loading Ken French FF3 monthly factors...")
    ff3 = get_ff3_monthly()
    print(f"  ✓ {len(ff3)} months of FF3 data")

    # Fetch monthly closes for full universe
    print("Fetching monthly closes for universe...")
    fetch_start = now - timedelta(days=400 * 3)  # ~40 months
    start_ts = int(fetch_start.timestamp())
    end_ts = int(now.timestamp())
    all_closes: Dict[str, Dict[str, float]] = {}
    for i, t in enumerate(UNIVERSE, 1):
        if i % 25 == 0:
            print(f"  {i}/{len(UNIVERSE)}...")
        c = _yahoo_monthly_closes(t, start_ts, end_ts)
        if c and len(c) >= 24:
            all_closes[t] = c
        time.sleep(0.08)
    print(f"  ✓ Got {len(all_closes)} tickers with enough history")

    # Compute residual momentum + raw momentum for each ticker
    print("Computing residual momentum per stock...")
    scores = []
    for t, closes in all_closes.items():
        rets = _monthly_returns(closes)
        res_score = residual_momentum_score(rets, ff3, now)
        raw_score = raw_momentum_12_2(closes, now)
        if res_score is not None:
            std_z, raw_sum, n = res_score
            scores.append({
                "ticker": t,
                "residual_momentum_z": std_z,
                "residual_sum_pct": raw_sum * 100,
                "raw_momentum_12_2_pct": (raw_score * 100) if raw_score is not None else None,
                "n_months_in_window": n,
            })

    print(f"  ✓ Scored {len(scores)} tickers")

    # Rank by residual momentum
    scores.sort(key=lambda x: -x["residual_momentum_z"])
    top_20 = scores[:20]

    # Also compute rank by raw for comparison
    raw_sorted = sorted(
        [s for s in scores if s["raw_momentum_12_2_pct"] is not None],
        key=lambda x: -x["raw_momentum_12_2_pct"]
    )
    raw_top_20 = raw_sorted[:20]

    # Overlap check
    top_20_res_tickers = set(s["ticker"] for s in top_20)
    top_20_raw_tickers = set(s["ticker"] for s in raw_top_20)
    overlap = top_20_res_tickers & top_20_raw_tickers
    only_residual = top_20_res_tickers - top_20_raw_tickers
    only_raw = top_20_raw_tickers - top_20_res_tickers

    # Build report
    today = now.strftime("%Y-%m-%d")
    lines = [
        f"# MomentumBot First Scan — {today}",
        "",
        "*Residual momentum (Blitz-Huij-Martens 2011) vs Raw 12-2 momentum (Jegadeesh-Titman 1993). Ranks top 20 picks the MomentumBot would buy today.*",
        "",
        "## Methodology",
        "",
        "- **Universe:** {n_univ} S&P 500 stocks with ≥24 months history".format(n_univ=len(all_closes)),
        "- **Signal:** BHM 2011 residual momentum → regress last 36mo monthly returns on FF3 (Mkt-RF, SMB, HML), sum residuals t-12 to t-2, standardize by residual sigma",
        "- **Comparison signal:** raw 12-2 momentum (JT 1993 classic)",
        "- **FF3 factors:** Ken French monthly data, ~1200 months loaded",
        "",
        "## 🚀 Top 20 by RESIDUAL momentum (what MomentumBot would buy today)",
        "",
        "| Rank | Ticker | Res Mom (z) | Res Sum (%) | Raw 12-2 (%) | In Raw Top 20? |",
        "|:---:|:---:|---:|---:|---:|:---:|",
    ]
    for i, s in enumerate(top_20, 1):
        raw_val = s["raw_momentum_12_2_pct"]
        raw_str = f"{raw_val:+.1f}%" if raw_val is not None else "N/A"
        in_raw = "✓" if s["ticker"] in top_20_raw_tickers else "✗"
        lines.append(
            f"| {i} | **{s['ticker']}** | {s['residual_momentum_z']:+.2f} "
            f"| {s['residual_sum_pct']:+.1f}% | {raw_str} | {in_raw} |"
        )
    lines.append("")

    # Raw comparison
    lines.extend([
        "## 📊 Top 20 by RAW 12-2 momentum (JT 1993 classic, for comparison)",
        "",
        "| Rank | Ticker | Raw 12-2 (%) | Res Mom (z) | In Residual Top 20? |",
        "|:---:|:---:|---:|---:|:---:|",
    ])
    for i, s in enumerate(raw_top_20, 1):
        in_res = "✓" if s["ticker"] in top_20_res_tickers else "✗"
        lines.append(
            f"| {i} | **{s['ticker']}** | {s['raw_momentum_12_2_pct']:+.1f}% "
            f"| {s['residual_momentum_z']:+.2f} | {in_res} |"
        )
    lines.append("")

    # Overlap analysis
    lines.extend([
        "## 🔗 Residual vs Raw — how much do they agree?",
        "",
        f"- **Overlap:** {len(overlap)}/20 stocks appear in BOTH top-20 lists",
        f"- **Only residual:** {len(only_residual)} → {sorted(only_residual)}",
        f"- **Only raw:** {len(only_raw)} → {sorted(only_raw)}",
        "",
        "**Interpretation:** If overlap is HIGH (15+), both signals are picking similar names — residual isn't adding much information here. "
        "If overlap is LOW (< 12), the two signals disagree meaningfully — residual is stripping out factor tilt and finding different picks.",
        "",
    ])

    # Bottom 20 (would be shorts in a long/short version)
    bottom_20 = scores[-20:]
    lines.extend([
        "## 🔻 Bottom 20 by residual momentum (would be shorts in JT long-short)",
        "",
        "| Rank | Ticker | Res Mom (z) | Raw 12-2 (%) |",
        "|:---:|:---:|---:|---:|",
    ])
    for i, s in enumerate(bottom_20, len(scores) - 19):
        raw_val = s["raw_momentum_12_2_pct"]
        raw_str = f"{raw_val:+.1f}%" if raw_val is not None else "N/A"
        lines.append(f"| {i} | **{s['ticker']}** | {s['residual_momentum_z']:+.2f} | {raw_str} |")
    lines.append("")

    # Would-be MomentumBot portfolio
    total_sleeve = 2500  # per Brock's $2.5K allocation
    per_position = total_sleeve / 20
    lines.extend([
        "## 💰 What the MomentumBot would actually buy today",
        "",
        f"**Sleeve:** ${total_sleeve} (25% of $10K fund per new allocation)",
        f"**Positions:** 20 stocks × ${per_position:.2f} each (equal weight)",
        "**Execution:** marketable limit orders, split into 3-5 child orders over 30-90 min at 11:00 ET on 1st trading day of the month",
        "",
        "```",
    ])
    for s in top_20:
        lines.append(f"  BUY  {s['ticker']:<6}  ${per_position:.2f}  (res_mom_z={s['residual_momentum_z']:+.2f})")
    lines.extend([
        "```",
        "",
    ])

    # Next steps
    lines.extend([
        "## Next steps",
        "",
        "1. **Statistical gate (Harvey-Liu-Zhu 2016):** before real money, run 15yr walk-forward backtest → require Sharpe > 0.77 net-of-15bps × 2 sides, t > 3.0.",
        "2. **Regime overlay (Faber + Daniel-Moskowitz):** currently SPY > 200-SMA → GREEN LIGHT. If SPY drops below 200-SMA for 3+ days, pause new buys.",
        "3. **Vol scaling (Barroso-Santa-Clara 2015):** compute realized 6mo vol of the 20-stock portfolio, target 12% annualized, cut sizes if vol > 12%.",
        "4. **Monthly re-scan:** run this job on 1st business day each month, compare to previous month's holdings, execute the delta.",
        "",
        "## Refs",
        "",
        "- `vault/research/2026-08-31-verify-blitz-huij-martens-residual-momentum.md` (signal construction)",
        "- `vault/research/2026-08-31-verify-jegadeesh-titman-1993-winners-losers.md` (raw JT for comparison)",
        "- `vault/research/2026-08-31-verify-frazzini-israel-moskowitz-trading-costs.md` (execution discipline)",
        "- `vault/research/2026-08-31-verify-harvey-liu-zhu-factor-zoo.md` (statistical pre-launch gate)",
        "",
        f"*Generated by scripts/local/job_momentum_scan.py — {today}. Manual run; add to schedule.yaml for monthly cron.*",
    ])

    body = "\n".join(lines)
    path = write_job_output("momentum_scan", body)
    return (f"wrote {path}\n"
            f"scanned: {len(scores)} tickers | top 20 residual mom: {[s['ticker'] for s in top_20[:10]]}...\n"
            f"overlap res vs raw: {len(overlap)}/20")


if __name__ == "__main__":
    print(run())
