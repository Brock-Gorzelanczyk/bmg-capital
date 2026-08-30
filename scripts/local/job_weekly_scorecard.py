"""Weekly rule scorecard — auto-runs Sunday 8am, writes to Obsidian.

Pulls all closed confluence picks (with rule_compliance JSON) from Railway.
Runs the same discrimination analysis as backend's rule_scorecard service
but LOCAL and writes a formatted markdown report to the vault research/ folder.

Key discipline (per Bailey-Lopez de Prado + McLean-Pontiff):
- MIN N = 20 in EACH bucket (satisfied AND violated) before recommending
  promote/demote. Small samples produce noise, not signal.
- Report confidence intervals, not just point estimates.
- Track history over time — a rule that discriminates one week but not next
  is not a real edge.

When a rule shows persistent discrimination:
- Promote it (weight higher in future picks)
- Or use as evidence to change the framework

When a rule shows persistent non-discrimination:
- Consider retiring it
- Consider changing its definition
"""
from __future__ import annotations

import json
import math
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent.resolve()
sys.path.insert(0, str(HERE))
from _bmg_api import get_client, BMGApiError  # noqa: E402

VAULT_ROOT = Path.home() / "Documents" / "BMG-Capital-Vault"
MIN_N_FOR_REC = 20  # Bailey-Lopez de Prado discipline applied to ourselves


def _welch_ci(mean_a: float, var_a: float, n_a: int,
              mean_b: float, var_b: float, n_b: int,
              z: float = 1.96) -> tuple:
    """95% CI on (mean_a - mean_b) via Welch's approximation."""
    if n_a < 2 or n_b < 2:
        return (float("nan"), float("nan"))
    se = math.sqrt(var_a / n_a + var_b / n_b)
    diff = mean_a - mean_b
    return (diff - z * se, diff + z * se)


def run() -> str:
    api = get_client()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        j = api.get("/api/admin/confluence/journal?include_closed=true&limit=500")
    except BMGApiError as e:
        return f"FAIL: {e}"

    closed = [p for p in j.get("closed_picks", []) if p.get("closed_date")]
    open_picks = j.get("open_picks", [])
    total = len(closed) + len(open_picks)

    if not closed:
        # No closed picks yet — write "waiting for data" note
        lines = [
            f"# Weekly Rule Scorecard — {today}",
            "",
            f"**Status:** Waiting for data. {total} total picks so far, {len(closed)} closed.",
            "",
            "**Scorecard requires closed picks with `rule_compliance` records.**",
            "The framework was updated to attach rule_compliance to every new pick",
            f"on 2026-08-30. As picks close over the next few weeks, this scorecard",
            "will start producing discrimination stats.",
            "",
            "**Minimum sample:** 20 satisfied + 20 violated per rule before any",
            "promote/demote recommendation. Below that = noise not signal.",
            "",
            f"**Current status:**",
            f"- Open picks: {len(open_picks)}",
            f"- Closed picks: {len(closed)}",
            f"- Estimated weeks to first meaningful scorecard: ~4-8 weeks",
            "",
            "This report will populate automatically. No manual work needed.",
        ]
        out = VAULT_ROOT / "research" / f"{today}-weekly-scorecard.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(lines))
        return f"wrote {out} (waiting for closed picks)"

    # ── Extract per-rule bucketed excess returns ──
    rule_buckets = defaultdict(lambda: defaultdict(list))
    for p in closed:
        rc_raw = p.get("rule_compliance")
        if not rc_raw:
            continue
        try:
            rc = json.loads(rc_raw) if isinstance(rc_raw, str) else rc_raw
        except Exception:
            continue
        excess = p.get("excess_vs_spy_pct")
        if excess is None:
            continue
        rules = rc.get("rules", {})
        for rid, r in rules.items():
            verdict = r.get("verdict")
            if verdict in ("SATISFIED", "VIOLATED", "APPLIED", "UNTESTABLE", "N/A"):
                rule_buckets[rid][verdict].append(float(excess))

    # ── Compute discrimination + recommendations ──
    scorecard = []
    for rid in sorted(rule_buckets.keys()):
        buckets = rule_buckets[rid]
        sat = buckets.get("SATISFIED", [])
        vio = buckets.get("VIOLATED", [])
        n_sat, n_vio = len(sat), len(vio)

        m_sat = statistics.mean(sat) if sat else None
        m_vio = statistics.mean(vio) if vio else None
        v_sat = statistics.variance(sat) if len(sat) > 1 else 0
        v_vio = statistics.variance(vio) if len(vio) > 1 else 0

        rec = "INSUFFICIENT"
        discrim = None
        ci = (None, None)
        if n_sat >= MIN_N_FOR_REC and n_vio >= MIN_N_FOR_REC:
            discrim = m_sat - m_vio
            ci = _welch_ci(m_sat, v_sat, n_sat, m_vio, v_vio, n_vio)
            if ci[0] > 0:
                rec = "PROMOTE"
            elif ci[1] < 0:
                rec = "INVESTIGATE"
            else:
                rec = "HOLD"

        scorecard.append({
            "rule": rid,
            "n_sat": n_sat, "n_vio": n_vio,
            "m_sat": m_sat, "m_vio": m_vio,
            "discrim": discrim, "ci": ci, "rec": rec,
        })

    # ── Render ──
    lines = [
        f"# Weekly Rule Scorecard — {today}",
        "",
        f"**Closed picks analyzed:** {len(closed)} of {total} total",
        f"**Rules evaluated:** {len(scorecard)}",
        f"**Discipline:** min N={MIN_N_FOR_REC} in BOTH satisfied AND violated buckets",
        "",
        "## Per-rule discrimination",
        "",
        "| Rule | N Sat | Sat Avg | N Vio | Vio Avg | Discrim | 95% CI | Rec |",
        "|---|---:|---:|---:|---:|---:|---|---|",
    ]
    for s in scorecard:
        m_sat_s = f"{s['m_sat']:+.2f}%" if s['m_sat'] is not None else "—"
        m_vio_s = f"{s['m_vio']:+.2f}%" if s['m_vio'] is not None else "—"
        discrim_s = f"{s['discrim']:+.2f}%" if s['discrim'] is not None else "—"
        if s['ci'][0] is not None:
            ci_s = f"[{s['ci'][0]:+.2f}, {s['ci'][1]:+.2f}]"
        else:
            ci_s = "—"
        lines.append(
            f"| {s['rule']} | {s['n_sat']} | {m_sat_s} | {s['n_vio']} | {m_vio_s} | "
            f"{discrim_s} | {ci_s} | {s['rec']} |"
        )

    # ── Actionable recommendations ──
    promoted = [s for s in scorecard if s['rec'] == 'PROMOTE']
    investigate = [s for s in scorecard if s['rec'] == 'INVESTIGATE']
    holds = [s for s in scorecard if s['rec'] == 'HOLD']
    insufficient = [s for s in scorecard if s['rec'] == 'INSUFFICIENT']

    lines.extend(["", "## Recommendations", ""])
    if promoted:
        lines.append("### 🟢 PROMOTE (CI excludes 0, positive discrimination)")
        for s in promoted:
            lines.append(
                f"- **{s['rule']}**: satisfied picks earn {s['discrim']:+.2f}% "
                f"more than violated picks (95% CI {s['ci']}). "
                f"Consider weighting HIGHER or making mandatory."
            )
        lines.append("")
    if investigate:
        lines.append("### 🔴 INVESTIGATE (CI excludes 0, negative — rule may be INVERTED)")
        for s in investigate:
            lines.append(
                f"- **{s['rule']}**: violated picks earn {abs(s['discrim']):+.2f}% "
                f"MORE than satisfied. Rule may be backwards — check the logic."
            )
        lines.append("")
    if holds:
        lines.append("### 🟡 HOLD (CI includes 0, no significant edge)")
        for s in holds:
            lines.append(
                f"- **{s['rule']}**: discrim {s['discrim']:+.2f}%, CI includes 0. "
                f"No clear edge — but has enough sample. Consider retiring in 4-8 weeks."
            )
        lines.append("")
    if insufficient:
        lines.append("### ⚪ INSUFFICIENT DATA")
        lines.append("Need more closed picks to evaluate these rules:")
        for s in insufficient:
            lines.append(
                f"- **{s['rule']}**: only {s['n_sat']} satisfied + {s['n_vio']} violated"
            )
        lines.append("")

    lines.extend([
        "## Historical trend",
        "",
        "Each week's scorecard is a snapshot. Check `research/*-weekly-scorecard.md`",
        "files to see if rule discrimination is:",
        "- Persistent (real edge) — 3+ weeks of PROMOTE = high confidence",
        "- Random (noise) — flips between rec categories week-to-week",
        "- Decaying (edge fading) — was PROMOTE, now HOLD or INSUFFICIENT",
        "",
        "This scorecard runs Sunday 8am ET automatically.",
        "",
        "Companion notes:",
        "- `research/decision-rules.md` — the rulebook",
        "- `research/rule-scorecard.md` — skeleton + methodology",
        "- `research/2026-08-30-signal-ablation-study.md` — signal quality analysis",
    ])

    out = VAULT_ROOT / "research" / f"{today}-weekly-scorecard.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines))
    return (f"wrote {out}\n"
            f"promoted: {len(promoted)} | investigate: {len(investigate)} | "
            f"hold: {len(holds)} | insufficient: {len(insufficient)}")


if __name__ == "__main__":
    print(run())
