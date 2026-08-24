"""m026 — Disable non-spec enabled bot_allocations for user_id=1.

Why this exists:
  m025 reset starting_capital_cents to the 13 SPEC bot names. But production
  has MORE THAN 13 enabled allocations for user_id=1 — Dashboard showed
  "7 Stocks bots, 9 Crypto bots" when spec is 3 + 4. Those 11 extras keep
  their old starting_capital_cents (m025 only UPDATEd the 13 SPEC names),
  so the canonical aggregator sums them in and PV reads $1,696,154 instead
  of $1,000,000.

What this migration does:
  For user_id=1: any enabled bot_allocation whose profile.name is NOT in
  the m025 SPEC set is disabled (enabled=0, paused_reason='m026_non_spec').
  Idempotent: re-running is a no-op once all extras are disabled.

What this migration does NOT do:
  - Does NOT delete rows (preserves audit)
  - Does NOT touch user_id != 1
  - Does NOT close associated positions (clean_slate endpoint handles that)
  - Does NOT update capital amounts (m025 owns that)

Hard-errors if profile_id JOIN can't find any of the 13 SPEC names — that
would mean m025 itself is broken upstream, and m026 has nothing safe to do.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from sqlalchemy import text

logger = logging.getLogger(__name__)

TARGET_USER_ID = 1

# Must mirror the m025 SPEC name set exactly. Do NOT import from m025 to
# keep this migration self-contained at boot.
SPEC_BOT_NAMES = frozenset({
    # Original m025 clean-slate 13 bots
    "stock_swing", "stock_lt", "stock_day",
    "crypto_day", "crypto_swing", "crypto_lt", "crypto_onchain",
    "options_income", "options_directional",
    "crypto_quant_aggressive", "crypto_quant_mean_reversion", "crypto_quant_scalper",
    "cash_floor",
    # 2026-07-01 m052 batch (3 new quant bots)
    "crypto_quant_alt_focus", "crypto_quant_scalp_1m", "crypto_dca_btc_eth",
    # 2026-07-02 m053 batch (5 more quant bots)
    "crypto_quant_universe_top6", "crypto_quant_defi_l2",
    "crypto_quant_meme_tier", "crypto_quant_10m", "crypto_quant_15m",
    # 2026-07-02 m056 batch (4 quant stock bots)
    "stock_quant_day_momentum", "stock_quant_day_meanrev",
    "stock_quant_swing_growth", "stock_quant_swing_value",
    # 2026-07-02 Brock table (m057)
    "stock_gap_fade", "stock_orb_breakout",
    "stock_momentum_breakout", "stock_pead",
    # 2026-07-12 fleet expansion (previously being stomped every boot):
    #   tsmom_multi_asset     — Moskowitz-Ooi-Pedersen 2012 TSMOM (m081)
    #   macro_faber_gtaa      — Faber Global Tactical Asset Alloc (m072)
    #   spy_iron_condor_weekly — options_income sibling (m072)
    "tsmom_multi_asset",
    "macro_faber_gtaa",
    "spy_iron_condor_weekly",
    # 2026-08-24 post-strategic-reset (m102 confluence framework):
    #   confluence_executor — auto-fires bracket orders on ARMED
    #   confluence_picks. Post-2026-08-21 reset this is the ONLY funded
    #   allocation ($10K). m026 was stomping it on every boot (setting
    #   paused_reason='m026_non_spec') — full-audit 2026-08-24 caught it.
    "confluence_executor",
})
# NOTE: this frozenset is the "known-good bot names" for the fund's
# user_id=1 allocations. m026 runs EVERY boot (not just once) — it disables
# any allocation whose profile name isn't in this set. Adding a new
# production bot? Add its name here first or m026 will silently disable it
# on the next deploy (which is exactly what happened to m052/m053 batches
# on 2026-07-02).

_MIGRATION_NAME = "m026_disable_non_spec_allocations"


def _table_exists(conn, table: str) -> bool:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall() or []
    return bool(rows)


def _migration_already_ran(conn, name: str) -> bool:
    try:
        result = conn.execute(
            text("SELECT 1 FROM schema_migrations WHERE migration_name = :n"),
            {"n": name},
        ).fetchone()
        return result is not None
    except Exception:
        return False


def _record_migration(conn, name: str) -> None:
    conn.execute(
        text(
            "INSERT INTO schema_migrations (migration_name) VALUES (:n)"
            " ON CONFLICT (migration_name) DO NOTHING"
        ),
        {"n": name},
    )
    conn.commit()


def run(conn) -> dict:
    """Disable non-spec enabled allocations for user 1. Idempotent."""
    migration_start_iso = datetime.now(timezone.utc).isoformat()

    if _migration_already_ran(conn, _MIGRATION_NAME):
        # NOTE: this migration is intentionally re-runnable in practice
        # (extras can creep back in via _ensure_portfolios_for_user — vault
        # known-issue #3). The schema_migrations row records the FIRST run.
        # On every subsequent boot the run() body still executes and is a
        # no-op if there are no extras to disable.
        logger.info("[m026] schema_migrations row present — running idempotent sweep anyway")

    if not _table_exists(conn, "bot_allocations"):
        return {"skipped_reason": "missing_table_bot_allocations", "executed": False}
    if not _table_exists(conn, "bot_profiles"):
        return {"skipped_reason": "missing_table_bot_profiles", "executed": False}

    # Find enabled allocations for user 1 whose profile name is NOT in SPEC.
    rows = conn.execute(
        text("""
            SELECT a.id, p.name, a.starting_capital_cents
              FROM bot_allocations a
              JOIN bot_profiles p ON p.id = a.profile_id
             WHERE a.user_id = :uid
               AND a.enabled = 1
        """),
        {"uid": TARGET_USER_ID},
    ).fetchall()

    extras = [(int(r[0]), r[1], int(r[2] or 0)) for r in rows if r[1] not in SPEC_BOT_NAMES]
    spec_present = {r[1] for r in rows if r[1] in SPEC_BOT_NAMES}

    if not spec_present:
        raise RuntimeError(
            "[m026] no SPEC bot names found among enabled allocations for user 1 — "
            "m025 must have failed or the schema is unexpected; refusing to proceed"
        )

    extras_cents_total = sum(c for _, _, c in extras)

    # Disable each extra.
    disabled_details: list[dict] = []
    for alloc_id, name, cents in extras:
        conn.execute(
            text("""
                UPDATE bot_allocations
                   SET enabled = 0,
                       paused_reason = 'm026_non_spec',
                       updated_at = CURRENT_TIMESTAMP
                 WHERE id = :id
                   AND user_id = :uid
            """),
            {"id": alloc_id, "uid": TARGET_USER_ID},
        )
        disabled_details.append({
            "alloc_id": alloc_id,
            "name": name,
            "previous_starting_cents": cents,
        })

    conn.commit()

    # Multi-user safety probe.
    other_users_touched = conn.execute(
        text("""
            SELECT COUNT(*) FROM bot_allocations
             WHERE user_id != :uid
               AND updated_at >= :ts
        """),
        {"uid": TARGET_USER_ID, "ts": migration_start_iso},
    ).fetchone()[0]

    if other_users_touched != 0:
        raise RuntimeError(
            f"[m026] multi-user safety violation: {other_users_touched} rows outside user_id=1 "
            f"updated at or after {migration_start_iso}"
        )

    # Acceptance gate: post-sweep, every enabled allocation for user 1 is in SPEC.
    leftovers = conn.execute(
        text("""
            SELECT p.name FROM bot_allocations a
              JOIN bot_profiles p ON p.id = a.profile_id
             WHERE a.user_id = :uid AND a.enabled = 1
        """),
        {"uid": TARGET_USER_ID},
    ).fetchall()
    bad = [r[0] for r in leftovers if r[0] not in SPEC_BOT_NAMES]
    if bad:
        raise RuntimeError(
            f"[m026] post-sweep verification failed: still-enabled non-SPEC names: {bad}"
        )

    _record_migration(conn, _MIGRATION_NAME)

    result = {
        "executed": True,
        "user_id": TARGET_USER_ID,
        "extras_disabled": len(extras),
        "extras_cents_total": extras_cents_total,
        "extras_dollars_total": extras_cents_total / 100,
        "spec_present_count": len(spec_present),
        "spec_missing": sorted(SPEC_BOT_NAMES - spec_present),
        "details": disabled_details,
        "other_users_touched": int(other_users_touched),
    }
    logger.warning(
        "[m026] executed=True · extras_disabled=%d · extras_dollars=%.2f"
        " · spec_present=%d · other_users_touched=%d",
        len(extras), extras_cents_total / 100, len(spec_present), int(other_users_touched),
    )
    return result
