"""Financial Turbulence Index — Phase 1 of regime overlay.

Kritzman & Li 2010 formalization (adopted in KPT 2012 vault paper #31).
Daily Mahalanobis distance of a cross-asset return vector from its historical
mean, using a rolling covariance matrix as the metric.

Higher turbulence = market moving in "unusual" patterns = statistically high
probability of regime shift or drawdown.

BMG uses this as a defensive overlay:
  - Turbulence > 90th percentile of trailing 5yr → HIGH ALERT
  - Reduce all sleeve sizings by 50%
  - Deploy Regime Overlay sleeve into GLD/TLT/SH hedges

Baskets tested (all Yahoo tickers, free):
  - SPY (US equity)
  - TLT (long treasuries)
  - GLD (gold)
  - UUP (dollar)
  - ^VIX (volatility itself)

Method:
  1. Fetch daily returns for the 5-asset basket over last 5 years
  2. Compute rolling 252-day mean vector μ and covariance matrix Σ
  3. For each day t, compute r_t (5-vector of that day's returns)
  4. Turbulence_t = (r_t − μ)ᵀ Σ⁻¹ (r_t − μ)  [Mahalanobis distance²]
  5. Compare today's value to 5yr percentile distribution
  6. Alert if > 90th percentile

Pure stdlib (5x5 matrix ops fast). No numpy/pandas.

Ref: vault/research/2026-08-31-verify-kritzman-page-turkington-regime-shifts.md
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

BASKET = ["SPY", "TLT", "GLD", "UUP", "^VIX"]
LOOKBACK_DAYS = 252  # for μ, Σ estimation
PERCENTILE_ALERT = 90.0  # KPT threshold


# ────────────────────────────────────────────────────────────────
# Data
# ────────────────────────────────────────────────────────────────

def _yahoo_daily_closes(symbol: str, days_back: int = 400) -> Optional[List[Tuple[int, float]]]:
    end_ts = int(datetime.now(timezone.utc).timestamp())
    start_ts = int((datetime.now(timezone.utc) - timedelta(days=days_back)).timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?period1={start_ts}&period2={end_ts}&interval=1d")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (BMG turb)"})
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


# ────────────────────────────────────────────────────────────────
# Matrix ops (5x5)
# ────────────────────────────────────────────────────────────────

def _mat_inverse(A):
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
                # Add tiny ridge for numerical stability
                for i in range(n):
                    aug[i][i] += 1e-6
                pv = aug[col][col]
        for j in range(2 * n):
            aug[col][j] /= pv
        for r in range(n):
            if r != col:
                f = aug[r][col]
                for j in range(2 * n):
                    aug[r][j] -= f * aug[col][j]
    return [row[n:] for row in aug]


def _mv_mul(A, v):
    """Matrix-vector multiply."""
    return [sum(A[i][j] * v[j] for j in range(len(v))) for i in range(len(A))]


def _dot(a, b):
    return sum(a[i] * b[i] for i in range(len(a)))


def _compute_cov(returns_by_asset: List[List[float]]) -> List[List[float]]:
    """Sample covariance matrix from k×n returns (k assets, n obs)."""
    k = len(returns_by_asset)
    n = len(returns_by_asset[0])
    means = [sum(r) / n for r in returns_by_asset]
    cov = [[0.0] * k for _ in range(k)]
    for i in range(k):
        for j in range(i, k):
            s = sum((returns_by_asset[i][t] - means[i]) * (returns_by_asset[j][t] - means[j])
                    for t in range(n))
            cov[i][j] = cov[j][i] = s / (n - 1) if n > 1 else 0.0
    return cov


def _turbulence(r_t: List[float], mean: List[float], cov_inv: List[List[float]]) -> float:
    """Mahalanobis distance squared."""
    d = [r_t[i] - mean[i] for i in range(len(r_t))]
    return _dot(d, _mv_mul(cov_inv, d))


# ────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────

def run() -> str:
    print("=" * 60)
    print("FINANCIAL TURBULENCE INDEX — Kritzman-Li")
    print("=" * 60)
    now = datetime.now(timezone.utc)

    # Fetch 5yr of daily closes for each basket asset
    print(f"Fetching {len(BASKET)} basket assets, 5 years each...")
    closes_by_asset = {}
    for a in BASKET:
        cl = _yahoo_daily_closes(a, days_back=365 * 5 + 30)
        if not cl:
            return f"ERROR: could not fetch {a}"
        closes_by_asset[a] = cl
        time.sleep(0.1)

    # Align to common DATES (not timestamps — Yahoo returns slightly different
    # unix times per asset due to exchange timezone / opening auction differences).
    print("Aligning dates across basket...")
    date_sets = []
    date_maps_per_asset = {}
    for a, cl in closes_by_asset.items():
        m = {}
        for t, c in cl:
            d = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")
            m[d] = (t, c)
        date_maps_per_asset[a] = m
        date_sets.append(set(m.keys()))
    common_dates = sorted(set.intersection(*date_sets))
    print(f"  ✓ {len(common_dates)} common trading days")

    # Convert to closes per day + track timestamps for last date reporting
    closes_aligned = {}
    common_ts = []
    for d in common_dates:
        # Pick any asset's timestamp as the canonical (they're the same day)
        common_ts.append(date_maps_per_asset[BASKET[0]][d][0])
    for a in BASKET:
        closes_aligned[a] = [date_maps_per_asset[a][d][1] for d in common_dates]

    # Compute daily returns (log returns for stability)
    returns_by_asset = {}
    for a, cl in closes_aligned.items():
        rets = [math.log(cl[i] / cl[i - 1]) for i in range(1, len(cl)) if cl[i - 1] > 0]
        returns_by_asset[a] = rets
    n_days = len(returns_by_asset[BASKET[0]])
    print(f"  ✓ {n_days} daily return observations per asset")

    # For each day t (starting after LOOKBACK), compute turbulence using
    # rolling 252-day window ending at t-1 (no look-ahead)
    print(f"Computing daily turbulence (rolling {LOOKBACK_DAYS}-day window)...")
    turb_series = []
    for t in range(LOOKBACK_DAYS, n_days):
        # Rolling window t-LOOKBACK to t-1
        window_returns = [returns_by_asset[a][t - LOOKBACK_DAYS:t] for a in BASKET]
        means = [sum(w) / len(w) for w in window_returns]
        cov = _compute_cov(window_returns)
        try:
            cov_inv = _mat_inverse(cov)
        except Exception:
            continue
        r_t = [returns_by_asset[a][t] for a in BASKET]
        turb = _turbulence(r_t, means, cov_inv)
        turb_series.append((common_ts[t + 1], turb))  # +1 because returns are shifted

    if not turb_series:
        return "ERROR: could not compute any turbulence values"

    # Latest reading
    latest_ts, latest_turb = turb_series[-1]
    latest_dt = datetime.fromtimestamp(latest_ts, tz=timezone.utc)

    # Percentiles from all values in series
    all_values = [v for _, v in turb_series]
    p50 = statistics.median(all_values)
    p90 = statistics.quantiles(all_values, n=10)[8]  # 90th
    p95 = statistics.quantiles(all_values, n=20)[18]  # 95th
    p99 = sorted(all_values)[int(len(all_values) * 0.99)]

    # Where does today rank?
    rank = sum(1 for v in all_values if v <= latest_turb) / len(all_values) * 100

    # Alert?
    alert_level = "🟢 NORMAL"
    if latest_turb > p99:
        alert_level = "🚨 EXTREME (>99th %ile) — CRISIS-LEVEL"
    elif latest_turb > p95:
        alert_level = "🔴 HIGH (>95th %ile)"
    elif latest_turb > p90:
        alert_level = "🟡 ELEVATED (>90th %ile)"

    # Recent trend — last 10 readings
    recent = turb_series[-10:]

    # Build report
    today_str = now.strftime("%Y-%m-%d")
    lines = [
        f"# Turbulence Check — {today_str}",
        "",
        f"*Kritzman-Li financial turbulence index. Phase 1 regime overlay per KPT 2012 (vault paper #31).*",
        "",
        f"## 🎯 Current Reading: {alert_level}",
        "",
        f"- **Latest value:** {latest_turb:.2f}",
        f"- **Latest date:** {latest_dt.strftime('%Y-%m-%d')}",
        f"- **Rank in 5yr distribution:** {rank:.1f}th percentile",
        f"- **Basket:** {', '.join(BASKET)}",
        "",
        "## Percentile thresholds (5-year rolling)",
        "",
        f"| Percentile | Value | Alert |",
        f"|---:|---:|---|",
        f"| 50th (median) | {p50:.2f} | Normal |",
        f"| 90th | {p90:.2f} | 🟡 Watch |",
        f"| 95th | {p95:.2f} | 🔴 High |",
        f"| 99th | {p99:.2f} | 🚨 Crisis |",
        "",
        "## Last 10 daily readings",
        "",
        "| Date | Turbulence | Level |",
        "|---|---:|:---:|",
    ]
    for ts, v in recent:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        marker = "🚨" if v > p99 else "🔴" if v > p95 else "🟡" if v > p90 else "🟢"
        lines.append(f"| {dt} | {v:.2f} | {marker} |")
    lines.append("")

    # Action recommendations
    lines.extend([
        "## BMG Sleeve Actions",
        "",
    ])
    if latest_turb > p95:
        lines.extend([
            "🚨 **HIGH TURBULENCE — DEFENSIVE POSTURE**",
            "",
            "- Reduce Confluence sleeve position sizes by 50%",
            "- Reduce MomentumBot sleeve by 50% (or pause new buys)",
            "- **DEPLOY Regime Overlay sleeve** into GLD (35%) + TLT (35%) + SH (30%)",
            "- Cancel any pending BUY orders across bots",
            "- Consider raising cash further",
        ])
    elif latest_turb > p90:
        lines.extend([
            "🟡 **ELEVATED TURBULENCE — CAUTION**",
            "",
            "- Do NOT increase sleeve sizes",
            "- Do NOT add new speculative positions",
            "- Continue monitoring daily",
            "- If turbulence persists >5 days at this level → escalate to HIGH-TURBULENCE response",
        ])
    else:
        lines.extend([
            "🟢 **NORMAL — proceed with framework**",
            "",
            "- No defensive adjustments needed",
            "- Continue MomentumBot monthly rebalance schedule",
            "- Continue Confluence framework execution",
            "- Regime Overlay sleeve remains in cash (dry powder)",
        ])

    lines.extend([
        "",
        "## Interpretation Guide",
        "",
        "Turbulence measures how UNUSUAL today's cross-asset return pattern is vs history. It goes up when:",
        "- Assets that usually move together diverge dramatically",
        "- Volatility spikes across MULTIPLE asset classes",
        "- Cross-asset correlations break down (a hallmark of regime shift)",
        "",
        "KPT 2012 showed that turbulence spikes >90th %ile PRECEDE (not lag) most major drawdowns.",
        "It's an early warning system, not a coincident indicator.",
        "",
        "## Historical spikes (for context)",
        "",
        "Note: this backtest sample is only last 5 years. Historical events that would show as spikes in a longer series:",
        "- Oct 2008 (Lehman) — extreme",
        "- Aug 2011 (US downgrade) — high",
        "- Mar 2020 (COVID) — extreme",
        "- Oct 2022 (rate shock) — high",
        "",
        "## Refs",
        "",
        "- `vault/research/2026-08-31-verify-kritzman-page-turkington-regime-shifts.md`",
        "- `vault/research/2026-08-31-verify-hamilton-markov-switching.md`",
        "- `vault/research/2026-08-31-verify-ang-bekaert-international-regimes.md`",
        "",
        f"*Generated by scripts/local/job_turbulence_check.py — {today_str}. Add to schedule.yaml for daily runs.*",
    ])

    body = "\n".join(lines)
    path = write_job_output("turbulence_check", body)
    return (
        f"wrote {path}\n"
        f"turbulence: {latest_turb:.2f} (rank {rank:.1f}%ile) → {alert_level}\n"
        f"thresholds: p90={p90:.2f}, p95={p95:.2f}, p99={p99:.2f}"
    )


if __name__ == "__main__":
    print(run())
