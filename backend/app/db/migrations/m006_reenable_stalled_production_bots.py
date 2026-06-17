"""Migration m006: Re-enable disabled allocations for non-T0 production bots.

Problem: Several production bots (crypto_day, stock_swing, stock_day, etc.) have
BotAllocation rows that are enabled=False and/or paper_mode=False. The runner
requires enabled=True AND paper_mode=True to execute scans. With all allocations
disabled, the bot logs "SKIP no enabled paper allocations" on every cycle and
never produces signals — causing the health dashboard to show RED indefinitely.

Root cause: Allocations were disabled by the health_watchdog or another mechanism
but were never re-enabled after the underlying issue was fixed. The _ensure_
portfolios_for_user() auto-re-enable only runs when the portfolios page is loaded.

Fix: For each non-T0 production bot, re-enable any allocation that was NOT
paused for a hard reason (health_halt, admin_lock, T0_tier_violation_auto_pause).
Also sets paper_mode=True if it was inadvertently set to False.

Idempotent — safe to run every startup. Never touches T0 incubation bots.
Never touches allocations paused for health_halt or admin_lock.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import text

logger = logging.getLogger(__name__)

# Non-T0 production bots only — T0 bots handled exclusively by m004_pause_t0_violations
_PRODUCTION_PROFILES = [
    "stock_swing",
    "stock_day",
    "stock_lt",
    "crypto_swing",
    "crypto_day",
    "crypto_lt",
    "crypto_onchain",
    "options_income",
    "options_directional",
    "crypto_quant_aggressive",
    "crypto_quant_scalper",
    "crypto_quant_mean_reversion",
]

# These pause reasons indicate intentional halts — do not override
_HARD_PAUSE_REASONS = {"health_halt", "admin_lock", "T0_tier_violation_auto_pause", "admin_freeze_bleed"}


def run(conn) -> None:
    now_iso = datetime.now(timezone.utc).isoformat()
    reenabled = 0

    for profile_name in _PRODUCTION_PROFILES:
        try:
            profile_row = conn.execute(
                text("SELECT id FROM bot_profiles WHERE name = :name"),
                {"name": profile_name},
            ).fetchone()
            if not profile_row:
                continue
            profile_id = profile_row[0]

            # Find all disabled OR non-paper allocations for this profile
            alloc_rows = conn.execute(
                text(
                    "SELECT id, enabled, paper_mode, paused_reason "
                    "FROM bot_allocations "
                    "WHERE profile_id = :pid "
                    "  AND (enabled = 0 OR paper_mode = 0)"
                ),
                {"pid": profile_id},
            ).fetchall()

            for row in alloc_rows:
                alloc_id, enabled, paper_mode, paused_reason = row
                # Skip if paused for a hard reason
                if paused_reason in _HARD_PAUSE_REASONS:
                    logger.debug(
                        "[m006] %s alloc=%d skipped — hard pause reason: %s",
                        profile_name, alloc_id, paused_reason,
                    )
                    continue

                conn.execute(
                    text(
                        "UPDATE bot_allocations "
                        "SET enabled = 1, paper_mode = 1, paused_reason = NULL, updated_at = :now "
                        "WHERE id = :id"
                    ),
                    {"id": alloc_id, "now": now_iso},
                )
                reenabled += 1
                logger.info(
                    "[m006] re-enabled alloc=%d (%s) — was enabled=%s paper_mode=%s paused_reason=%s",
                    alloc_id, profile_name, enabled, paper_mode, paused_reason,
                )

        except Exception as exc:
            logger.warning("[m006] failed for %s: %s", profile_name, exc)

    if reenabled:
        conn.commit()
        logger.info("[m006] done — re-enabled %d allocation(s) for production bots", reenabled)
    else:
        logger.info("[m006] done — all production bot allocations already active")
