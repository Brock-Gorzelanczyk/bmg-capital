"""Rule scorecard — measures which decision rules actually predict outcomes.

**Source of truth for rules:** `vault:research/decision-rules.md`
**Skeleton report:** `vault:research/rule-scorecard.md`

Reads all CLOSED confluence picks with rule_compliance records, buckets each
rule's picks into SATISFIED / VIOLATED / APPLIED, and computes discrimination
(satisfied avg excess return - violated avg excess return) with confidence
intervals.

**Discipline (per Bailey-Lopez de Prado + McLean-Pontiff applied to ourselves):**
  - Do NOT recommend demote/promote a rule below N=20 in BOTH satisfied AND
    violated buckets. Small-sample discrimination is noise, not signal.
  - Report 95% CIs, not just point estimates.
  - Kill-list requires 2 consecutive scorecard runs with no discrimination.

The scorecard emits a Dict[rule_id, ScorecardEntry] suitable for JSON serving
via admin endpoint, and pretty-prints to markdown for vault sync.
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

MIN_N_FOR_RECOMMENDATION = 20


def _welch_ci_diff(mean_a: float, var_a: float, n_a: int,
                   mean_b: float, var_b: float, n_b: int,
                   z: float = 1.96) -> tuple:
    """95% CI on (mean_a - mean_b) using Welch's t-approximation (large-N).

    Returns (lower, upper). Assumes N large enough for normal approx.
    """
    if n_a < 2 or n_b < 2:
        return (float("nan"), float("nan"))
    se = math.sqrt(var_a / n_a + var_b / n_b)
    diff = mean_a - mean_b
    return (diff - z * se, diff + z * se)


def _mean_var(xs: List[float]) -> tuple:
    """Sample mean + variance."""
    n = len(xs)
    if n == 0:
        return (0.0, 0.0)
    m = sum(xs) / n
    if n < 2:
        return (m, 0.0)
    v = sum((x - m) ** 2 for x in xs) / (n - 1)
    return (m, v)


def compute_scorecard(db: Session) -> Dict[str, Any]:
    """Compute the full scorecard across all closed picks with rule_compliance."""
    from app.db.models.confluence import ConfluencePick

    closed = db.query(ConfluencePick).filter(
        ConfluencePick.closed_date.isnot(None),
        ConfluencePick.rule_compliance.isnot(None),
        ConfluencePick.excess_vs_spy_pct.isnot(None),
    ).all()

    # Bucket picks by (rule_id, verdict)
    # Structure: rule_buckets[rule_id][verdict] -> list of excess_vs_spy_pct
    rule_buckets: Dict[str, Dict[str, List[float]]] = {}

    for pick in closed:
        try:
            rc = json.loads(pick.rule_compliance)
            rules = rc.get("rules", {})
        except Exception as e:
            logger.warning("[scorecard] pick %d rule_compliance parse failed: %s", pick.id, e)
            continue

        excess = float(pick.excess_vs_spy_pct)

        for rule_id, r in rules.items():
            verdict = r.get("verdict")
            if verdict not in ("SATISFIED", "VIOLATED", "APPLIED", "UNTESTABLE", "N/A"):
                continue
            rule_buckets.setdefault(rule_id, {}).setdefault(verdict, []).append(excess)

    # Compute per-rule stats
    scorecard: Dict[str, Any] = {}
    for rule_id, buckets in sorted(rule_buckets.items()):
        entry: Dict[str, Any] = {"rule_id": rule_id, "buckets": {}}

        for verdict, xs in buckets.items():
            m, v = _mean_var(xs)
            entry["buckets"][verdict] = {
                "n": len(xs),
                "mean_excess_pct": round(m, 4),
                "std_dev": round(math.sqrt(v), 4) if len(xs) > 1 else None,
                "hit_rate": round(sum(1 for x in xs if x >= 3.0) / len(xs), 4)
                            if xs else None,
            }

        # Discrimination: SATISFIED avg - VIOLATED avg (for SELECT/REJECT rules)
        sat = buckets.get("SATISFIED", [])
        vio = buckets.get("VIOLATED", [])
        n_sat, n_vio = len(sat), len(vio)

        recommendation = "INSUFFICIENT_DATA"
        discrimination = None
        ci = None

        if n_sat >= MIN_N_FOR_RECOMMENDATION and n_vio >= MIN_N_FOR_RECOMMENDATION:
            m_sat, v_sat = _mean_var(sat)
            m_vio, v_vio = _mean_var(vio)
            discrimination = round(m_sat - m_vio, 4)
            ci_lo, ci_hi = _welch_ci_diff(m_sat, v_sat, n_sat, m_vio, v_vio, n_vio)
            ci = [round(ci_lo, 4), round(ci_hi, 4)]

            # Recommendation logic
            if ci_lo > 0:
                recommendation = "PROMOTE"
            elif ci_hi < 0:
                recommendation = "INVESTIGATE"
            else:
                recommendation = "HOLD"

        entry["discrimination"] = discrimination
        entry["ci_95"] = ci
        entry["recommendation"] = recommendation
        scorecard[rule_id] = entry

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "closed_picks_with_rc": len(closed),
        "min_n_for_recommendation": MIN_N_FOR_RECOMMENDATION,
        "rules": scorecard,
    }


def scorecard_to_markdown(sc: Dict[str, Any]) -> str:
    """Render scorecard as markdown for vault sync."""
    lines = [
        "# RULE SCORECARD — Auto-Generated",
        "",
        f"**Generated:** {sc['generated_at']}",
        f"**Closed picks with rule-compliance records:** {sc['closed_picks_with_rc']}",
        f"**Min N per bucket for recommendation:** {sc['min_n_for_recommendation']}",
        "",
        "---",
        "",
    ]

    if sc['closed_picks_with_rc'] == 0:
        lines.append("*No closed picks with rule-compliance records yet. "
                     "Scorecard cannot run until picks close.*")
        return "\n".join(lines)

    lines.append("## Per-Rule Discrimination")
    lines.append("")
    lines.append("| Rule | N Sat | Mean Sat | N Vio | Mean Vio | Discrim | 95% CI | Rec |")
    lines.append("|---|---:|---:|---:|---:|---:|---|---|")

    for rule_id, entry in sc['rules'].items():
        b = entry.get('buckets', {})
        sat = b.get('SATISFIED', {})
        vio = b.get('VIOLATED', {})
        discrim = entry.get('discrimination')
        ci = entry.get('ci_95')
        ci_str = f"[{ci[0]}, {ci[1]}]" if ci else "—"
        lines.append(
            f"| {rule_id} | "
            f"{sat.get('n', 0)} | "
            f"{sat.get('mean_excess_pct', '—')} | "
            f"{vio.get('n', 0)} | "
            f"{vio.get('mean_excess_pct', '—')} | "
            f"{discrim if discrim is not None else '—'} | "
            f"{ci_str} | "
            f"{entry['recommendation']} |"
        )

    lines.extend(["", "## Recommendations", ""])
    for rule_id, entry in sc['rules'].items():
        rec = entry['recommendation']
        if rec == "PROMOTE":
            lines.append(f"- **{rule_id}**: PROMOTE (discrimination {entry['discrimination']}%, "
                         f"CI excludes 0 on positive side)")
        elif rec == "INVESTIGATE":
            lines.append(f"- **{rule_id}**: INVESTIGATE (discrimination {entry['discrimination']}%, "
                         f"CI excludes 0 on NEGATIVE side — rule may be inverted)")
        elif rec == "HOLD":
            lines.append(f"- **{rule_id}**: HOLD (discrimination {entry['discrimination']}%, "
                         f"CI includes 0)")

    return "\n".join(lines)
