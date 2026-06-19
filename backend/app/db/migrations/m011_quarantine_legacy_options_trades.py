"""Migration m011: Quarantine legacy fake-options trades in bot_trades.

All trades in options_income + options_directional where option_type IS NULL
are share positions mislabeled as options contracts — created before the
reason-nesting bug fix (commit 17aa7f3). Quarantine them so they disappear
from the Activity Feed, trade detail pages, and portfolio P&L without
deleting the audit trail.

Also catches any open bot_positions rows not caught by m010 (should be 0,
but runs idempotently as a safety net).

Idempotent: only touches rows where quarantined_at IS NULL.
"""
from __future__ import annotations

import logging
from sqlalchemy import text

logger = logging.getLogger(__name__)

_REASON = "legacy_fake_options_pre_17aa7f3"

_OPTIONS_BOTS_SUBQUERY = """
    SELECT ba.id
    FROM bot_allocations ba
    JOIN bot_profiles bp ON bp.id = ba.profile_id
    WHERE bp.name IN ('options_income', 'options_directional')
"""


def run(conn) -> None:
    try:
        # Quarantine bot_trades rows (share fills mislabeled as options contracts)
        r_trades = conn.execute(text(f"""
            UPDATE bot_trades
            SET
                quarantined_at    = CURRENT_TIMESTAMP,
                quarantine_reason = :reason
            WHERE quarantined_at IS NULL
              AND option_type IS NULL
              AND allocation_id IN ({_OPTIONS_BOTS_SUBQUERY})
        """), {"reason": _REASON})
        conn.commit()
        trades_count = getattr(r_trades, "rowcount", None) or 0
        if trades_count:
            logger.warning(
                "[m011] Quarantined %d legacy fake-options bot_trades rows (%s)",
                trades_count, _REASON,
            )
        else:
            logger.info("[m011] bot_trades: no unquarantined legacy rows — already clean")
    except Exception as exc:
        logger.warning("[m011] bot_trades quarantine failed (non-fatal): %s", exc)
        try:
            conn.rollback()
        except Exception:
            pass

    try:
        # Safety net: catch any open positions missed by m010
        r_pos = conn.execute(text(f"""
            UPDATE bot_positions
            SET
                quarantined_at    = CURRENT_TIMESTAMP,
                quarantine_reason = :reason
            WHERE quarantined_at IS NULL
              AND closed_at IS NULL
              AND option_type IS NULL
              AND allocation_id IN ({_OPTIONS_BOTS_SUBQUERY})
        """), {"reason": _REASON})
        conn.commit()
        pos_count = getattr(r_pos, "rowcount", None) or 0
        if pos_count:
            logger.warning(
                "[m011] Quarantined %d additional legacy bot_positions rows (%s)",
                pos_count, _REASON,
            )
        else:
            logger.info("[m011] bot_positions: no additional rows — m010 already handled them")
    except Exception as exc:
        logger.warning("[m011] bot_positions quarantine failed (non-fatal): %s", exc)
        try:
            conn.rollback()
        except Exception:
            pass
