"""Migration m002: Seed all 12 production bot allocations at Tier 2.

Existing bots shipped before the tier system existed so they landed at T0
CANDIDATE. This migration promotes every allocation whose profile is one of
the 12 production profiles to T2 PRODUCTION and writes a tier-history row
so the audit trail is clean.

Idempotent — guarded by schema_migrations. Safe to run multiple times.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import text

logger = logging.getLogger(__name__)

_MIGRATION_NAME = "m002_seed_bots_t2_v1"

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
    """Promote 12 production bot allocations from T0 → T2. Idempotent."""
    # Guard — skip if already ran
    already = conn.execute(
        text("SELECT 1 FROM schema_migrations WHERE migration_name = :n"),
        {"n": _MIGRATION_NAME},
    ).fetchone()
    if already:
        logger.info("[m002] already ran — skipping")
        return

    now_iso = datetime.now(timezone.utc).isoformat()

    promoted = 0
    for profile_name in _PRODUCTION_PROFILES:
        try:
            # Find the bot_profile id
            profile_row = conn.execute(
                text("SELECT id FROM bot_profiles WHERE name = :name"),
                {"name": profile_name},
            ).fetchone()
            if not profile_row:
                logger.debug("[m002] profile not found: %s", profile_name)
                continue

            profile_id = profile_row[0]

            # Find all allocations for this profile that are still at T0
            alloc_rows = conn.execute(
                text(
                    "SELECT id, tier FROM bot_allocations "
                    "WHERE profile_id = :pid"
                ),
                {"pid": profile_id},
            ).fetchall()

            for alloc_row in alloc_rows:
                alloc_id = alloc_row[0]
                current_tier = alloc_row[1] or "T0"

                # Promote to T2
                conn.execute(
                    text(
                        "UPDATE bot_allocations SET tier = 'T2' "
                        "WHERE id = :id"
                    ),
                    {"id": alloc_id},
                )

                # Record the transition
                conn.execute(
                    text(
                        "INSERT INTO bot_tier_history "
                        "(allocation_id, changed_at, previous_tier, new_tier, "
                        " reason, triggered_by, "
                        " return_30d_pct_at_change, win_rate_at_change, "
                        " max_drawdown_at_change, trade_count_at_change) "
                        "VALUES "
                        "(:alloc_id, :changed_at, :prev, 'T2', "
                        " :reason, 'manual_seed', "
                        " NULL, NULL, NULL, 0)"
                    ),
                    {
                        "alloc_id": alloc_id,
                        "changed_at": now_iso,
                        "prev": current_tier if current_tier != "T0" else None,
                        "reason": "initial seed — existing production bot",
                    },
                )
                promoted += 1
                logger.info("[m002] %s (alloc %d): %s → T2", profile_name, alloc_id, current_tier)

        except Exception as exc:
            logger.warning("[m002] failed for %s: %s", profile_name, exc)

    conn.commit()

    # Record migration as complete
    conn.execute(
        text("INSERT OR IGNORE INTO schema_migrations (migration_name) VALUES (:n)"),
        {"n": _MIGRATION_NAME},
    )
    conn.commit()

    logger.info("[m002] done — promoted %d allocation(s) to T2", promoted)
