"""m089 — Halt 4 sim-only crypto quant bleeders; redistribute to broker-real winners.

2026-07-12 audit finding: the crypto sleeve's sim-only quant bots
continue to churn losing trades that never hit Alpaca. Rates as of Sat:

  aggressive:     -$54.54 (-0.75%) on 71 trades — biggest $ loser
  10m:            -$44.67 (-2.29%) on 43 trades — biggest % loser
  universe_top6:  -$43.71 (-2.25%) on 39 trades
  15m:            -$34.65 (-1.78%) on 28 trades
  defi_l2:        -$28.33 (-0.97%) — LEFT ENABLED (borderline, might turn)

Halting the 4 worst frees $13,141 of allocated capital. Redistribute
equal thirds to the three broker-real-fill winners:

  options_directional (+$395 all-time, mleg working)  → +$4,380 → $7,247
  options_income (+$11 all-time, mleg working)        → +$4,381 → $6,328
  stock_quant_day_momentum (+$18 all-time, real fills)→ +$4,380 → $7,300

Net delta = 0. Capital-invariant EXPECTED_SUM_CENTS preserved at
$96,826.70.

Idempotent via _gate.record() AND via data-level checks (won't
double-halt if bots are already at cap=0, won't double-bump if
targets are already at post-bump values).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import bindparam, text

from app.db.migrations._gate import already_ran, record

logger = logging.getLogger(__name__)

_MIGRATION_NAME = "m089_halt_sim_crypto_quants_2026_07_12"
_HALT_REASON = "halt_sim_only_bleeder_2026_07_12"

_HALT_BOTS = [
    "crypto_quant_aggressive",
    "crypto_quant_10m",
    "crypto_quant_15m",
    "crypto_quant_universe_top6",
]

# Redistribute the freed pool ($13,141.10) equally: rounding to preserve
# invariant to the cent.
_BUMP_CENTS = {
    "options_directional":      438_040,  # $4,380.40 → $2,867 → $7,247.40
    "options_income":            438_030,  # $4,380.30 → $1,946.80 → $6,327.10
    "stock_quant_day_momentum":  438_040,  # $4,380.40 → $2,920.20 → $7,300.60
}
# Sum: 438,040 + 438,030 + 438,040 = 1,314,110 cents = $13,141.10 ✓


def run(conn) -> dict:
    if already_ran(conn, _MIGRATION_NAME):
        return {"skipped_reason": "already_applied", "executed": False}

    now_iso = datetime.now(timezone.utc).isoformat()

    # ── 1. HALT the 4 bleeders ────────────────────────────────────────────
    halt_rows = conn.execute(text("""
        SELECT ba.id, bp.name, ba.starting_capital_cents
          FROM bot_allocations ba
          JOIN bot_profiles bp ON bp.id = ba.profile_id
         WHERE ba.user_id = 1 AND bp.name IN :names
    """).bindparams(bindparam("names", expanding=True)),
        {"names": _HALT_BOTS}).fetchall()

    freed_cents = 0
    halted: list[dict] = []
    for r in halt_rows:
        alloc_id = int(r[0])
        name = r[1]
        prior = int(r[2] or 0)
        # Data-level idempotency: only halt if the bot still has capital
        if prior <= 0:
            halted.append({"bot": name, "action": "already_halted",
                           "prior_cents": prior})
            continue
        conn.execute(text(
            "UPDATE bot_allocations "
            "SET enabled = 0, "
            "    starting_capital_cents = 0, "
            "    current_capital_cents = 0, "
            "    paused_reason = :r, "
            "    updated_at = :ts "
            "WHERE id = :aid"
        ), {"r": _HALT_REASON, "ts": now_iso, "aid": alloc_id})
        freed_cents += prior
        halted.append({"bot": name, "action": "halted",
                       "prior_cents": prior, "alloc_id": alloc_id})

    # ── 2. BUMP the winners ──────────────────────────────────────────────
    bumps: list[dict] = []
    total_bumped = 0
    for bot_name, bump_cents in _BUMP_CENTS.items():
        row = conn.execute(text("""
            SELECT ba.id, ba.starting_capital_cents
              FROM bot_allocations ba
              JOIN bot_profiles bp ON bp.id = ba.profile_id
             WHERE ba.user_id = 1 AND bp.name = :n
             LIMIT 1
        """), {"n": bot_name}).fetchone()
        if not row:
            logger.error("[m089] target bot %s not found — skipping bump",
                         bot_name)
            bumps.append({"bot": bot_name, "action": "not_found"})
            continue
        alloc_id = int(row[0])
        current = int(row[1] or 0)
        expected_post = _pre_bump_expected(bot_name) + bump_cents
        # Data-level idempotency: if already at (or past) expected post-bump,
        # skip so re-runs don't double-bump.
        if current >= expected_post:
            bumps.append({"bot": bot_name, "action": "already_bumped",
                          "current_cents": current})
            continue
        new_cents = current + bump_cents
        conn.execute(text(
            "UPDATE bot_allocations "
            "SET starting_capital_cents = :c, "
            "    current_capital_cents = COALESCE(current_capital_cents, 0) + :b, "
            "    updated_at = :ts "
            "WHERE id = :aid"
        ), {"c": new_cents, "b": bump_cents, "ts": now_iso, "aid": alloc_id})
        total_bumped += bump_cents
        bumps.append({"bot": bot_name, "action": "bumped",
                      "old_cents": current, "new_cents": new_cents,
                      "bump_cents": bump_cents, "alloc_id": alloc_id})

    logger.warning(
        "[m089] halted %d bots, freed %d cents; bumped %d winners, total %d cents",
        len(_HALT_BOTS), freed_cents, len(_BUMP_CENTS), total_bumped,
    )
    record(conn, _MIGRATION_NAME)
    return {
        "executed": True,
        "halted": halted,
        "freed_cents": freed_cents,
        "bumps": bumps,
        "total_bumped_cents": total_bumped,
    }


def _pre_bump_expected(bot_name: str) -> int:
    """Value each target held BEFORE m089's bump. Reference points used to
    detect re-runs without depending on schema_migrations."""
    return {
        "options_directional":      286_680,   # $2,866.80 (post-m088)
        "options_income":           194_680,   # $1,946.80
        "stock_quant_day_momentum": 292_020,   # $2,920.20
    }.get(bot_name, 0)
