"""Migration m004: Seed system-level bot allocations for every production profile.

Problem: bot_scheduler jobs call run_bot_profile() / scan_and_execute() which
both require at least one enabled paper BotAllocation row to proceed. Without it,
every bot silently returns {"skipped": True, "reason": "no enabled paper allocations"}.

Fix: for each production bot profile, if no BotAllocation exists at all, create
one tied to the first admin user (fallback: first user in the users table).

This is idempotent — it only inserts where no allocation exists.
Runs every startup from app/main.py lifespan.
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
    "options_income",
    "options_directional",
    "crypto_quant_aggressive",
    "crypto_quant_scalper",
    "crypto_quant_mean_reversion",
    # T0 incubation bots intentionally excluded — m004_pause_t0_violations handles them.
    # Including them here would create enabled=True allocations on fresh DBs since
    # pause migration runs first but has nothing to pause.
    # "tsmom_multi_asset", "quality_factor", "value_quality", "crypto_meanrev_2163"
]

# Starting capital per bot: $100,000 = 10_000_000 cents
_DEFAULT_CAPITAL_CENTS = 10_000_000


def run(conn) -> None:
    """Create missing system paper allocations. Safe to run multiple times."""

    # 1. Find the system user (admin preferred, fallback first user)
    try:
        admin_row = conn.execute(
            text("SELECT id FROM users WHERE is_admin = 1 OR is_admin = TRUE ORDER BY id LIMIT 1")
        ).fetchone()
        if not admin_row:
            admin_row = conn.execute(text("SELECT id FROM users ORDER BY id LIMIT 1")).fetchone()
        if not admin_row:
            logger.warning("[m004] No users found — skipping system allocation seed")
            return
        system_user_id = admin_row[0]
        logger.info("[m004] Using system_user_id=%d for bot allocations", system_user_id)
    except Exception as exc:
        logger.warning("[m004] Cannot determine system user: %s — aborting", exc)
        return

    now_iso = datetime.now(timezone.utc).isoformat()
    created = 0

    for profile_name in _PRODUCTION_PROFILES:
        try:
            # Get profile id
            profile_row = conn.execute(
                text("SELECT id FROM bot_profiles WHERE name = :name"),
                {"name": profile_name},
            ).fetchone()
            if not profile_row:
                logger.debug("[m004] profile not in DB yet: %s — skip", profile_name)
                continue

            profile_id = profile_row[0]

            # Check if any allocation already exists for this profile
            existing = conn.execute(
                text("SELECT id FROM bot_allocations WHERE profile_id = :pid LIMIT 1"),
                {"pid": profile_id},
            ).fetchone()
            if existing:
                logger.debug("[m004] %s already has allocation — skip", profile_name)
                continue

            # Create the system allocation
            conn.execute(
                text("""
                    INSERT INTO bot_allocations
                        (user_id, profile_id, capital_pct, risk_profile, paper_mode,
                         enabled, starting_capital_cents, tier, created_at, updated_at)
                    VALUES
                        (:user_id, :profile_id, 10.0, 'standard', 1,
                         1, :capital_cents, 'T2', :now, :now)
                """),
                {
                    "user_id":       system_user_id,
                    "profile_id":    profile_id,
                    "capital_cents": _DEFAULT_CAPITAL_CENTS,
                    "now":           now_iso,
                },
            )
            conn.commit()
            created += 1
            logger.info(
                "[m004] Created system allocation for %s (user=%d, $100k paper)",
                profile_name, system_user_id,
            )

        except Exception as exc:
            logger.warning("[m004] Failed to seed allocation for %s: %s", profile_name, exc)
            try:
                conn.rollback()
            except Exception:
                pass

    if created:
        logger.warning("[m004] Seeded %d system bot allocations — bots should now fire", created)
    else:
        logger.info("[m004] All bot allocations already present — no action needed")
