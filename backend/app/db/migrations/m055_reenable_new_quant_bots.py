"""m055 — undo m026's damage to the m052/m053 batch allocations.

## What happened

m026_disable_non_spec_allocations runs on EVERY boot (per its own comment:
"intentionally re-runnable in practice — extras can creep back in via
_ensure_portfolios_for_user"). Its SPEC_BOT_NAMES frozenset was hardcoded
to the original 13-bot spec.

m052 (2026-07-01) and m053 (2026-07-02) allocated 8 new bots for user_id=1.
Every one had enabled=1 paper_mode=1 at INSERT. But on the next boot, m026's
sweep saw them as "extras" (not in SPEC_BOT_NAMES) and disabled them all
with paused_reason='m026_non_spec'.

Result: the new bots ran the scanner (scheduler doesn't check enabled), but
scan_and_execute's allocation lookup filters `enabled=True AND paper_mode=True`,
so it found 0 matches → "no allocations (user_id=None)" for every scan.

## What this fixes

1. m026's SPEC_BOT_NAMES now includes all 8 new bots (committed alongside
   this migration). So future boots won't re-disable them.

2. This migration undoes the DAMAGE: for user_id=1 allocations of the 8 new
   bot names where paused_reason='m026_non_spec', flip enabled back to 1
   and clear paused_reason.

Runs on every boot but is idempotent — if no allocations match the m026_non_spec
tag (because they've already been re-enabled), it's a cheap no-op.

## Gate handling

_Not_ gated. m026 sets `paused_reason='m026_non_spec'` on every boot in the
window between "spec list updated" and "this migration lands" — if this
migration were gated it would only fix things once. Idempotent instead.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import text

logger = logging.getLogger(__name__)

_NEW_BOT_NAMES = (
    "crypto_quant_alt_focus", "crypto_quant_scalp_1m", "crypto_dca_btc_eth",
    "crypto_quant_universe_top6", "crypto_quant_defi_l2",
    "crypto_quant_meme_tier", "crypto_quant_10m", "crypto_quant_15m",
)


def run(conn) -> dict:
    """Re-enable m052/m053 batch allocations that m026 disabled."""
    now_iso = datetime.now(timezone.utc).isoformat()

    # Build a placeholder list for the IN clause.
    name_ph = ", ".join(f":n{i}" for i in range(len(_NEW_BOT_NAMES)))
    name_params = {f"n{i}": name for i, name in enumerate(_NEW_BOT_NAMES)}

    # Find candidate allocations: user 1, paused_reason='m026_non_spec',
    # profile is one of the new bots.
    rows = conn.execute(text(f"""
        SELECT a.id, p.name, a.enabled, a.paused_reason
          FROM bot_allocations a
          JOIN bot_profiles p ON p.id = a.profile_id
         WHERE a.user_id = 1
           AND a.paused_reason = 'm026_non_spec'
           AND p.name IN ({name_ph})
    """), name_params).fetchall()

    if not rows:
        return {"skipped_reason": "no_damaged_allocations", "executed": True, "reenabled": 0}

    reenabled: list[str] = []
    for alloc_id, bot_name, _enabled, _paused in rows:
        conn.execute(text("""
            UPDATE bot_allocations
               SET enabled = 1,
                   paused_reason = NULL,
                   updated_at = :now
             WHERE id = :aid
        """), {"aid": alloc_id, "now": now_iso})
        reenabled.append(bot_name)
        logger.warning(
            "[m055] re-enabled alloc_id=%d bot=%s (was disabled by m026)",
            alloc_id, bot_name,
        )

    return {
        "executed": True,
        "reenabled_count": len(reenabled),
        "reenabled_bots": reenabled,
    }
