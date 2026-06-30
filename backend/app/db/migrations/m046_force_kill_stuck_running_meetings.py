"""m046 — force-close any fund_meetings row stuck in status='running' for >30 minutes.

WHY THIS EXISTS (and why it has no gate):
  Pre-PR-#25, POST /api/agents/cio/meeting/start ran the full meeting SYNCHRONOUSLY
  inside the HTTP request. Cloudflare killed those requests at 5 min but the DB row
  was never updated — leaving fund_meetings rows in status='running' forever, which
  in turn made the 409 stale-window guard return 409 for every subsequent /start call.

  The asyncio.wait_for(900s) watchdog added in PR #25 (cio_meeting_runner.py) CANNOT
  fire on pre-#25 orphans because no asyncio task exists for them. m046 is the
  belt-and-suspenders cleanup that runs on every boot to catch any orphan row whose
  started_at is older than 30 minutes (2x the 15-min watchdog).

IDEMPOTENCY: SQL match is `WHERE status='running' AND started_at < :cutoff`. On a
healthy boot this matches zero rows; UPDATE is a no-op; killed_count=0 is returned.
No gate row needed — re-running on every boot is cheap and self-limiting.

RISK: If a legitimate meeting runs >30 min in flight (the asyncio watchdog should
prevent this at 15 min), m046 on a subsequent boot would mark it failed_killed
mid-flight. Document only — do not gate around this; the watchdog is the
upstream defense.

Standing decisions honored:
  - NO writes to inception_capital_cents.
  - NO writes to bot_trades or bot_daily_pnl.
  - NO writes to bot_allocations.
  - Multi-user safe: fund_meetings has no user_id column.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

logger = logging.getLogger(__name__)

KILL_CUTOFF_MINUTES = 30


def run(conn) -> dict:
    """Mark every running meeting older than KILL_CUTOFF_MINUTES as failed_killed.

    Returns:
        {"executed": True, "killed_count": N, "cutoff_iso": "..."}
    """
    now_dt = datetime.now(timezone.utc)
    cutoff_iso = (now_dt - timedelta(minutes=KILL_CUTOFF_MINUTES)).isoformat()
    now_iso = now_dt.isoformat()

    result = conn.execute(
        text(
            "UPDATE fund_meetings "
            "   SET status='failed_killed', "
            "       ended_at=:now, "
            "       failure_reason='boot_orphan_cleanup' "
            " WHERE status='running' AND started_at < :cutoff"
        ),
        {"now": now_iso, "cutoff": cutoff_iso},
    )

    killed_count = int(result.rowcount or 0)
    if killed_count > 0:
        logger.warning(
            "[m046] killed_count=%d cutoff_iso=%s (orphan running rows force-closed)",
            killed_count, cutoff_iso,
        )
    else:
        logger.info("[m046] killed_count=0 (no orphan running rows)")

    return {"executed": True, "killed_count": killed_count, "cutoff_iso": cutoff_iso}
