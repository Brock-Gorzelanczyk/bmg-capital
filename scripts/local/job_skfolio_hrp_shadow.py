"""skfolio HRP shadow allocator — LOCAL, non-prod.

Reads bot daily P&L via Railway API, runs Hierarchical Risk Parity + Hierarchical
Equal Risk Contribution + Risk Budgeting on the bot-returns matrix, and writes
side-by-side vs the live risk-parity allocator to the vault.

Purpose: WATCH how HRP would differ from the current risk-parity allocator.
Do NOT execute HRP weights directly — this is a shadow signal for judgment.

If HRP consistently outperforms the risk-parity allocator over 60 days, promote.
If it diverges wildly with no clear win, keep it as a diagnostic.

Follows §L1 local-first architecture — costs $0 on Railway.
Runs weekly via scripts/local/schedule.yaml.

Requires:
  pip install skfolio pandas numpy scikit-learn
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _bmg_api import get_client  # noqa: E402
from _obsidian import write_job_output  # noqa: E402


LOOKBACK_DAYS = 60
MIN_BOTS = 3  # need at least 3 bots for meaningful HRP hierarchy


def _fetch_returns_matrix(api) -> "pandas.DataFrame":
    """Get bot × date returns matrix from Railway API. Returns pct returns."""
    import pandas as pd

    # Use the existing bot-performance endpoint; it returns per-bot daily P&L
    since = (date.today() - timedelta(days=LOOKBACK_DAYS + 5)).isoformat()
    data = api.get(f"/api/bot-performance/daily?since={since}")
    rows = data.get("rows", [])
    if not rows:
        raise RuntimeError("no bot daily P&L rows returned")

    df = pd.DataFrame(rows)  # cols: allocation_id, name, date, realized_cents, starting_capital_cents
    df["date"] = pd.to_datetime(df["date"])
    df["ret"] = df["realized_cents"] / df["starting_capital_cents"].replace(0, pd.NA)
    df = df.dropna(subset=["ret"])

    pivot = df.pivot(index="date", columns="name", values="ret").fillna(0.0)
    # Drop bots with < 20 observations (thin history distorts HRP dendrogram)
    keep_cols = pivot.columns[(pivot != 0).sum() >= 20]
    return pivot[keep_cols]


def _run_hrp_family(returns_df) -> dict:
    """Fit HRP, HERC, and RiskBudgeting on the returns matrix.

    Returns dict of {method_name: {bot_name: weight_pct}}.
    """
    import numpy as np
    from skfolio import RiskMeasure
    from skfolio.optimization import HierarchicalRiskParity, HierarchicalEqualRiskContribution, RiskBudgeting
    from skfolio.cluster import HierarchicalClustering
    from skfolio.distance import PearsonDistance

    X = returns_df.values
    names = list(returns_df.columns)

    results: dict[str, dict[str, float]] = {}

    # HRP with CVaR (safer than variance for skewed bot P&L)
    try:
        model = HierarchicalRiskParity(
            risk_measure=RiskMeasure.CVAR,
            hierarchical_clustering_estimator=HierarchicalClustering(),
            distance_estimator=PearsonDistance(),
        )
        model.fit(X)
        results["HRP_CVaR"] = {names[i]: float(w) * 100 for i, w in enumerate(model.weights_)}
    except Exception as e:
        results["HRP_CVaR_error"] = {"_error": str(e)[:120]}

    # HERC (better cluster-aware inheritance than HRP)
    try:
        model = HierarchicalEqualRiskContribution(
            risk_measure=RiskMeasure.VARIANCE,
        )
        model.fit(X)
        results["HERC_Var"] = {names[i]: float(w) * 100 for i, w in enumerate(model.weights_)}
    except Exception as e:
        results["HERC_Var_error"] = {"_error": str(e)[:120]}

    # Risk Budgeting — equal risk contribution (no hierarchy)
    try:
        model = RiskBudgeting(risk_measure=RiskMeasure.VARIANCE)
        model.fit(X)
        results["RB_ERC"] = {names[i]: float(w) * 100 for i, w in enumerate(model.weights_)}
    except Exception as e:
        results["RB_ERC_error"] = {"_error": str(e)[:120]}

    return results


def _fetch_live_weights(api) -> dict:
    """Get the live risk-parity allocator's current weights."""
    try:
        data = api.get("/api/allocation/current-weights")
        return {r["name"]: r["weight_pct"] for r in data.get("rows", [])}
    except Exception:
        # Fallback: uniform across enabled bots from the bot list
        data = api.get("/api/bots")
        bots = data.get("bots", [])
        n = len(bots) or 1
        return {b["name"]: 100.0 / n for b in bots}


def _write_report(returns_df, results: dict, live_weights: dict) -> str:
    lines: list[str] = []
    lines.append("# skfolio HRP shadow allocator — weekly diff\n")
    lines.append("**Purpose:** watch how HRP / HERC / Risk Budgeting would allocate\n")
    lines.append("differently from the live risk-parity allocator. Not executed.\n\n")
    lines.append(f"**Lookback:** {LOOKBACK_DAYS} days · bots included: {returns_df.shape[1]} · observations: {returns_df.shape[0]}\n\n")

    if returns_df.shape[1] < MIN_BOTS:
        lines.append(f"⚠️ **Only {returns_df.shape[1]} bots with sufficient history — HRP hierarchy needs ≥ {MIN_BOTS}.** Skipping optimization.\n")
        return "".join(lines)

    # Big table: bot × method weights
    method_names = [k for k in results if not k.endswith("_error")]
    header = "| Bot | Live (RP) | " + " | ".join(method_names) + " |\n"
    sep = "|---|" + "---|" * (1 + len(method_names)) + "\n"
    lines.append(header)
    lines.append(sep)

    all_bots = sorted(returns_df.columns)
    for bot in all_bots:
        live = live_weights.get(bot, 0.0)
        row = f"| {bot} | {live:.1f}% |"
        for m in method_names:
            w = results[m].get(bot, 0.0)
            delta = w - live
            marker = "🔺" if delta > 5 else ("🔻" if delta < -5 else "")
            row += f" {w:.1f}% {marker} |"
        row += "\n"
        lines.append(row)

    # Errors
    for k, v in results.items():
        if k.endswith("_error"):
            lines.append(f"\n**{k}**: `{v.get('_error')}`\n")

    lines.append("\n## Interpretation guide\n")
    lines.append("- **HRP_CVaR**: variance-of-tail-losses weighting. Deweights bots with big downside outliers even if their mean is fine.\n")
    lines.append("- **HERC_Var**: equal-risk within each hierarchical cluster. Balances between highly-correlated bots (e.g., all crypto together).\n")
    lines.append("- **RB_ERC**: pure equal-risk-contribution, no hierarchy. This is what pure risk-parity converges to.\n\n")
    lines.append("**Read:** if HRP methods consistently downweight a bot the live allocator overweights, that's a signal to investigate whether the live allocator is being fooled by a low-vol run masking hidden tail risk.\n\n")
    lines.append("**Decision rule:** promote HRP only after 60+ days of shadow tracking + HRP variant beating live cumulative sleeve return by > 200 bps.\n")

    return "".join(lines)


def run() -> str:
    try:
        api = get_client()
        returns = _fetch_returns_matrix(api)
        results = _run_hrp_family(returns)
        live = _fetch_live_weights(api)
        body = _write_report(returns, results, live)
        write_job_output("skfolio_hrp_shadow", body)
        return f"ok · {returns.shape[1]} bots · {returns.shape[0]} obs"
    except Exception as e:
        import traceback
        err_body = "# skfolio HRP shadow — FAILED\n\n```\n" + traceback.format_exc() + "\n```\n"
        write_job_output("skfolio_hrp_shadow", err_body)
        return f"error: {e}"


if __name__ == "__main__":
    print(run())
