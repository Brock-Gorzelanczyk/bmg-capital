"""Migration m002: Seed all 12 production bot allocations at Tier 2.

Truly idempotent — runs every startup, only promotes allocations still at T0.
Never downgrades T1/T2/T3. No schema_migrations guard (the original guard caused
the bug where m002 ran before any user allocations existed, recorded itself as
done, then never ran again when allocations were created later).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import text

logger = logging.getLogger(__name__)

_PRODUCTION_PROFILES = [
    "stock_swing",
    "stock_day",
    "stock_lt",
    "crypto_swing",
    "crypto_day",
    "crypto_lt",
    "crypto_onchain",
    "crypto_quant_aggressive",
    "crypto_quant_mean_reversion",
    "crypto_quant_scalper",
    "options_income",
    "options_directional",
]


def run(conn) -> None:
    """Promote production bot allocations from T0 → T2. Runs every startup.

    Only touches rows where tier IS NULL or tier = 'T0' — never downgrades
    anything already at T1, T2, or T3.
    """
    now_iso = datetime.now(timezone.utc).isoformat()

    promoted = 0
    for profile_name in _PRODUCTION_PROFILES:
        try:
            profile_row = conn.execute(
                text("SELECT id FROM bot_profiles WHERE name = :name"),
                {"name": profile_name},
            ).fetchone()
            if not profile_row:
                logger.debug("[m002] profile not found: %s", profile_name)
                continue

            profile_id = profile_row[0]

            # Only grab allocations still at T0 (or NULL) — never touch T1/T2/T3
            alloc_rows = conn.execute(
                text(
                    "SELECT id FROM bot_allocations "
                    "WHERE profile_id = :pid AND (tier IS NULL OR tier = 'T0')"
                ),
                {"pid": profile_id},
            ).fetchall()

            for (alloc_id,) in alloc_rows:
                conn.execute(
                    text("UPDATE bot_allocations SET tier = 'T2' WHERE id = :id"),
                    {"id": alloc_id},
                )
                conn.execute(
                    text(
                        "INSERT INTO bot_tier_history "
                        "(allocation_id, changed_at, previous_tier, new_tier, "
                        " reason, triggered_by, "
                        " return_30d_pct_at_change, win_rate_at_change, "
                        " max_drawdown_at_change, trade_count_at_change) "
                        "VALUES "
                        "(:aid, :ts, NULL, 'T2', "
                        " 'initial seed — existing production bot', 'manual_seed', "
                        " NULL, NULL, NULL, 0)"
                    ),
                    {"aid": alloc_id, "ts": now_iso},
                )
                promoted += 1
                logger.info("[m002] alloc %d (%s): T0 → T2", alloc_id, profile_name)

        except Exception as exc:
            logger.warning("[m002] failed for %s: %s", profile_name, exc)

    if promoted:
        conn.commit()
        logger.info("[m002] promoted %d allocation(s) to T2", promoted)
    else:
        logger.debug("[m002] no T0 production allocations to promote")
