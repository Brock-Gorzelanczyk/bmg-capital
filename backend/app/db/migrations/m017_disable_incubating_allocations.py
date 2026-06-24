"""Migration m017: Disable bot_allocations for INCUBATING-PENDING-DATA profiles.

The 3 research strategies earnings_nlp / quality_factor / value_quality were
flagged INCUBATING-PENDING-DATA in commit 576141a (YAML enabled: false +
comment documenting which data feed each needs). The profile YAMLs are now
correct, but the matching bot_allocations rows on production still carry
enabled=1, so the UI still shows them as ACTIVE with 0-symbol universes.

Idempotent: only touches rows where enabled = 1 AND the profile is in the
incubating set, so re-runs are safe no-ops once consistent.

Acceptance: Strategy Lab "active bots" count drops by 3 (12 → 9 for admin).
"""
from __future__ import annotations

import logging
from sqlalchemy import text

logger = logging.getLogger(__name__)

_INCUBATING_PROFILES = ("earnings_nlp", "quality_factor", "value_quality")


def run(conn) -> None:
    try:
        result = conn.execute(
            text("""
                UPDATE bot_allocations
                SET
                    enabled        = 0,
                    paused_reason  = 'incubating_pending_data'
                WHERE enabled = 1
                  AND profile_id IN (
                    SELECT id FROM bot_profiles WHERE name IN (
                        :p0, :p1, :p2
                    )
                  )
            """),
            {"p0": _INCUBATING_PROFILES[0], "p1": _INCUBATING_PROFILES[1], "p2": _INCUBATING_PROFILES[2]},
        )
        conn.commit()
        count = getattr(result, "rowcount", None) or 0
        if count:
            logger.warning(
                "[m017] Disabled %d INCUBATING-PENDING-DATA allocations (%s)",
                count, ",".join(_INCUBATING_PROFILES),
            )
        else:
            logger.info(
                "[m017] No active INCUBATING allocations to disable — already clean"
            )
    except Exception as exc:
        logger.warning("[m017] disable migration failed (non-fatal): %s", exc)
        try:
            conn.rollback()
        except Exception:
            pass
