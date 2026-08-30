"""job_morning_brief — pre-market brief 7:30am ET → Obsidian.

Was on Railway as `morning_brief` cron. Moved local 2026-08-30.
Pulls open positions + confluence picks + writes brief.

Called by scripts/local/run.py — must expose `run() -> str`.
"""
from __future__ import annotations

from datetime import datetime, timezone

from _bmg_api import get_client, BMGApiError
from _obsidian import write_job_output


def run() -> str:
    api = get_client()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    lines = [f"## Morning Brief — {today}", ""]

    # Open positions
    try:
        positions = api.get("/api/portfolio/positions")
        pos_list = positions.get("positions", [])
        lines.extend([
            "### Open Positions",
            f"Count: {len(pos_list)}",
            "",
        ])
        for p in pos_list[:15]:
            unrealized = (p.get("unrealized_pnl_cents") or 0) / 100
            lines.append(
                f"- **{p.get('symbol')}** {p.get('qty')}sh @ ${(p.get('avg_entry_cents') or 0)/100:.2f} "
                f"(unrealized ${unrealized:+,.2f})"
            )
        lines.append("")
    except BMGApiError as e:
        lines.append(f"⚠️ portfolio/positions failed: {e}\n")

    # Armed confluence picks (about to fire)
    try:
        journal = api.get("/api/admin/confluence/journal?include_closed=false&limit=50")
        open_picks = journal.get("open_picks", [])
        armed = [p for p in open_picks if p.get("arm_state") == "ARMED"]
        lines.extend([
            "### Armed Picks (ready to fire)",
            f"Count: {len(armed)}",
            "",
        ])
        for p in armed[:10]:
            lines.append(
                f"- **{p.get('ticker')}** Play A trigger ${(p.get('play_a_trigger_price_cents') or 0)/100:.2f} "
                f"stop ${(p.get('play_a_stop_price_cents') or 0)/100:.2f}"
            )
        lines.append("")
    except BMGApiError as e:
        lines.append(f"⚠️ confluence/journal failed: {e}\n")

    body = "\n".join(lines)
    path = write_job_output("morning_brief", body)
    return f"wrote {path}"


if __name__ == "__main__":
    print(run())
