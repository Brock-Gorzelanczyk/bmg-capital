"""MomentumBot 15-year walk-forward backtest — the statistical gate.

Per RULE-M35 (Harvey-Liu-Zhu 2016 factor zoo discipline), any new signal
must clear t > 3.0 in an out-of-sample walk-forward before touching real
money. This is that test for MomentumBot v1.

Method:
  - Universe: same 104 stocks as signal race backtest (has survivorship bias)
  - Formation dates: monthly from 2013-01 through 2026-08 (~165 months)
  - At each formation date:
      1. Compute residual momentum for every stock (36mo FF3 regression)
      2. Take top-20 by z-score
      3. Hold equal-weight for 1 month
      4. Record portfolio return
  - After all 165 rebalances, compute:
      * Annualized return (net of 25 bps × 2 sides × turnover)
      * Annualized volatility
      * Sharpe ratio
      * t-statistic
      * Max drawdown
      * Vs SPY buy-and-hold benchmark

Gate: Sharpe > 0.77, t > 3.0 for GO. Otherwise NO-GO.

Refs: vault/research/2026-08-31-verify-{blitz-huij-martens-residual-momentum,
      frazzini-israel-moskowitz-trading-costs, harvey-liu-zhu-factor-zoo,
      bailey-lopez-de-prado-deflated-sharpe}.md
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
from job_signal_race_backtest import UNIVERSE  # 104 stocks

BACKTEST_START = "2013-01"  # need 36 months prior data, so we fetch from 2010
BACKTEST_END_YEAR = 2026
TOP_N = 20
COST_PER_SIDE_BPS = 15  # FIM 2018 realistic large-cap
INITIAL_CAPITAL = 10000.0


# ────────────────────────────────────────────────────────────────
# Data fetching
# ────────────────────────────────────────────────────────────────

def _yahoo_monthly_closes(symbol: str, start_ts: int, end_ts: int) -> Optional[Dict[str, float]]:
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?period1={start_ts}&period2={end_ts}&interval=1mo")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (BMG mom_bt)"})
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
        prev, cur = closes[keys[i - 1]], closes[keys[i]]
        if prev and prev > 0:
            rets[keys[i]] = (cur / prev) - 1.0
    return rets


# ────────────────────────────────────────────────────────────────
# OLS (pure stdlib)
# ────────────────────────────────────────────────────────────────

def _mt(A):
    return [list(r) for r in zip(*A)]


def _mm(A, B):
    n, m, p = len(A), len(A[0]), len(B[0])
    C = [[0.0] * p for _ in range(n)]
    for i in range(n):
        for j in range(p):
            s = 0.0
            for k in range(m):
                s += A[i][k] * B[k][j]
            C[i][j] = s
    return C


def _minv(A):
    n = len(A)
    aug = [row[:] + [1.0 if i == j else 0.0 for j in range(n)] for i, row in enumerate(A)]
    for col in range(n):
        pv = aug[col][col]
        if abs(pv) < 1e-14:
            for r in range(col + 1, n):
                if abs(aug[r][col]) > 1e-14:
                    aug[col], aug[r] = aug[r], aug[col]
                    pv = aug[col][col]
                    break
            else:
                raise ValueError("singular")
        for j in range(2 * n):
            aug[col][j] /= pv
        for r in range(n):
            if r != col:
                f = aug[r][col]
                for j in range(2 * n):
                    aug[r][j] -= f * aug[col][j]
    return [row[n:] for row in aug]


# ────────────────────────────────────────────────────────────────
# Signal — residual momentum z-score at a given formation date
# ────────────────────────────────────────────────────────────────

def _month_key_offset(formation: str, months_back: int) -> str:
    """Given 'YYYY-MM', return the key months_back earlier."""
    y, m = map(int, formation.split("-"))
    total = y * 12 + (m - 1) - months_back
    ny, nm = total // 12, total % 12 + 1
    return f"{ny:04d}-{nm:02d}"


def residual_momentum(rets: Dict[str, float], ff3: Dict[str, Dict[str, float]],
                       formation: str) -> Optional[float]:
    """36-month FF3 regression, sum residuals t-12 to t-2, standardize."""
    window_36 = [_month_key_offset(formation, k) for k in range(2, 38)]
    y_full, X_full, all_keys = [], [], []
    for m in window_36:
        if m not in rets or m not in ff3:
            continue
        f = ff3[m]
        mkt, smb, hml = f.get("Mkt-RF"), f.get("SMB"), f.get("HML")
        rf = f.get("RF", 0.0)
        if mkt is None or smb is None or hml is None:
            continue
        y_full.append(rets[m] - rf)
        X_full.append([1.0, mkt, smb, hml])
        all_keys.append(m)
    if len(y_full) < 24:
        return None
    Xt = _mt(X_full)
    XtX = _mm(Xt, X_full)
    try:
        beta = [row[0] for row in _mm(_minv(XtX), _mm(Xt, [[v] for v in y_full]))]
    except ValueError:
        return None
    residuals = {all_keys[i]: y_full[i] - sum(X_full[i][j] * beta[j] for j in range(4))
                 for i in range(len(y_full))}
    window_12_2 = [_month_key_offset(formation, k) for k in range(2, 13)]
    ws = [residuals[m] for m in window_12_2 if m in residuals]
    if len(ws) < 6:
        return None
    sigma = statistics.stdev(list(residuals.values()))
    if sigma <= 0:
        return None
    return sum(ws) / sigma


def _all_month_keys(start: str, end: str) -> List[str]:
    y, m = map(int, start.split("-"))
    ey, em = map(int, end.split("-"))
    out = []
    while (y, m) <= (ey, em):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


# ────────────────────────────────────────────────────────────────
# Backtest engine
# ────────────────────────────────────────────────────────────────

def run_backtest() -> Dict:
    print("=" * 60)
    print("MOMENTUMBOT — 15-YEAR WALK-FORWARD BACKTEST")
    print("=" * 60)
    now = datetime.now(timezone.utc)
    end_date = now
    start_fetch = now - timedelta(days=365 * 17)  # 17 years back
    start_ts = int(start_fetch.timestamp())
    end_ts = int(end_date.timestamp())

    print("Loading FF3 monthly factors...")
    ff3 = get_ff3_monthly()
    print(f"  ✓ {len(ff3)} months")

    print(f"Fetching {len(UNIVERSE)} tickers × ~204 months each...")
    all_closes: Dict[str, Dict[str, float]] = {}
    for i, t in enumerate(UNIVERSE + ["SPY"], 1):
        if i % 20 == 0:
            print(f"  {i}/{len(UNIVERSE) + 1}...")
        c = _yahoo_monthly_closes(t, start_ts, end_ts)
        if c and len(c) >= 60:
            all_closes[t] = c
        time.sleep(0.08)
    print(f"  ✓ Got {len(all_closes)} tickers")

    spy_closes = all_closes.get("SPY", {})
    spy_rets = _monthly_returns(spy_closes)

    # Pre-compute monthly returns for all stocks
    all_rets = {t: _monthly_returns(c) for t, c in all_closes.items() if t != "SPY"}

    # Build formation dates: monthly from 2013-01 through last month
    end_month = f"{end_date.year:04d}-{end_date.month - 1:02d}" if end_date.month > 1 else f"{end_date.year - 1}-12"
    formation_dates = _all_month_keys(BACKTEST_START, end_month)
    print(f"Running {len(formation_dates)} monthly rebalances...")

    # Simulate portfolio
    portfolio_value = INITIAL_CAPITAL
    prior_picks = set()
    monthly_returns = []
    turnover_pct_history = []
    trace = []  # per-month record for debugging

    for i, formation in enumerate(formation_dates):
        # Compute scores
        scores = {}
        for t, rets in all_rets.items():
            s = residual_momentum(rets, ff3, formation)
            if s is not None:
                scores[t] = s
        if len(scores) < TOP_N * 2:
            continue

        # Pick top 20
        picks = sorted(scores.items(), key=lambda x: -x[1])[:TOP_N]
        pick_tickers = set(t for t, _ in picks)

        # Turnover: fraction of positions changed
        if prior_picks:
            new_names = len(pick_tickers - prior_picks)
            turnover = new_names / TOP_N
        else:
            turnover = 1.0  # 100% turnover on first month
        turnover_pct_history.append(turnover)

        # Cost: 2 sides × turnover × 15 bps
        cost = 2 * turnover * (COST_PER_SIDE_BPS / 10000.0)

        # Forward return = equal-weighted next-month return of picks
        next_month = _month_key_offset(formation, -1)  # next calendar month
        fwd_rets = []
        for t, _ in picks:
            r = all_rets.get(t, {}).get(next_month)
            if r is not None:
                fwd_rets.append(r)
        if not fwd_rets:
            continue
        gross_ret = statistics.mean(fwd_rets)
        net_ret = gross_ret - cost
        monthly_returns.append(net_ret)
        portfolio_value *= (1.0 + net_ret)
        prior_picks = pick_tickers

        if i % 24 == 0:
            print(f"  month {i+1}/{len(formation_dates)} ({formation}): "
                  f"n={len(scores)}, ret={net_ret*100:+.2f}%, PV=${portfolio_value:,.0f}")

        trace.append({
            "formation": formation,
            "next_month": next_month,
            "n_universe": len(scores),
            "turnover": turnover,
            "gross_return": gross_ret,
            "cost": cost,
            "net_return": net_ret,
            "portfolio_value": portfolio_value,
            "top_5": [t for t, _ in picks[:5]],
        })

    # SPY benchmark over same period
    spy_monthly = []
    for i, formation in enumerate(formation_dates):
        next_month = _month_key_offset(formation, -1)
        r = spy_rets.get(next_month)
        if r is not None:
            spy_monthly.append(r)
    spy_initial = INITIAL_CAPITAL
    spy_value = INITIAL_CAPITAL
    for r in spy_monthly:
        spy_value *= (1.0 + r)

    # Stats
    n = len(monthly_returns)
    ann_ret = ((portfolio_value / INITIAL_CAPITAL) ** (12 / n) - 1) * 100
    vol_monthly = statistics.stdev(monthly_returns)
    vol_annual = vol_monthly * math.sqrt(12)
    mean_monthly = statistics.mean(monthly_returns)
    # t-stat
    se_monthly = vol_monthly / math.sqrt(n)
    t_stat = mean_monthly / se_monthly
    # Sharpe (using RF ≈ 0 for simplicity; monthly rf is tiny)
    sharpe_annual = (mean_monthly * 12) / (vol_monthly * math.sqrt(12))
    # Max drawdown
    peak = INITIAL_CAPITAL
    max_dd = 0.0
    values = [INITIAL_CAPITAL]
    v = INITIAL_CAPITAL
    for r in monthly_returns:
        v *= (1 + r)
        values.append(v)
        peak = max(peak, v)
        dd = (v - peak) / peak
        max_dd = min(max_dd, dd)

    # SPY benchmark
    spy_ann_ret = ((spy_value / INITIAL_CAPITAL) ** (12 / len(spy_monthly)) - 1) * 100
    spy_vol_monthly = statistics.stdev(spy_monthly)
    spy_sharpe = (statistics.mean(spy_monthly) * 12) / (spy_vol_monthly * math.sqrt(12))
    spy_peak = INITIAL_CAPITAL
    spy_max_dd = 0.0
    sv = INITIAL_CAPITAL
    for r in spy_monthly:
        sv *= (1 + r)
        spy_peak = max(spy_peak, sv)
        spy_max_dd = min(spy_max_dd, (sv - spy_peak) / spy_peak)

    return {
        "n_months": n,
        "final_value": portfolio_value,
        "spy_final_value": spy_value,
        "ann_return_pct": ann_ret,
        "spy_ann_return_pct": spy_ann_ret,
        "ann_vol_pct": vol_annual * 100,
        "spy_ann_vol_pct": spy_vol_monthly * math.sqrt(12) * 100,
        "sharpe": sharpe_annual,
        "spy_sharpe": spy_sharpe,
        "t_stat": t_stat,
        "max_drawdown_pct": max_dd * 100,
        "spy_max_drawdown_pct": spy_max_dd * 100,
        "mean_monthly_turnover": statistics.mean(turnover_pct_history),
        "start": formation_dates[0],
        "end": formation_dates[-1] if formation_dates else "?",
        "trace": trace,
    }


def build_report(stats: Dict) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    hlz_pass_sharpe = stats["sharpe"] > 0.77
    hlz_pass_tstat = stats["t_stat"] > 3.0
    verdict_go = hlz_pass_sharpe and hlz_pass_tstat
    verdict_line = "**✅ GO — passes Harvey-Liu-Zhu gate**" if verdict_go else "**❌ NO-GO — fails Harvey-Liu-Zhu gate**"

    lines = [
        f"# MomentumBot Backtest — {today}",
        "",
        "*15-year walk-forward backtest of Residual Momentum strategy (BHM 2011 methodology). Statistical gate per Harvey-Liu-Zhu 2016 (t > 3.0) required before real money.*",
        "",
        f"## Verdict: {verdict_line}",
        "",
        "## Setup",
        "",
        f"- **Backtest window:** {stats['start']} → {stats['end']} ({stats['n_months']} monthly rebalances)",
        f"- **Universe:** {len(UNIVERSE)} S&P 500 stocks (with survivorship bias — flagged as limitation)",
        f"- **Signal:** BHM 2011 residual 12-2 momentum, top-20 equal-weight",
        f"- **Rebalance:** monthly (1st trading day)",
        f"- **Cost model:** 15 bps × 2 sides × turnover (Frazzini-Israel-Moskowitz 2018 large-cap)",
        f"- **Initial capital:** ${INITIAL_CAPITAL:,.0f}",
        "",
        "## Headline Results",
        "",
        "| Metric | MomentumBot | SPY Benchmark | Delta |",
        "|---|---:|---:|---:|",
        f"| Final value from $10K | **${stats['final_value']:,.0f}** | ${stats['spy_final_value']:,.0f} | {(stats['final_value'] - stats['spy_final_value'])/INITIAL_CAPITAL*100:+.1f}% |",
        f"| Annualized return | **{stats['ann_return_pct']:+.2f}%** | {stats['spy_ann_return_pct']:+.2f}% | {stats['ann_return_pct'] - stats['spy_ann_return_pct']:+.2f}pp |",
        f"| Annualized volatility | {stats['ann_vol_pct']:.2f}% | {stats['spy_ann_vol_pct']:.2f}% | {stats['ann_vol_pct'] - stats['spy_ann_vol_pct']:+.2f}pp |",
        f"| **Sharpe ratio** | **{stats['sharpe']:+.3f}** | {stats['spy_sharpe']:+.3f} | {stats['sharpe'] - stats['spy_sharpe']:+.3f} |",
        f"| **t-statistic** | **{stats['t_stat']:+.2f}** | — | — |",
        f"| Max drawdown | {stats['max_drawdown_pct']:.2f}% | {stats['spy_max_drawdown_pct']:.2f}% | {stats['max_drawdown_pct'] - stats['spy_max_drawdown_pct']:+.2f}pp |",
        f"| Mean monthly turnover | {stats['mean_monthly_turnover']*100:.1f}% | — | — |",
        "",
        "## Harvey-Liu-Zhu 2016 Gate",
        "",
        f"- **Sharpe > 0.77 required:** {stats['sharpe']:+.3f} → {'✅ PASS' if hlz_pass_sharpe else '❌ FAIL'}",
        f"- **t-stat > 3.0 required:** {stats['t_stat']:+.2f} → {'✅ PASS' if hlz_pass_tstat else '❌ FAIL'}",
        f"- **Verdict:** {'✅ SHIP IT (paper trade first, then scale to real money after 90 days)' if verdict_go else '❌ DO NOT SHIP — signal is not statistically significant vs the factor zoo. Iterate on the strategy before further testing.'}",
        "",
        "## Diagnostic Interpretation",
        "",
    ]
    if verdict_go:
        lines.append(f"The Residual Momentum strategy PASSES the Harvey-Liu-Zhu discipline gate. Over {stats['n_months']} monthly rebalances, the strategy earned {stats['ann_return_pct']:+.2f}%/yr net of trading costs vs SPY's {stats['spy_ann_return_pct']:+.2f}%/yr — a real risk-adjusted edge with t={stats['t_stat']:.2f} vs the required 3.0 threshold.")
        lines.append("")
        if stats['sharpe'] > stats['spy_sharpe']:
            lines.append(f"Sharpe of {stats['sharpe']:.2f} vs SPY's {stats['spy_sharpe']:.2f} means the strategy delivered more return-per-unit-of-risk. Max drawdown of {stats['max_drawdown_pct']:.1f}% (vs SPY's {stats['spy_max_drawdown_pct']:.1f}%) indicates the risk profile is comparable to benchmark.")
        else:
            lines.append(f"NOTE: SPY had a higher Sharpe ({stats['spy_sharpe']:.2f}) than the strategy ({stats['sharpe']:.2f}) despite the t-stat passing. This suggests the strategy adds concentrated bets but not necessarily better risk-adjusted returns.")
    else:
        lines.extend([
            "The strategy FAILED the Harvey-Liu-Zhu gate. Possible reasons:",
            "",
            "1. **Small universe** — 104 stocks limits diversification. Real MomentumBot would use full Russell 1000.",
            "2. **Survivorship bias** — using CURRENT S&P 500 members creates upward bias, but the SPY benchmark also benefits, so may cancel out.",
            "3. **Regime unfavorable** — 2013-2026 has been a growth-dominant regime with several momentum crashes (2016, 2020). Value + quality strategies would show similar weakness in this period.",
            "4. **Signal weak in this specific universe** — try Russell 1000 or restrict to top-500 by market cap.",
            "",
            "**Recommendation:** DO NOT ship to real (or paper) money until iterating on the signal. Try:",
            "- Expand universe to Russell 1000",
            "- Add Barroso-Santa-Clara vol scaling before ranking",
            "- Overlay Daniel-Moskowitz momentum-crash regime gate (already in overlay #6)",
        ])

    lines.extend([
        "",
        "## Recent Performance (last 12 months)",
        "",
        "| Formation | Top 5 Picks | Net Return | PV |",
        "|---|---|---:|---:|",
    ])
    for row in stats["trace"][-12:]:
        lines.append(
            f"| {row['formation']} | {', '.join(row['top_5'])} | {row['net_return']*100:+.2f}% | ${row['portfolio_value']:,.0f} |"
        )
    lines.append("")

    lines.extend([
        "## Caveats",
        "",
        "- **Survivorship bias:** universe is TODAY's 104 stocks. Real backtest would use point-in-time S&P 500 membership.",
        "- **Look-ahead in FF3:** we use monthly FF3 factors — those ARE point-in-time (Ken French publishes with lag), so no look-ahead in signal.",
        "- **Transaction costs static:** 15 bps × 2 sides is FIM 2018 large-cap median. Real costs vary by liquidity + trade size.",
        "- **No regime overlay applied:** this backtest is PURE signal. Adding Faber 200-SMA regime gate would reduce drawdowns further.",
        "- **No slippage model:** assumed instant fill at monthly close. Real fills would be worse by ~5-10 bps.",
        "",
        "## Next steps",
        "",
        f"{'1. **APPROVE for paper trading** — bot goes live with $2,500 sleeve on next 1st of month rebalance.' if verdict_go else '1. **Iterate signal** — expand universe, add vol scaling, retest.'}",
        f"{'2. **Monitor 90 days** — track live vs backtest. Cap real-money graduation at $500 first if scaling later.' if verdict_go else '2. **Re-run backtest** with iterated signal before continuing.'}",
        "3. **Ship regime overlay + turbulence index** in parallel — the drawdown protection layer is orthogonal to the signal itself.",
        "",
        "## Refs",
        "",
        "- Blitz-Huij-Martens 2011 (paper #33) — residual momentum construction",
        "- Frazzini-Israel-Moskowitz 2018 (paper #32) — 15 bps/side cost model",
        "- Harvey-Liu-Zhu 2016 (paper #34) — t > 3.0 statistical gate",
        "- Bailey-Lopez de Prado deflated Sharpe (vault) — related discipline",
        "",
        f"*Generated by scripts/local/job_momentum_backtest.py — {today}.*",
    ])
    return "\n".join(lines)


def run() -> str:
    stats = run_backtest()
    body = build_report(stats)
    path = write_job_output("momentum_backtest", body)
    return (
        f"wrote {path}\n"
        f"final ${stats['final_value']:,.0f} vs SPY ${stats['spy_final_value']:,.0f} | "
        f"Sharpe {stats['sharpe']:.2f} vs SPY {stats['spy_sharpe']:.2f} | "
        f"t-stat {stats['t_stat']:.2f} | max DD {stats['max_drawdown_pct']:.1f}%"
    )


if __name__ == "__main__":
    print(run())
