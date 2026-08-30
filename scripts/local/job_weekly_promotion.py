"""job_weekly_promotion — Monday 9am ET weekly bot promotion digest.

Was on Railway as `weekly_promotion_digest` cron. Moved local 2026-08-30.
Reports which bots are ready to promote/demote by tier based on realized P&L.

Called by scripts/local/run.py — must expose `run() -> str`.
"""
from __future__ import annotations

from datetime import datetime, timezone

from _bmg_api import get_client, BMGApiError
from _obsidian import write_job_output


def run() -> str:
    api = get_client()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    lines = [f"## Weekly Promotion Digest — {today}", ""]

    # Rule scorecard (part of research → decision pipeline)
    try:
        sc = api.get("/api/admin/confluence/scorecard")
        n_picks = sc.get("closed_picks_with_rc", 0)
        rules = sc.get("rules", {})
        lines.extend([
            "### Rule Scorecard",
            f"- Closed picks with rule-compliance records: **{n_picks}**",
            f"- Rules evaluated: {len(rules)}",
            "",
        ])

        promotes = [rid for rid, r in rules.items() if r.get("recommendation") == "PROMOTE"]
        investigates = [rid for rid, r in rules.items() if r.get("recommendation") == "INVESTIGATE"]
        insufficient = [rid for rid, r in rules.items() if r.get("recommendation") == "INSUFFICIENT_DATA"]

        if promotes:
            lines.append("**PROMOTE:**")
            for rid in promotes:
                r = rules[rid]
                lines.append(f"- {rid}: discrimination {r.get('discrimination')}% "
                             f"CI {r.get('ci_95')}")
        if investigates:
            lines.append("\n**INVESTIGATE (rule may be inverted):**")
            for rid in investigates:
                r = rules[rid]
                lines.append(f"- {rid}: {r.get('discrimination')}% CI {r.get('ci_95')}")
        if insufficient:
            lines.append(f"\n**Insufficient data ({len(insufficient)} rules):** "
                         "need N≥20 satisfied AND N≥20 violated picks to promote/demote.")

        lines.append("")
    except BMGApiError as e:
        lines.append(f"⚠️ scorecard failed: {e}\n")

    # Confluence framework KPIs
    try:
        journal = api.get("/api/admin/confluence/journal?include_closed=true&limit=100")
        closed = [p for p in journal.get("closed_picks", []) if p.get("closed_date")]
        if closed:
            hit_rate = sum(1 for p in closed if p.get("hit_win_criterion")) / len(closed)
            avg_excess = sum(p.get("excess_vs_spy_pct") or 0 for p in closed) / len(closed)
            lines.extend([
                "### Confluence Framework KPI",
                f"- Closed picks: **{len(closed)}**",
                f"- Hit rate (≥3% excess vs SPY): **{hit_rate:.1%}**",
                f"- Avg excess vs SPY: **{avg_excess:+.2f}%**",
                f"- Verdict: {journal.get('verdict', 'n/a')}",
                "",
            ])
    except BMGApiError as e:
        lines.append(f"⚠️ confluence/journal failed: {e}\n")

    body = "\n".join(lines)
    path = write_job_output("weekly_promotion", body)
    return f"wrote {path}"


if __name__ == "__main__":
    print(run())
