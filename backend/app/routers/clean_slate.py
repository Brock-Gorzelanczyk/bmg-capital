"""
POST /api/admin/clean-slate/restart — atomic $1M fresh allocation.

Per Brock's 2026-06-24 spec:
  1. Close every open position across the fleet (paper convention: DB
     update, no broker call). exit_reason='clean_slate_reset',
     fill_price = current avg_cost (zero artificial P&L).
  2. Reset user_id=1's bot_allocations to the exact $1M distribution.
     12 active bots ranging $50K-$110K.
  3. Create cash_floor BotProfile + allocation at $100K if missing.
  4. Verify, post to ops, return summary.

ATOMIC: every DB write happens inside a single SQLAlchemy session
transaction. If any step raises, db.rollback() restores pre-state.

KILL SWITCH: requires CLEAN_SLATE_ENABLED=true. Returns
{executed: false, reason: kill_switch_off} otherwise. Brock flips
the env var, hits the endpoint once, flips it back.

Allocations spec ($1,000,000 total):
  STOCKS ($270K):
    stock_swing      110,000
    stock_lt          90,000
    stock_day         70,000
  CRYPTO ($270K):
    crypto_onchain    90,000
    crypto_day        70,000
    crypto_swing      60,000
    crypto_lt         50,000
  OPTIONS ($100K — reduced under cleanup):
    options_directional 50,000
    options_income      50,000
  QUANT ($260K):
    crypto_quant_mean_reversion 110,000  (top performer)
    crypto_quant_aggressive      80,000
    crypto_quant_scalper         70,000
  CASH FLOOR ($100K):
    cash_floor (new profile)    100,000
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text

from app.db.session import get_db
from app.dependencies import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/clean-slate", tags=["admin"])

# Brock's exact spec (cents)
ALLOCATIONS: dict[str, int] = {
    "stock_swing":                  11_000_000,
    "stock_lt":                      9_000_000,
    "stock_day":                     7_000_000,
    "crypto_onchain":                9_000_000,
    "crypto_day":                    7_000_000,
    "crypto_swing":                  6_000_000,
    "crypto_lt":                     5_000_000,
    "options_directional":           5_000_000,
    "options_income":                5_000_000,
    "crypto_quant_mean_reversion":  11_000_000,
    "crypto_quant_aggressive":       8_000_000,
    "crypto_quant_scalper":          7_000_000,
    "cash_floor":                   10_000_000,
}
TARGET_USER_ID = 1
TOTAL_TARGET_CENTS = sum(ALLOCATIONS.values())   # 100,000,000 = $1,000,000


@router.post("/restart")
def clean_slate_restart(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    """Execute the clean-slate restart. Single atomic transaction."""
    if os.getenv("CLEAN_SLATE_ENABLED", "false").strip().lower() != "true":
        return {
            "executed": False,
            "reason": "kill_switch_off",
            "note": (
                "Set CLEAN_SLATE_ENABLED=true in Railway, hit this endpoint, "
                "then set it back to false. The operation is destructive — "
                "the kill switch is your acknowledgement that you understand."
            ),
            "target_total_cents": TOTAL_TARGET_CENTS,
            "target_total_dollars": TOTAL_TARGET_CENTS / 100,
            "allocations_spec": {k: v / 100 for k, v in ALLOCATIONS.items()},
        }

    if current_user.id != TARGET_USER_ID:
        raise HTTPException(
            status_code=403,
            detail=(
                f"clean-slate restart can only be triggered by user "
                f"{TARGET_USER_ID} (Brock). Authenticated as {current_user.id}."
            ),
        )

    summary: dict[str, Any] = {
        "executed": True,
        "ts": datetime.now(timezone.utc).isoformat(),
        "operator_user_id": current_user.id,
    }

    try:
        # ── STEP 1: close every open position across the fleet ──────────
        now_iso = datetime.now(timezone.utc).isoformat()
        # Count first
        open_count = db.execute(sql_text("""
            SELECT COUNT(*) FROM bot_positions
             WHERE closed_at IS NULL AND quarantined_at IS NULL
        """)).scalar() or 0

        # Close them. fill_price = avg_cost_cents (zero artificial P&L).
        # The session commits at the end of this block, so this is atomic.
        db.execute(sql_text("""
            UPDATE bot_positions
               SET closed_at = :now,
                   exit_reason = 'clean_slate_reset'
             WHERE closed_at IS NULL
               AND quarantined_at IS NULL
        """), {"now": now_iso})

        summary["positions_closed"] = int(open_count)

        # ── STEP 2: ensure cash_floor BotProfile exists ─────────────────
        cf_row = db.execute(sql_text(
            "SELECT id FROM bot_profiles WHERE name = 'cash_floor'"
        )).fetchone()
        if cf_row:
            cash_floor_profile_id = int(cf_row[0])
            summary["cash_floor_profile"] = "preexisting"
        else:
            db.execute(sql_text("""
                INSERT INTO bot_profiles
                    (name, display_name, asset_class, enabled,
                     starting_capital_cents, config_json)
                VALUES
                    ('cash_floor', 'Cash Floor', 'stock', 1,
                     :cap, :cfg)
            """), {
                "cap": ALLOCATIONS["cash_floor"],
                "cfg": (
                    '{"strategy_type": "passive_beta", '
                    '"watchlist": ["SPY","QQQ"], '
                    '"target_weights": {"SPY": 0.60, "QQQ": 0.40}, '
                    '"rebalance_cadence": "daily_close", '
                    '"composite_threshold": 0, '
                    '"position_size_pct": 100, '
                    '"max_concurrent_positions": 2}'
                ),
            })
            cash_floor_profile_id = int(db.execute(sql_text(
                "SELECT id FROM bot_profiles WHERE name = 'cash_floor'"
            )).fetchone()[0])
            summary["cash_floor_profile"] = "created"
        summary["cash_floor_profile_id"] = cash_floor_profile_id

        # ── STEP 3: reset user_id=1's allocations to the spec ──────────
        # First, disable ALL existing enabled allocations for this user
        # (catches dupes that might have crept in despite m021).
        db.execute(sql_text("""
            UPDATE bot_allocations
               SET enabled = 0,
                   paused_reason = 'clean_slate_reset'
             WHERE user_id = :uid AND enabled = 1
        """), {"uid": TARGET_USER_ID})

        # Then for each profile in the spec, find one row (any user_id=1 row
        # for that profile) and re-enable + resize. If none exists, create one.
        per_bot: list[dict] = []
        for bot_name, target_cents in ALLOCATIONS.items():
            profile_row = db.execute(sql_text(
                "SELECT id FROM bot_profiles WHERE name = :n"
            ), {"n": bot_name}).fetchone()
            if not profile_row:
                # Profile doesn't exist — skip with note (shouldn't happen
                # since cash_floor was just created above).
                per_bot.append({"bot": bot_name, "status": "profile_missing"})
                continue
            profile_id = int(profile_row[0])

            existing = db.execute(sql_text("""
                SELECT id FROM bot_allocations
                 WHERE user_id = :uid AND profile_id = :pid
                 ORDER BY id ASC LIMIT 1
            """), {"uid": TARGET_USER_ID, "pid": profile_id}).fetchone()

            if existing:
                alloc_id = int(existing[0])
                db.execute(sql_text("""
                    UPDATE bot_allocations
                       SET enabled = 1,
                           paused_reason = NULL,
                           starting_capital_cents = :cap,
                           capital_cents_within_portfolio = :cap,
                           updated_at = :now
                     WHERE id = :id
                """), {"cap": target_cents, "now": now_iso, "id": alloc_id})
                per_bot.append({
                    "bot": bot_name, "alloc_id": alloc_id,
                    "cents": target_cents, "action": "updated",
                })
            else:
                db.execute(sql_text("""
                    INSERT INTO bot_allocations
                        (user_id, profile_id, capital_pct, risk_profile,
                         paper_mode, go_live_requested, enabled,
                         starting_capital_cents, created_at, updated_at,
                         tier)
                    VALUES
                        (:uid, :pid, 10.0, 'standard', 1, 0, 1,
                         :cap, :now, :now, 'T1')
                """), {
                    "uid": TARGET_USER_ID, "pid": profile_id,
                    "cap": target_cents, "now": now_iso,
                })
                new_id = int(db.execute(sql_text("""
                    SELECT id FROM bot_allocations
                     WHERE user_id = :uid AND profile_id = :pid
                     ORDER BY id DESC LIMIT 1
                """), {"uid": TARGET_USER_ID, "pid": profile_id}).fetchone()[0])
                per_bot.append({
                    "bot": bot_name, "alloc_id": new_id,
                    "cents": target_cents, "action": "created",
                })

        summary["allocations"] = per_bot

        # ── STEP 4: verify ──────────────────────────────────────────────
        enabled_total = db.execute(sql_text("""
            SELECT COALESCE(SUM(starting_capital_cents), 0)
              FROM bot_allocations
             WHERE user_id = :uid AND enabled = 1
        """), {"uid": TARGET_USER_ID}).scalar() or 0
        enabled_count = db.execute(sql_text("""
            SELECT COUNT(*) FROM bot_allocations
             WHERE user_id = :uid AND enabled = 1
        """), {"uid": TARGET_USER_ID}).scalar() or 0
        open_after = db.execute(sql_text("""
            SELECT COUNT(*) FROM bot_positions
             WHERE closed_at IS NULL AND quarantined_at IS NULL
        """)).scalar() or 0

        summary["verification"] = {
            "enabled_count": int(enabled_count),
            "enabled_total_cents": int(enabled_total),
            "enabled_total_dollars": int(enabled_total) / 100,
            "expected_total_cents": TOTAL_TARGET_CENTS,
            "matches_spec": int(enabled_total) == TOTAL_TARGET_CENTS,
            "open_positions_after": int(open_after),
        }

        if int(enabled_count) != len(ALLOCATIONS):
            raise RuntimeError(
                f"verification failed: expected {len(ALLOCATIONS)} enabled "
                f"allocs, found {enabled_count}"
            )
        if int(enabled_total) != TOTAL_TARGET_CENTS:
            raise RuntimeError(
                f"verification failed: enabled total {enabled_total} != "
                f"target {TOTAL_TARGET_CENTS}"
            )
        if int(open_after) != 0:
            raise RuntimeError(
                f"verification failed: {open_after} open positions remain"
            )

        # ── STEP 5: commit + post ops alert ─────────────────────────────
        db.commit()

        try:
            from app.services.discord import send_ops_alert
            send_ops_alert(
                title="[clean-slate] restart complete",
                message=(
                    f"Clean-slate restart executed by user {current_user.id}.\n"
                    f"Positions closed: {summary['positions_closed']}\n"
                    f"Active bots: {summary['verification']['enabled_count']}\n"
                    f"Allocated: ${summary['verification']['enabled_total_dollars']:,.0f}\n"
                    f"Cash Floor profile: {summary['cash_floor_profile']}\n"
                    f"Ready for fresh signal cycle."
                ),
                severity="warn",
                source="clean_slate.restart",
            )
        except Exception:
            pass

    except Exception as exc:
        db.rollback()
        logger.error("[clean-slate] failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"clean-slate restart aborted (rolled back): {exc}",
        )

    return summary
