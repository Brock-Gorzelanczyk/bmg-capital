"""Migration m010: Quarantine legacy options-bot positions created before fix 17aa7f3.

All open positions in options_income + options_directional that were created
before the reason-nesting bug was fixed are corrupted:
  - Positions with option_type IS NULL are literal share positions (58 found).
  - Positions with strike_price <= 100 have fallback dummy values because
    spot=0 (reason JSON couldn't be parsed), causing strike = spot * 0.95 = 95.

All 63 open positions are quarantined with reason
'misclassified_legacy_pre_17aa7f3' so they are excluded from P&L, the
Activity Feed, and bot detail pages without deleting the audit trail.

Idempotent: only touches rows where quarantined_at IS NULL AND closed_at IS NULL.
"""
from __future__ import annotations

import logging
from sqlalchemy import text

logger = logging.getLogger(__name__)


def run(conn) -> None:
    try:
        result = conn.execute(text("""
            UPDATE bot_positions
            SET
                quarantined_at    = CURRENT_TIMESTAMP,
                quarantine_reason = 'misclassified_legacy_pre_17aa7f3'
            WHERE quarantined_at IS NULL
              AND closed_at IS NULL
              AND allocation_id IN (
                SELECT ba.id
                FROM bot_allocations ba
                JOIN bot_profiles bp ON bp.id = ba.profile_id
                WHERE bp.name IN ('options_income', 'options_directional')
              )
        """))
        conn.commit()
        count = getattr(result, "rowcount", None)
        if count:
            logger.warning(
                "[m010] Quarantined %d legacy options-bot positions (misclassified_legacy_pre_17aa7f3)",
                count,
            )
        else:
            logger.info("[m010] No unquarantined legacy options positions found — already clean")
    except Exception as exc:
        logger.warning("[m010] quarantine migration failed (non-fatal): %s", exc)
        try:
            conn.rollback()
        except Exception:
            pass
