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

    # Portfolio summary — /api/portfolio/summary exposes total_value_cents +
    # alpaca_* breakdown; all-time P&L lives on /api/portfolio/snapshot as
    # total_pnl_alltime_cents. Prior version used made-up field names
    # (fund_pv_cents / cash_cents / all_time_pnl_cents) that returned dict
    # defaults of 0, silently printing "$0.00" for a live-funded account.
    try:
        summary = api.get("/api/portfolio/summary")
        fund_pv_cents = int(summary.get("total_value_cents") or 0)
        cash_cents = int(summary.get("alpaca_cash_cents") or 0)
        long_mv = int(summary.get("alpaca_long_mv_cents") or 0)
        short_mv = int(summary.get("alpaca_short_mv_cents") or 0)
        position_sum_cents = long_mv + short_mv
        today_pnl_cents = summary.get("today_pnl_cents")
        today_label = summary.get("today_pnl_label") or "n/a"
        try:
            snap = api.get("/api/portfolio/snapshot")
            alltime_pnl_cents = int(snap.get("total_pnl_alltime_cents") or 0)
        except BMGApiError:
            alltime_pnl_cents = 0
        today_str = (
            f"${today_pnl_cents / 100:,.2f}" if today_pnl_cents is not None else "—"
        )
        lines.extend([
            "### Fund",
            f"- Fund PV: ${fund_pv_cents / 100:,.2f}",
            f"- Cash: ${cash_cents / 100:,.2f}",
            f"- Positions: ${position_sum_cents / 100:,.2f}",
            f"- Today P&L: {today_str} ({today_label})",
            f"- All-time P&L: ${alltime_pnl_cents / 100:,.2f}",
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
