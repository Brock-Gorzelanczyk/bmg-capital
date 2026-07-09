"""m085 — Halt crypto_quant_scalp_1m and crypto_quant_meme_tier.

Both are structural bleeders per 2026-07-09 audit:
  - crypto_quant_scalp_1m: 563 trades in 7 days, -$80.56 (-4.14%). Sim-only.
  - crypto_quant_meme_tier: 42 trades in 7 days, -$163.34 (-16.78%). Sim-only.

Freeing ~$2,920 of allocated capital for SSRN batch 5 bots (short-term
momentum, cw vol spread, earnings straddle) shipped in m086-m088.

Sets enabled=false, zeros starting_capital_cents (redistributed via
existing invariant reconciliation on next boot), and marks
paused_reason for audit trail. Companion to m051 halt pattern.

Idempotent via _gate.record().
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.db.migrations._gate import already_ran, record

logger = logging.getLogger(__name__)

_MIGRATION_NAME = "m085_halt_scalp_meme_bleeders_2026_07_09"
_HALT_REASON = "halt_bleeding_pre_ssrn_batch_5_2026_07_09"
_BOTS = ["crypto_quant_scalp_1m", "crypto_quant_meme_tier"]


def run(conn) -> dict:
    if already_ran(conn, _MIGRATION_NAME):
        return {"skipped_reason": "already_applied", "executed": False}

    now_iso = datetime.now(timezone.utc).isoformat()

    rows = conn.execute(text("""
        SELECT ba.id, bp.name, ba.enabled, ba.starting_capital_cents
          FROM bot_allocations ba
          JOIN bot_profiles bp ON bp.id = ba.profile_id
         WHERE ba.user_id = 1 AND bp.name IN :names
    """).bindparams(
        __import__("sqlalchemy").bindparam("names", expanding=True)
    ), {"names": _BOTS}).fetchall()

    halted: list[dict] = []
    freed_cents = 0
    for r in rows:
        alloc_id = int(r[0])
        name = r[1]
        was_enabled = bool(r[2])
        prior_cents = int(r[3] or 0)
        conn.execute(text(
            "UPDATE bot_allocations "
            "SET enabled = 0, "
            "    starting_capital_cents = 0, "
            "    current_capital_cents = 0, "
            "    paused_reason = :r, "
            "    updated_at = :ts "
            "WHERE id = :aid"
        ), {"r": _HALT_REASON, "ts": now_iso, "aid": alloc_id})
        halted.append({
            "alloc_id": alloc_id,
            "bot": name,
            "was_enabled": was_enabled,
            "prior_cents": prior_cents,
        })
        freed_cents += prior_cents

    if hasattr(conn, "commit"):
        conn.commit()

    verify = conn.execute(text("""
        SELECT COUNT(*)
          FROM bot_allocations ba
          JOIN bot_profiles bp ON bp.id = ba.profile_id
         WHERE ba.user_id = 1 AND bp.name IN :names
           AND ba.enabled = 1
    """).bindparams(
        __import__("sqlalchemy").bindparam("names", expanding=True)
    ), {"names": _BOTS}).fetchone()
    still_enabled = int(verify[0] or 0) if verify else -1

    if still_enabled != 0:
        logger.error(
            "[m085] verify failed: %d bot(s) still enabled — NOT recording",
            still_enabled,
        )
        return {
            "executed": False,
            "error": "verify_failed",
            "halted": halted,
            "still_enabled": still_enabled,
        }

    logger.warning(
        "[m085] halted %d bots (%s), freed %d cents ($%.2f) for SSRN batch 5",
        len(halted), [h["bot"] for h in halted], freed_cents, freed_cents / 100.0,
    )
    record(conn, _MIGRATION_NAME)
    return {
        "executed": True,
        "halted": halted,
        "freed_cents": freed_cents,
        "freed_dollars": freed_cents / 100.0,
    }
