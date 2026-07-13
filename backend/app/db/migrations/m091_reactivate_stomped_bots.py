"""m091 — Reactivate 3 bots m026 was auto-pausing every boot.

Root cause: m026's SPEC_BOT_NAMES frozenset is a hardcoded whitelist. Any
allocation whose profile.name is missing gets `enabled=0,
paused_reason='m026_non_spec'` on every boot. When I promoted
tsmom_multi_asset in m081 and left macro_faber_gtaa + spy_iron_condor_weekly
unlisted, m026 stomped them back to disabled on the very next deploy.

Fixed in the companion commit by adding those 3 names to
m026.SPEC_BOT_NAMES. This migration flips them enabled=1 and clears
paused_reason so they start trading immediately instead of waiting for
another manual toggle.

Order matters: this migration MUST run AFTER m026 in the same boot so
m026's stomp finishes first and this migration is the last word.
main.py registers migrations in numeric order → m089/m090/m091 fire
after m026 → we win. Idempotent via _gate.record().
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import bindparam, text

from app.db.migrations._gate import already_ran, record

logger = logging.getLogger(__name__)

_MIGRATION_NAME = "m091_reactivate_stomped_bots_2026_07_12"
_BOTS = ["tsmom_multi_asset", "macro_faber_gtaa", "spy_iron_condor_weekly"]


def run(conn) -> dict:
    if already_ran(conn, _MIGRATION_NAME):
        return {"skipped_reason": "already_applied", "executed": False}

    now_iso = datetime.now(timezone.utc).isoformat()

    rows = conn.execute(text("""
        SELECT ba.id, bp.name, ba.enabled, ba.paused_reason, ba.starting_capital_cents
          FROM bot_allocations ba
          JOIN bot_profiles bp ON bp.id = ba.profile_id
         WHERE ba.user_id = 1 AND bp.name IN :names
    """).bindparams(bindparam("names", expanding=True)),
        {"names": _BOTS}).fetchall()

    actions: list[dict] = []
    for r in rows:
        alloc_id = int(r[0])
        name = r[1]
        was_enabled = bool(r[2])
        prior_reason = r[3]
        cap = int(r[4] or 0)

        if was_enabled and prior_reason is None:
            actions.append({"bot": name, "action": "already_enabled",
                            "cap_cents": cap})
            continue
        # Only clear the reason if it's the m026 stomp — don't accidentally
        # unpause a bot Brock or another migration halted for a real reason.
        if prior_reason and prior_reason != "m026_non_spec":
            actions.append({"bot": name, "action": "skipped_other_pause",
                            "paused_reason": prior_reason})
            continue

        conn.execute(text(
            "UPDATE bot_allocations "
            "SET enabled = 1, paused_reason = NULL, updated_at = :ts "
            "WHERE id = :aid"
        ), {"ts": now_iso, "aid": alloc_id})
        actions.append({"bot": name, "action": "reactivated",
                        "alloc_id": alloc_id, "cap_cents": cap})

    missing = [n for n in _BOTS if not any(a["bot"] == n for a in actions)]
    for n in missing:
        actions.append({"bot": n, "action": "no_allocation_found"})

    logger.warning("[m091] actions=%s", actions)
    record(conn, _MIGRATION_NAME)
    return {"executed": True, "actions": actions}
