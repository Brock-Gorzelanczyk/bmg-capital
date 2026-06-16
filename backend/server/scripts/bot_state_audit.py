#!/usr/bin/env python3
"""
Bot state audit + immediate pause for T0 violators.

Run in Railway shell:
  railway run python backend/server/scripts/bot_state_audit.py

Outputs:
  1. Per-allocation state (enabled, tier, paused_reason, capital)
  2. Last signal timestamp per bot (last 24h signal count)
  3. Immediately pauses crypto_meanrev_2163 if still active
  4. Confirms options_income / options_directional allocation existence
"""
from __future__ import annotations
import os, sys
from datetime import datetime, timezone, timedelta

db_url = os.getenv("DATABASE_URL")
if not db_url:
    print("ERROR: DATABASE_URL not set — run inside Railway shell")
    sys.exit(1)

from sqlalchemy import create_engine, text
engine = create_engine(db_url)

ALL_BOTS = [
    "stock_swing", "stock_day", "stock_lt",
    "crypto_swing", "crypto_day", "crypto_lt", "crypto_onchain",
    "crypto_quant_aggressive", "crypto_quant_scalper", "crypto_quant_mean_reversion",
    "options_income", "options_directional",
    "crypto_meanrev_2163",
    "earnings_nlp", "quality_factor", "tsmom_multi_asset", "value_quality",
]

with engine.connect() as conn:
    now = datetime.now(timezone.utc)
    cutoff_24h = (now - timedelta(hours=24)).isoformat()

    # ── 1. IMMEDIATE PAUSE: crypto_meanrev_2163 ───────────────────────────────
    print("\n" + "="*70)
    print("A. IMMEDIATE PAUSE — crypto_meanrev_2163")
    print("="*70)

    mr_profile = conn.execute(text(
        "SELECT id, enabled FROM bot_profiles WHERE name = 'crypto_meanrev_2163'"
    )).fetchone()

    if not mr_profile:
        print("  WARN: profile not in DB yet — seeds haven't run")
    else:
        mr_pid, mr_enabled = mr_profile
        print(f"  BotProfile.enabled = {mr_enabled}")

        mr_allocs = conn.execute(text("""
            SELECT id, user_id, enabled, tier, paused_reason,
                   starting_capital_cents, capital_cents_within_portfolio
            FROM bot_allocations WHERE profile_id = :pid
        """), {"pid": mr_pid}).fetchall()

        if not mr_allocs:
            print("  No allocations — bot never received capital. SAFE.")
        else:
            for row in mr_allocs:
                aid, uid, enabled, tier, paused_reason, cap_cents, port_cents = row
                cap_usd = (cap_cents or port_cents or 0) / 100
                print(f"  alloc_id={aid} user_id={uid} tier={tier} enabled={enabled} "
                      f"paused_reason={paused_reason!r} capital=${cap_usd:,.0f}")

                if enabled:
                    conn.execute(text("""
                        UPDATE bot_allocations
                        SET enabled = FALSE,
                            paused_reason = 'T0_tier_violation_manual_pause_script'
                        WHERE id = :id
                    """), {"id": aid})
                    print(f"  >>> PAUSED alloc_id={aid} RIGHT NOW")
                else:
                    print(f"  >>> Already disabled (paused_reason={paused_reason!r})")
            conn.commit()

    # ── 2. PER-BOT ALLOCATION STATE ──────────────────────────────────────────
    print("\n" + "="*70)
    print("B. PER-BOT ALLOCATION STATE")
    print("="*70)
    print(f"{'bot_id':<35} {'alloc_id':>8} {'tier':>4} {'enabled':>7} {'capital':>10} {'paused_reason'}")
    print("-"*90)

    for bot in ALL_BOTS:
        row = conn.execute(text(
            "SELECT id FROM bot_profiles WHERE name = :n"
        ), {"n": bot}).fetchone()
        if not row:
            print(f"  {bot:<35} NO PROFILE IN DB")
            continue
        pid = row[0]
        allocs = conn.execute(text("""
            SELECT id, tier, enabled, paused_reason,
                   starting_capital_cents, capital_cents_within_portfolio
            FROM bot_allocations WHERE profile_id = :pid
        """), {"pid": pid}).fetchall()
        if not allocs:
            print(f"  {bot:<35} NO ALLOCATION — not seeded for this user")
            continue
        for a in allocs:
            aid, tier, enabled, paused, cap, portcap = a
            cap_usd = (cap or portcap or 0) / 100
            print(f"  {bot:<35} {aid:>8} {str(tier):>4} {str(enabled):>7} {cap_usd:>9,.0f}  {paused or ''}")

    # ── 3. LAST 24H SIGNALS PER BOT ──────────────────────────────────────────
    print("\n" + "="*70)
    print("C. SIGNALS IN LAST 24H PER BOT")
    print("="*70)
    print(f"{'bot_id':<35} {'24h_sigs':>8} {'last_signal_at'}")
    print("-"*70)

    for bot in ALL_BOTS:
        row = conn.execute(text(
            "SELECT id FROM bot_profiles WHERE name = :n"
        ), {"n": bot}).fetchone()
        if not row:
            continue
        pid = row[0]
        result = conn.execute(text("""
            SELECT COUNT(bs.id), MAX(bs.ts)
            FROM bot_signals bs
            JOIN bot_allocations ba ON bs.allocation_id = ba.id
            WHERE ba.profile_id = :pid
              AND bs.ts > :cutoff
        """), {"pid": pid, "cutoff": cutoff_24h}).fetchone()
        cnt, last_ts = result if result else (0, None)
        print(f"  {bot:<35} {(cnt or 0):>8}  {last_ts or 'NONE'}")

    # ── 4. OPEN POSITIONS PER BOT ────────────────────────────────────────────
    print("\n" + "="*70)
    print("D. OPEN POSITIONS PER BOT")
    print("="*70)
    print(f"{'bot_id':<35} {'open_pos':>8} {'unrealized_pct (approx)'}")
    print("-"*70)

    for bot in ALL_BOTS:
        row = conn.execute(text(
            "SELECT id FROM bot_profiles WHERE name = :n"
        ), {"n": bot}).fetchone()
        if not row:
            continue
        pid = row[0]
        pos_result = conn.execute(text("""
            SELECT COUNT(bp.id)
            FROM bot_positions bp
            JOIN bot_allocations ba ON bp.allocation_id = ba.id
            WHERE ba.profile_id = :pid
              AND bp.closed_at IS NULL
              AND (bp.quarantined_at IS NULL)
        """), {"pid": pid}).fetchone()
        open_pos = pos_result[0] if pos_result else 0
        print(f"  {bot:<35} {open_pos:>8}")

    # ── 5. OPTIONS BOTS SPECIFIC CHECK ───────────────────────────────────────
    print("\n" + "="*70)
    print("E. OPTIONS BOTS — LEADERBOARD VISIBILITY CHECK")
    print("="*70)
    for bot in ("options_income", "options_directional"):
        row = conn.execute(text(
            "SELECT id, enabled FROM bot_profiles WHERE name = :n"
        ), {"n": bot}).fetchone()
        if not row:
            print(f"  {bot}: NO PROFILE — seeds.py hasn't run or profile name mismatch")
            continue
        pid, bp_enabled = row
        allocs = conn.execute(text(
            "SELECT id, enabled, tier FROM bot_allocations WHERE profile_id = :pid"
        ), {"pid": pid}).fetchall()
        print(f"  {bot}: BotProfile.enabled={bp_enabled}, allocations={len(allocs)}")
        if not allocs:
            print(f"    -> NOT IN LEADERBOARD: no allocation row.")
            print(f"    -> FIX: visit /bots or /strategy-lab page once to trigger _ensure_portfolios_for_user()")
        for a in allocs:
            print(f"    alloc_id={a[0]} enabled={a[1]} tier={a[2]}")

print("\nAudit complete.")
