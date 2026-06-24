"""Migration m010: Quarantine legacy options-bot positions created before fix 17aa7f3.

All open positions in options_income + options_directional that were created
BEFORE the reason-nesting bug was fixed are corrupted:
  - Positions with option_type IS NULL are literal share positions (58 found).
  - Positions with strike_price <= 100 have fallback dummy values because
    spot=0 (reason JSON couldn't be parsed), causing strike = spot * 0.95 = 95.

Date predicate: only quarantine positions opened BEFORE the 17aa7f3 deploy
went live. The fix was authored 2026-06-18 22:06:06 -0500 = 2026-06-19
03:06:06 UTC; using a 10-minute buffer (03:16:00 UTC) to cover build +
healthcheck + DNS-flip lag. Anything opened at/after that timestamp ran
the post-fix code path with real strike/premium data and MUST NOT be
re-quarantined on subsequent deploys — without the date filter this
migration ran on every boot and ate fresh legitimate trades (76 rows of
collateral damage by 2026-06-23).

Quarantine reason: 'misclassified_legacy_pre_17aa7f3' — excluded from
P&L, Activity Feed, and bot detail pages without deleting the audit trail.

Idempotent: only touches rows where quarantined_at IS NULL AND closed_at IS NULL
AND opened_at < the cutoff. Once all legacy rows are sealed, subsequent
boots are no-ops.
"""
from __future__ import annotations

import logging
from sqlalchemy import text

logger = logging.getLogger(__name__)

# 17aa7f3 deploy cutoff: commit at 2026-06-19 03:06:06 UTC + 10 min build/deploy lag.
# Positions opened at or after this point used the post-fix code path.
_LEGACY_CUTOFF_UTC = "2026-06-19 03:16:00"


def run(conn) -> None:
    try:
        result = conn.execute(
            text("""
                UPDATE bot_positions
                SET
                    quarantined_at    = CURRENT_TIMESTAMP,
                    quarantine_reason = 'misclassified_legacy_pre_17aa7f3'
                WHERE quarantined_at IS NULL
                  AND closed_at IS NULL
                  AND opened_at < :cutoff
                  AND allocation_id IN (
                    SELECT ba.id
                    FROM bot_allocations ba
                    JOIN bot_profiles bp ON bp.id = ba.profile_id
                    WHERE bp.name IN ('options_income', 'options_directional')
                  )
            """),
            {"cutoff": _LEGACY_CUTOFF_UTC},
        )
        conn.commit()
        count = getattr(result, "rowcount", None)
        if count:
            logger.warning(
                "[m010] Quarantined %d legacy options-bot positions opened before %s (misclassified_legacy_pre_17aa7f3)",
                count, _LEGACY_CUTOFF_UTC,
            )
        else:
            logger.info(
                "[m010] No unquarantined legacy options positions opened before %s — already clean",
                _LEGACY_CUTOFF_UTC,
            )
    except Exception as exc:
        logger.warning("[m010] quarantine migration failed (non-fatal): %s", exc)
        try:
            conn.rollback()
        except Exception:
            pass
