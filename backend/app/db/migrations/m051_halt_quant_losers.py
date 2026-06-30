"""m051 — Halt scanners for confirmed-loser Quant bots.

2026-06-30 incident: leaderboard audit confirmed two bots actively bleeding —

  crypto_quant_mean_reversion:  -1.30% all-time, -$1,126 today
  crypto_quant_scalper:         -2.71% all-time, +$700 today (recovering but
                                still net negative)

Diagnosis (per Brock's strategy investigation):
  - 5-min crypto mean reversion is structurally weak (most 5m moves are noise,
    Bollinger 2.5σ fires usually mark momentum impulses worth following, not
    fading). 4-hour max hold + 1.25:1 R:R is mathematically losing once
    slippage is included.
  - 1-min crypto scalping with Alpaca paper feed suffers systematic adverse
    selection vs co-located HFT, plus 8-15bps round-trip slippage on a 0.5%
    stop / 1.0% target eats the edge.
  - The 2026-06-24 "deployment push" (composite_threshold dropped from 60 to
    50, position size override 25, max_concurrent 5) loosened risk AND
    increased size simultaneously — worst combination when edge isn't proven.

Action: set enabled=false on both bots and stamp paused_reason for audit.
Capital allocation is PRESERVED (starting_capital_cents untouched) so the
bots can be re-enabled later if/when their replacement strategies are ready.
Open positions exit naturally via existing stop/take-profit/time-based exits
(MR hold_max_hours=4, Scalper hold_max_minutes=30) so no forced market sells.

Gated via _gate.already_ran so the operator can re-enable later without the
migration silently flipping them back on the next boot.
"""
from __future__ import annotations

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)

_MIGRATION_NAME = "m051_halt_quant_losers_2026_06_30"
_PAUSED_REASON = "halt_2026_06_30_underperformance"
_TARGET_BOTS = ("crypto_quant_mean_reversion", "crypto_quant_scalper")


def run(conn) -> dict:
    """Halt scanners for the two confirmed-loser Quant bots. Idempotent via _gate."""
    from app.db.migrations._gate import already_ran, record

    if already_ran(conn, _MIGRATION_NAME):
        return {"skipped_reason": "already_applied", "executed": False}

    affected: dict[str, int] = {}
    for bot_name in _TARGET_BOTS:
        result = conn.execute(
            text(
                "UPDATE bot_allocations SET enabled = 0, paused_reason = :reason "
                "WHERE profile_id IN (SELECT id FROM bot_profiles WHERE name = :name) "
                "  AND enabled = 1"
            ),
            {"reason": _PAUSED_REASON, "name": bot_name},
        )
        affected[bot_name] = result.rowcount or 0
        logger.warning(
            "[m051] halted bot=%s rows_affected=%d paused_reason=%s",
            bot_name,
            affected[bot_name],
            _PAUSED_REASON,
        )

    record(conn, _MIGRATION_NAME)
    return {
        "executed": True,
        "affected": affected,
        "paused_reason": _PAUSED_REASON,
    }
