"""FF3/FF4 alpha calculator — the honest edge measurement.

For every closed BMG confluence pick, compute the pick's monthly return
series over its hold period, join to Ken French's free FF3+UMD factors,
run OLS regression, and report FF3-α, FF4-α with t-stats.

Also aggregates across all closed picks to give a fund-wide alpha.

Zero cost: Ken French data is free from Dartmouth, Yahoo Finance closes
are free, everything computed in pure stdlib (no numpy/pandas).

Writes to Obsidian at:
  context/local-jobs/YYYY-MM-DD-ff4_alpha_calc.md

Ref: vault/research/2026-08-31-verify-fama-french-3-factor.md (RULE-M13,M14,M15,M16)
     vault/research/2026-08-31-verify-carhart-4-factor.md (RULE-M17-M20)

Not scheduled by default — run manually first:
  python3 scripts/local/job_ff4_alpha_calc.py
If useful, add to schedule.yaml (weekly, Sundays).
"""
from __future__ import annotations

import json
import math
import statistics
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

HERE = Path(__file__).parent.resolve()
sys.path.insert(0, str(HERE))
from _bmg_api import get_client, BMGApiError  # noqa: E402
from _obsidian import write_job_output  # noqa: E402
from _ff_data import get_ff4_monthly  # noqa: E402


# ─────────────────────────────────────────────────────────────────
# Yahoo Finance monthly closes
# ─────────────────────────────────────────────────────────────────

def _yahoo_monthly_closes(symbol: str, start_dt: datetime, end_dt: datetime) -> Dict[str, float]:
    """Fetch monthly closes from Yahoo Finance. Returns {YYYY-MM: close_price}."""
    start_ts = int(start_dt.timestamp())
    end_ts = int(end_dt.timestamp())
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        f"?period1={start_ts}&period2={end_ts}&interval=1mo"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (BMG ff_alpha)"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, OSError):
        return {}

    result = data.get("chart", {}).get("result", [])
    if not result:
        return {}
    r = result[0]
    timestamps = r.get("timestamp", []) or []
    closes = (r.get("indicators", {}).get("quote", [{}])[0].get("close", [])) or []
    out: Dict[str, float] = {}
    for ts, c in zip(timestamps, closes):
        if c is None:
            continue
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        key = dt.strftime("%Y-%m")
        out[key] = float(c)
    return out


def _monthly_returns(closes: Dict[str, float]) -> Dict[str, float]:
    """Convert monthly close prices into monthly returns."""
    keys = sorted(closes.keys())
    rets: Dict[str, float] = {}
    for i in range(1, len(keys)):
        prev = closes[keys[i - 1]]
        cur = closes[keys[i]]
        if prev and prev > 0:
            rets[keys[i]] = (cur / prev) - 1.0
    return rets


# ─────────────────────────────────────────────────────────────────
# OLS regression in pure stdlib
# ─────────────────────────────────────────────────────────────────

def _mat_transpose(A: List[List[float]]) -> List[List[float]]:
    return [list(row) for row in zip(*A)]


def _mat_mul(A: List[List[float]], B: List[List[float]]) -> List[List[float]]:
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


def _mat_inverse(A: List[List[float]]) -> List[List[float]]:
    """Gauss-Jordan inversion for small matrices (≤ 8x8)."""
    n = len(A)
    aug = [row[:] + [1.0 if i == j else 0.0 for j in range(n)] for i, row in enumerate(A)]
    for col in range(n):
        pivot = aug[col][col]
        if abs(pivot) < 1e-14:
            # Find row swap
            for r in range(col + 1, n):
                if abs(aug[r][col]) > 1e-14:
                    aug[col], aug[r] = aug[r], aug[col]
                    pivot = aug[col][col]
                    break
            else:
                raise ValueError("singular matrix")
        for j in range(2 * n):
            aug[col][j] /= pivot
        for r in range(n):
            if r != col:
                factor = aug[r][col]
                for j in range(2 * n):
                    aug[r][j] -= factor * aug[col][j]
    return [row[n:] for row in aug]


def ols_regression(y: List[float], X: List[List[float]]) -> Dict[str, object]:
    """OLS with intercept. X is n×k (no intercept column — added automatically).

    Returns:
      coeffs: [intercept, β1, ..., βk]
      t_stats: same length
      r_squared, n
    """
    n = len(y)
    k = len(X[0]) if X else 0
    # Add intercept column
    X_full = [[1.0] + list(row) for row in X]
    p = k + 1  # parameters incl. intercept

    if n <= p:
        return {"error": f"insufficient obs (n={n}, params={p})"}

    Xt = _mat_transpose(X_full)
    XtX = _mat_mul(Xt, X_full)
    XtX_inv = _mat_inverse(XtX)
    Xty = _mat_mul(Xt, [[v] for v in y])
    beta = _mat_mul(XtX_inv, Xty)
    coeffs = [row[0] for row in beta]

    # Fitted values, residuals, sigma^2
    y_hat = [sum(X_full[i][j] * coeffs[j] for j in range(p)) for i in range(n)]
    residuals = [y[i] - y_hat[i] for i in range(n)]
    ss_res = sum(r * r for r in residuals)
    y_mean = sum(y) / n
    ss_tot = sum((v - y_mean) ** 2 for v in y)
    r_sq = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

    sigma2 = ss_res / (n - p) if n > p else float("inf")
    se = [math.sqrt(sigma2 * XtX_inv[i][i]) if XtX_inv[i][i] > 0 else float("inf") for i in range(p)]
    t_stats = [coeffs[i] / se[i] if se[i] > 0 else 0.0 for i in range(p)]

    return {
        "coeffs": coeffs,
        "t_stats": t_stats,
        "r_squared": r_sq,
        "n": n,
        "residual_sigma": math.sqrt(sigma2),
    }


# ─────────────────────────────────────────────────────────────────
# Alpha per pick
# ─────────────────────────────────────────────────────────────────

def compute_pick_alpha(
    ticker: str, entry_date: str, exit_date: Optional[str], ff4: Dict[str, Dict[str, float]]
) -> Dict[str, object]:
    """Compute FF3 + FF4 alpha for one closed pick over its hold period."""
    entry_dt = datetime.strptime(entry_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    exit_dt = (
        datetime.strptime(exit_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if exit_date
        else datetime.now(timezone.utc)
    )
    # Pad for month-boundary
    start = entry_dt - timedelta(days=45)
    end = exit_dt + timedelta(days=5)

    closes = _yahoo_monthly_closes(ticker, start, end)
    rets = _monthly_returns(closes)
    # Restrict to hold-period months
    hold_keys = sorted([k for k in rets if entry_dt.strftime("%Y-%m") <= k <= exit_dt.strftime("%Y-%m")])

    if len(hold_keys) < 3:
        return {"ticker": ticker, "error": f"only {len(hold_keys)} monthly returns in hold period"}

    y_full = [rets[k] for k in hold_keys]
    # FF3 regression: excess return on Mkt-RF, SMB, HML
    X_ff3, y_ff3, months_ff3 = [], [], []
    X_ff4, y_ff4, months_ff4 = [], [], []
    for i, k in enumerate(hold_keys):
        f = ff4.get(k)
        if not f:
            continue
        rf = f.get("RF", 0.0)
        excess = y_full[i] - rf
        mkt = f.get("Mkt-RF")
        smb = f.get("SMB")
        hml = f.get("HML")
        umd = f.get("UMD")
        if mkt is None or smb is None or hml is None:
            continue
        X_ff3.append([mkt, smb, hml])
        y_ff3.append(excess)
        months_ff3.append(k)
        if umd is not None:
            X_ff4.append([mkt, smb, hml, umd])
            y_ff4.append(excess)
            months_ff4.append(k)

    result: Dict[str, object] = {
        "ticker": ticker,
        "entry_date": entry_date,
        "exit_date": exit_date,
        "hold_months": len(hold_keys),
        "months_used_ff3": len(months_ff3),
        "months_used_ff4": len(months_ff4),
    }

    if len(y_ff3) >= 5:
        ff3 = ols_regression(y_ff3, X_ff3)
        if "error" not in ff3:
            coeffs, ts = ff3["coeffs"], ff3["t_stats"]
            result["ff3"] = {
                "alpha_monthly": coeffs[0],
                "alpha_annualized_pct": round(coeffs[0] * 12 * 100, 2),
                "alpha_t": round(ts[0], 2),
                "beta_mkt": round(coeffs[1], 3),
                "beta_smb": round(coeffs[2], 3),
                "beta_hml": round(coeffs[3], 3),
                "r_squared": round(ff3["r_squared"], 3),
            }

    if len(y_ff4) >= 6:
        ff4res = ols_regression(y_ff4, X_ff4)
        if "error" not in ff4res:
            coeffs, ts = ff4res["coeffs"], ff4res["t_stats"]
            result["ff4"] = {
                "alpha_monthly": coeffs[0],
                "alpha_annualized_pct": round(coeffs[0] * 12 * 100, 2),
                "alpha_t": round(ts[0], 2),
                "beta_mkt": round(coeffs[1], 3),
                "beta_smb": round(coeffs[2], 3),
                "beta_hml": round(coeffs[3], 3),
                "beta_umd": round(coeffs[4], 3),
                "r_squared": round(ff4res["r_squared"], 3),
            }

    return result


# ─────────────────────────────────────────────────────────────────
# Job entry point
# ─────────────────────────────────────────────────────────────────

def run() -> str:
    print("Downloading Ken French FF3+UMD factors (or reading cache)...")
    ff4 = get_ff4_monthly()
    print(f"  Loaded {len(ff4)} months of factor data")

    api = get_client()
    print("Fetching closed confluence picks from Railway...")
    try:
        j = api.get("/api/admin/confluence/journal?include_closed=true&limit=200")
    except BMGApiError as e:
        return f"failed to fetch picks: {e}"

    all_picks = (j.get("open_picks") or []) + (j.get("closed_picks") or [])
    closed = [p for p in all_picks if p.get("closed_date") or p.get("exit_date")]
    print(f"  Got {len(closed)} closed picks (of {len(all_picks)} total)")

    if not closed:
        body = build_no_data_report(len(all_picks))
        path = write_job_output("ff4_alpha_calc", body)
        return f"wrote {path}: 0 closed picks — nothing to regress"

    # Compute per-pick alpha
    pick_results = []
    for p in closed[:100]:  # cap at 100 to keep runtime bounded
        ticker = p.get("ticker")
        entry = p.get("entry_date") or p.get("created_date")
        exit_ = p.get("closed_date") or p.get("exit_date")
        if not ticker or not entry:
            continue
        try:
            r = compute_pick_alpha(ticker, entry, exit_, ff4)
            pick_results.append(r)
            print(f"  {ticker}: {r.get('ff3', {}).get('alpha_annualized_pct', '—')}%/yr FF3-α")
        except Exception as e:
            print(f"  {ticker}: ERROR {e}")

    body = build_alpha_report(pick_results, len(all_picks), len(ff4))
    path = write_job_output("ff4_alpha_calc", body)
    return f"wrote {path}: {len(pick_results)} picks regressed"


def build_no_data_report(total_picks: int) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"""# FF4 Alpha Calculator — {today}

**Status:** waiting for data — 0 closed picks in journal (of {total_picks} total).

FF3/FF4 alpha regression requires ≥ 3 months of holding data per pick, and
ideally 10+ closed picks for a meaningful fund-aggregate. Currently the
confluence framework picks are all open.

## What this job will report once picks close

- Per-pick monthly FF3-α (Fama-French 3-factor) + t-stat + factor loadings
  (β_MKT, β_SMB, β_HML)
- Per-pick monthly FF4-α (Carhart 4-factor adds UMD momentum)
- Fund-aggregate alpha across all closed picks
- Comparison to raw excess return (which currently sits in the scorecard)

## Why this matters

Per vault research 2026-08-31 (RULE-M13, M17):
- Raw excess vs SPY is CAPM-style — assumes all edge is skill
- FF3-α strips out size + value tilt exposure
- FF4-α additionally strips out momentum tilt
- Only alpha remaining AFTER these controls is genuinely non-factor edge

Ken French data cached at ~/Documents/BMG-Capital-Vault/data/ff_factors/.
Re-run this job (or add to schedule.yaml) once we have 10+ closed picks.
"""


def build_alpha_report(results: List[Dict[str, object]], total_picks: int, factor_months: int) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    valid_ff3 = [r for r in results if "ff3" in r]
    valid_ff4 = [r for r in results if "ff4" in r]

    lines = [
        f"# FF4 Alpha Calculator — {today}",
        "",
        "*Honest edge measurement per vault research 2026-08-31 (FF3, Carhart 4-factor).*",
        "",
        f"- Picks analyzed: {len(results)} closed (of {total_picks} total in journal)",
        f"- Regressions with valid FF3: {len(valid_ff3)}",
        f"- Regressions with valid FF4: {len(valid_ff4)}",
        f"- Ken French factor months loaded: {factor_months}",
        "",
    ]

    # Fund aggregate
    if valid_ff3:
        alphas_ff3 = [r["ff3"]["alpha_annualized_pct"] for r in valid_ff3]
        mean_alpha = statistics.mean(alphas_ff3)
        stdev_alpha = statistics.stdev(alphas_ff3) if len(alphas_ff3) > 1 else 0.0
        lines.extend([
            "## Fund Aggregate (equal-weighted mean of per-pick alphas)",
            "",
            f"- **Mean FF3-α (annualized):** {mean_alpha:+.2f}%",
            f"- **Stdev of pick alphas:** {stdev_alpha:.2f}%",
            f"- **Picks with positive FF3-α:** {sum(1 for a in alphas_ff3 if a > 0)}/{len(alphas_ff3)}",
            "",
        ])
    if valid_ff4:
        alphas_ff4 = [r["ff4"]["alpha_annualized_pct"] for r in valid_ff4]
        mean_alpha = statistics.mean(alphas_ff4)
        lines.extend([
            f"- **Mean FF4-α (annualized):** {mean_alpha:+.2f}%",
            f"- **Picks with positive FF4-α:** {sum(1 for a in alphas_ff4 if a > 0)}/{len(alphas_ff4)}",
            "",
        ])

    # Per-pick table
    if valid_ff3:
        lines.extend([
            "## Per-Pick FF3 Alpha (sorted by alpha desc)",
            "",
            "| Ticker | Entry | Exit | Months | FF3-α (%/yr) | t-stat | β_MKT | β_SMB | β_HML | R² |",
            "|---|---|---|---:|---:|---:|---:|---:|---:|---:|",
        ])
        for r in sorted(valid_ff3, key=lambda x: -x["ff3"]["alpha_annualized_pct"]):
            f3 = r["ff3"]
            lines.append(
                f"| **{r['ticker']}** | {r['entry_date']} | {r.get('exit_date') or 'OPEN'} "
                f"| {r['months_used_ff3']} | {f3['alpha_annualized_pct']:+.2f} | {f3['alpha_t']:+.2f} "
                f"| {f3['beta_mkt']:+.2f} | {f3['beta_smb']:+.2f} | {f3['beta_hml']:+.2f} | {f3['r_squared']:.2f} |"
            )
        lines.append("")

    if valid_ff4:
        lines.extend([
            "## Per-Pick FF4 Alpha (Carhart — adds UMD momentum)",
            "",
            "| Ticker | Months | FF4-α (%/yr) | t-stat | β_UMD (momentum loading) |",
            "|---|---:|---:|---:|---:|",
        ])
        for r in sorted(valid_ff4, key=lambda x: -x["ff4"]["alpha_annualized_pct"]):
            f4 = r["ff4"]
            lines.append(
                f"| **{r['ticker']}** | {r['months_used_ff4']} | {f4['alpha_annualized_pct']:+.2f} "
                f"| {f4['alpha_t']:+.2f} | {f4['beta_umd']:+.2f} |"
            )
        lines.append("")

    lines.extend([
        "## Interpretation",
        "",
        "- **Positive t-stat > 2.0** on alpha means the pick beat FF3 controls at conventional significance.",
        "- **β_SMB > 0** means the pick loaded on small-cap. Some 'alpha' is really just size tilt.",
        "- **β_HML > 0** means value-tilt loading. Same caveat.",
        "- **β_UMD > 0** means momentum loading. FF4 vs FF3 alpha gap tells us how much came from momentum.",
        "",
        "Per RULE-M15: if FF3-α vanishes after adding UMD (β_UMD large + positive), we're just riding momentum, not adding skill.",
        "",
        "**Sample size warning:** for a real edge claim, need ≥ 20 closed picks with 6+ months each. Below that, all numbers are noisy signals not conclusions (per Bailey-López de Prado Deflated Sharpe).",
        "",
        "## Refs",
        "",
        "- `vault/research/2026-08-31-verify-fama-french-3-factor.md`",
        "- `vault/research/2026-08-31-verify-carhart-4-factor.md`",
        "- `vault/research/2026-08-30-verify-bailey-lopez-de-prado-deflated-sharpe.md`",
        "",
        f"*Generated by scripts/local/job_ff4_alpha_calc.py — Ken French factor data auto-refreshes weekly.*",
    ])
    return "\n".join(lines)


if __name__ == "__main__":
    print(run())
