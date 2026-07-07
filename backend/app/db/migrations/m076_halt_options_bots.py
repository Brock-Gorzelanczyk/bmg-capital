"""m076 — Emergency halt of options_income + options_directional bots.

Reason: BUY-to-open sign flip on all 6 credit-strategy files caused
options_income to pay premium instead of collect it. Alpaca account
utilization spiked to 99.7% and the bots were bleeding 2.57%/day.

Sign flip fixed in same commit (all 6 credit strategies now emit
side="sell"; runner's intent-based position side already fixed at
488a3269). Halting the bots until a fresh scan+test cycle confirms
sell orders route + fill correctly.

To re-enable:
  UPDATE bot_allocations SET enabled = 1 WHERE user_id = 1 AND
    profile_id IN (SELECT id FROM bot_profiles
                   WHERE name IN ('options_income', 'options_directional'));

Fund invariant unchanged (capital stays with the bots, just paused
from trading).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.db.migrations._gate import already_ran, record

logger = logging.getLogger(__name__)

_MIGRATION_NAME = "m076_halt_options_bots_2026_07_07"

_HALT_BOTS = ["options_income", "options_directional"]


def run(conn) -> dict:
    if already_ran(conn, _MIGRATION_NAME):
        return {"skipped_reason": "already_applied", "executed": False}

    now_iso = datetime.now(timezone.utc).isoformat()
    actions: list[dict] = []

    for name in _HALT_BOTS:
        prof = conn.execute(text(
            "SELECT id FROM bot_profiles WHERE name = :n"
        ), {"n": name}).fetchone()
        if not prof:
            actions.append({"bot": name, "action": "profile_not_found"})
            continue
        profile_id = int(prof[0])

        res = conn.execute(text("""
            UPDATE bot_allocations
            SET enabled = 0,
                paused_reason = 'm076_credit_side_bug_2026_07_07',
                updated_at = :ts
            WHERE user_id = 1
              AND profile_id = :pid
              AND enabled = 1
        """), {"ts": now_iso, "pid": profile_id})
        actions.append({
            "bot": name,
            "action": "halted",
            "rows_affected": res.rowcount,
        })
        logger.warning("[m076] halted %s (rows=%d)", name, res.rowcount)

    record(conn, _MIGRATION_NAME)
    return {"executed": True, "actions": actions}
