"""m012 — quarantine misrouted share orders on options bots from 2026-06-19.

Options bots (options_income, options_directional) fired at market open today
and submitted equity bracket orders instead of options orders due to a routing
bug. These are NOT real options positions and must be quarantined.

Idempotent: WHERE quarantined_at IS NULL ensures safe re-runs.
"""
from __future__ import annotations

from sqlalchemy import text

_REASON = "misrouted_share_order_pre_routing_fix"

# Bot names in both old and new naming conventions
_OPTIONS_BOT_NAMES = (
    "options_income",
    "options_directional",
    "equity_income",
    "equity_directional",
)

# Cutoff: 9:30 AM ET on 2026-06-19 = 13:30 UTC (market open, when bad orders fired)
_CUTOFF = "2026-06-19 13:00:00+00"  # use 13:00 to be safe (some fired at ~9:00 AM ET = 13:00 UTC)


def run(conn) -> dict:
    """Quarantine misrouted share-order bot_trades and bot_positions from today."""
    # bot_trades: need to join through bot_allocations → bot_profiles to get bot name
    trades_result = conn.execute(text("""
        UPDATE bot_trades bt
        SET quarantined_at = NOW(),
            quarantine_reason = :reason
        FROM bot_allocations ba
        JOIN bot_profiles bp ON bp.id = ba.profile_id
        WHERE bt.allocation_id = ba.id
          AND bt.quarantined_at IS NULL
          AND bt.opened_at >= :cutoff
          AND bp.name = ANY(:bot_names)
          AND (bt.option_type IS NULL)
    """), {
        "reason": _REASON,
        "cutoff": _CUTOFF,
        "bot_names": list(_OPTIONS_BOT_NAMES),
    })
    trades_count = trades_result.rowcount

    positions_result = conn.execute(text("""
        UPDATE bot_positions bp_pos
        SET quarantined_at = NOW(),
            quarantine_reason = :reason
        FROM bot_allocations ba
        JOIN bot_profiles bp ON bp.id = ba.profile_id
        WHERE bp_pos.allocation_id = ba.id
          AND bp_pos.quarantined_at IS NULL
          AND bp_pos.closed_at IS NULL
          AND bp_pos.opened_at >= :cutoff
          AND bp.name = ANY(:bot_names)
          AND (bp_pos.option_type IS NULL)
    """), {
        "reason": _REASON,
        "cutoff": _CUTOFF,
        "bot_names": list(_OPTIONS_BOT_NAMES),
    })
    positions_count = positions_result.rowcount

    conn.commit()

    import logging
    logging.getLogger(__name__).info(
        "[m012] quarantined %d misrouted trades, %d misrouted positions (reason=%s)",
        trades_count, positions_count, _REASON,
    )
    return {"trades": trades_count, "positions": positions_count}
