"""job_daily_recap — after-close daily P&L + trade summary → Obsidian.

Was on Railway as `daily_recap` cron (4:15pm ET M-F). Moved local 2026-08-30
to cut Railway memory cost. Pulls today's data from Railway API + writes to
`~/Documents/BMG-Capital-Vault/context/local-jobs/YYYY-MM-DD-job_daily_recap.md`.

Called by scripts/local/run.py — must expose `run() -> str`.
"""
from __future__ import annotations

from datetime import datetime, timezone

from _bmg_api import get_client, BMGApiError
from _obsidian import write_job_output


def run() -> str:
    api = get_client()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    lines = [f"## Daily Recap — {today}", ""]

    # Portfolio summary
    try:
        summary = api.get("/api/portfolio/summary")
        lines.extend([
            "### Fund",
            f"- Fund PV: ${summary.get('fund_pv_cents', 0) / 100:,.2f}",
            f"- Cash: ${summary.get('cash_cents', 0) / 100:,.2f}",
            f"- Positions: ${summary.get('position_sum_cents', 0) / 100:,.2f}",
            f"- Today P&L: ${(summary.get('today_pnl_cents') or 0) / 100:,.2f} "
            f"({summary.get('today_pnl_label', 'n/a')})",
            f"- All-time P&L: ${(summary.get('all_time_pnl_cents') or 0) / 100:,.2f}",
            "",
        ])
    except BMGApiError as e:
        lines.append(f"⚠️ portfolio/summary failed: {e}\n")

    # Confluence picks status
    try:
        journal = api.get("/api/admin/confluence/journal?include_closed=false&limit=50")
        open_picks = journal.get("open_picks", [])
        lines.extend([
            "### Open Confluence Picks",
            f"Count: {len(open_picks)}",
            "",
        ])
        for p in open_picks[:10]:
            lines.append(
                f"- **{p.get('ticker')}** entry ${p.get('entry_price'):.2f} "
                f"target ${p.get('target_price') or '—'} "
                f"({p.get('signals', {}).get('count', 0)} signals)"
            )
        lines.append("")
    except BMGApiError as e:
        lines.append(f"⚠️ confluence/journal failed: {e}\n")

    body = "\n".join(lines)
    path = write_job_output("daily_recap", body)
    return f"wrote {path}"


if __name__ == "__main__":
    print(run())
