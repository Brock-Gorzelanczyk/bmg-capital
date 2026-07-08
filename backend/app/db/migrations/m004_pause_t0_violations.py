"""Migration m004: Pause T0 bot allocations that incorrectly received live capital.

Idempotent — safe to run every startup. Targets crypto_meanrev_2163 specifically
(a T0 incubation bot that was included in the quant portfolio _PORTFOLIO_DEFS and
therefore received $30k paper capital, causing -8.26% drawdown before discovery).

Also demotes any allocation for a non-production bot profile that somehow reached
T2+ tier — these are reclassified to T0 and paused.

Root cause of the bug: bots.py _PORTFOLIO_DEFS included crypto_meanrev_2163 in the
quant sleeve. _ensure_portfolios_for_user() creates allocations for every entry in
that dict, bypassing the tier system entirely. Fix: removed from _PORTFOLIO_DEFS.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import text

logger = logging.getLogger(__name__)

_T0_INCUBATION_PROFILES = [
    "crypto_meanrev_2163",
    "earnings_nlp",
    "quality_factor",
    # 2026-07-08: tsmom_multi_asset promoted to production in m081 (SSRN batch
    # 4). Removed from T0 pause list so m004 stops re-pausing it every restart.
    "value_quality",
]

_PRODUCTION_PROFILES = {
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
}


def run(conn) -> None:
    """Pause incubation bot allocations; demote any non-production bots at T2+."""
    now_iso = datetime.now(timezone.utc).isoformat()
    paused = 0
    demoted = 0

    for profile_name in _T0_INCUBATION_PROFILES:
        try:
            profile_row = conn.execute(
                text("SELECT id FROM bot_profiles WHERE name = :name"),
                {"name": profile_name},
            ).fetchone()
            if not profile_row:
                logger.debug("[m004] profile not found: %s", profile_name)
                continue

            # Pause all enabled allocations for this profile
            alloc_rows = conn.execute(
                text(
                    "SELECT id, tier FROM bot_allocations "
                    "WHERE profile_id = :pid"
                ),
                {"pid": profile_row[0]},
            ).fetchall()

            for (alloc_id, tier) in alloc_rows:
                conn.execute(
                    text(
                        "UPDATE bot_allocations "
                        "SET enabled = 0, "
                        "    paused_reason = 'T0_tier_violation_auto_pause' "
                        "WHERE id = :id AND (enabled = 1 OR enabled IS NULL)"
                    ),
                    {"id": alloc_id},
                )
                paused += 1
                logger.warning(
                    "[m004] paused alloc %d (%s, was tier=%s) — T0 incubation bots must not receive capital",
                    alloc_id, profile_name, tier,
                )

                # If the tier was wrongly elevated, force back to T0
                if tier and tier not in ("T0", None):
                    conn.execute(
                        text("UPDATE bot_allocations SET tier = 'T0' WHERE id = :id"),
                        {"id": alloc_id},
                    )
                    try:
                        conn.execute(
                            text(
                                "INSERT INTO bot_tier_history "
                                "(allocation_id, changed_at, previous_tier, new_tier, "
                                " reason, triggered_by, return_30d_pct_at_change, "
                                " win_rate_at_change, max_drawdown_at_change, trade_count_at_change) "
                                "VALUES (:aid, :ts, :prev, 'T0', "
                                " 'm004_auto_demotion — T0 incubation bot must not hold T2+ tier', "
                                " 'system_migration', NULL, NULL, NULL, 0)"
                            ),
                            {"aid": alloc_id, "ts": now_iso, "prev": tier},
                        )
                    except Exception:
                        pass
                    demoted += 1
                    logger.warning(
                        "[m004] demoted alloc %d (%s): %s → T0", alloc_id, profile_name, tier,
                    )

        except Exception as exc:
            logger.warning("[m004] failed for %s: %s", profile_name, exc)

    if paused or demoted:
        conn.commit()
        logger.warning("[m004] complete — paused=%d demoted=%d allocations", paused, demoted)
    else:
        logger.debug("[m004] no T0-violation allocations found")
