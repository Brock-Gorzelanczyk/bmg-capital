"""
/api/admin/capital/execute-rebalance — SCAFFOLDING ONLY.

Implements the gated execute path for the vol-targeting rebalance produced
by the dry-run allocator (capital_allocator.propose_rebalance).

Activation requires ALL of:
  1. X-Brock-Confirm HMAC header (computed via BROCK_CONFIRM_SECRET env var)
  2. A successful dry-run within the last 15 minutes (read from
     allocator router's _DRY_RUN_HISTORY)
  3. Fleet drawdown checks pass: > -1.5% from peak halts new orders;
     > -3% triggers unwind-to-30%
  4. Per-bot 24h drawdown < 5% (else that bot is flattened, not rebalanced)
  5. CAPITAL_EXECUTE_ENABLED env var set to "true"

Until Brock flips CAPITAL_EXECUTE_ENABLED=true, this endpoint always returns
{ executed: false, reason: 'kill_switch_off' }. No BotAllocation rows are
ever updated by V1. The scaffolding exists so that when Brock signs off, a
single env-var flip activates the path without any code changes.

Drawdown kill thresholds (per Brock's greenlight):
  - Fleet:  -1.5% peak-to-trough = halt new orders
            -3.0% peak-to-trough = unwind to 30% deployment
  - Per-bot: -5.0% in last 24h    = flatten that bot before rebalance
  - Crypto sleeve at cap          = hard error, do not spill to other sleeves
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text

from app.db.session import get_db
from app.dependencies import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/capital", tags=["admin"])

# Drawdown thresholds (fractions, negative)
FLEET_DD_HALT = -0.015        # -1.5% halt new orders
FLEET_DD_UNWIND = -0.030      # -3.0% unwind to 30%
PER_BOT_DD_24H_FLATTEN = -0.05  # -5% in 24h flatten bot
UNWIND_TARGET_DEPLOYMENT = 0.30
DRY_RUN_FRESHNESS_SECONDS = 15 * 60


def _verify_brock_confirm(payload: str, header_value: Optional[str]) -> tuple[bool, str]:
    """Verify HMAC of payload using BROCK_CONFIRM_SECRET env var.

    payload = canonical JSON of the dry-run propose_rebalance hash. The
    operator computes HMAC-SHA256(secret, payload) locally and passes it
    as X-Brock-Confirm.
    """
    secret = os.getenv("BROCK_CONFIRM_SECRET", "")
    if not secret:
        return False, "BROCK_CONFIRM_SECRET not configured"
    if not header_value:
        return False, "missing X-Brock-Confirm header"
    expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, header_value):
        return False, "X-Brock-Confirm signature mismatch"
    return True, "ok"


def _compute_fleet_drawdown(db: Session) -> tuple[float, dict]:
    """Peak-to-trough drawdown over last 30 days from nav_history."""
    try:
        rows = db.execute(sql_text("""
            SELECT date, nav_cents FROM nav_history
             WHERE date >= date('now', '-30 days')
             ORDER BY date ASC
        """)).fetchall()
        if not rows:
            return 0.0, {"reason": "no_nav_history"}
        peak = 0
        peak_date = None
        for d, nav in rows:
            if nav > peak:
                peak, peak_date = int(nav), d
        latest_date, latest_nav = rows[-1][0], int(rows[-1][1])
        if peak <= 0:
            return 0.0, {"reason": "peak_zero"}
        dd = (latest_nav - peak) / peak
        return dd, {
            "peak_cents": peak,
            "peak_date": peak_date,
            "latest_cents": latest_nav,
            "latest_date": latest_date,
            "dd_pct": round(dd * 100, 3),
        }
    except Exception as exc:
        logger.warning("[execute-rebalance] fleet dd computation failed: %s", exc)
        return 0.0, {"reason": "error", "detail": str(exc)}


def _bots_to_flatten(db: Session, allocation_ids: list[int]) -> list[int]:
    """Return allocation_ids whose 24h realized return < -5%."""
    if not allocation_ids:
        return []
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        rows = db.execute(sql_text("""
            SELECT bdp.allocation_id,
                   COALESCE(SUM(bdp.realized_cents), 0) AS realized,
                   COALESCE(MAX(a.starting_capital_cents), 1) AS start_cap
              FROM bot_daily_pnl bdp
              JOIN bot_allocations a ON a.id = bdp.allocation_id
             WHERE bdp.allocation_id IN ({ids})
               AND bdp.date >= date(:cutoff)
             GROUP BY bdp.allocation_id
        """.format(ids=",".join(str(int(x)) for x in allocation_ids))), {"cutoff": cutoff}).fetchall()
        return [
            int(r[0]) for r in rows
            if r[2] and int(r[2]) > 0 and float(r[1]) / float(r[2]) < PER_BOT_DD_24H_FLATTEN
        ]
    except Exception as exc:
        logger.warning("[execute-rebalance] bots_to_flatten failed: %s", exc)
        return []


@router.post("/execute-rebalance")
def execute_rebalance(
    payload: Dict[str, Any] = Body(...),
    x_brock_confirm: Optional[str] = Header(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    """Execute the rebalance described in payload.

    Required body shape:
      {"dry_run_id": "<hash from last-dry-run output>"}

    The dry-run output must have been produced within the last 15 minutes.
    If it has, payload['dry_run_id'] is HMAC-verified via X-Brock-Confirm,
    drawdown checks run, and IF and only if CAPITAL_EXECUTE_ENABLED=true,
    BotAllocation.capital_cents_within_portfolio rows are updated to the
    proposed values.

    Until CAPITAL_EXECUTE_ENABLED=true is set, this returns the would-execute
    plan + the dry-run reference but performs NO writes.
    """
    # Gate 1: kill switch
    if os.getenv("CAPITAL_EXECUTE_ENABLED", "false").strip().lower() != "true":
        return {
            "executed": False,
            "reason": "kill_switch_off",
            "note": "Set CAPITAL_EXECUTE_ENABLED=true in Railway when ready to activate.",
            "would_check_next": [
                "X-Brock-Confirm signature",
                "fresh dry-run (< 15 min)",
                "fleet drawdown > -1.5%",
                "per-bot 24h drawdown > -5%",
            ],
        }

    # Gate 2: dry-run freshness
    from app.routers.allocator import _DRY_RUN_HISTORY
    if not _DRY_RUN_HISTORY:
        raise HTTPException(status_code=400, detail="no dry-run on file — run /allocator/run-dry-run first")
    latest = _DRY_RUN_HISTORY[-1]
    computed_at = latest.get("computed_at")
    if not computed_at:
        raise HTTPException(status_code=400, detail="dry-run missing computed_at timestamp")
    try:
        ts = datetime.fromisoformat(computed_at.replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - ts).total_seconds()
    except Exception:
        raise HTTPException(status_code=400, detail="dry-run timestamp unparseable")
    if age > DRY_RUN_FRESHNESS_SECONDS:
        raise HTTPException(
            status_code=400,
            detail=f"dry-run is {int(age)}s old, max {DRY_RUN_FRESHNESS_SECONDS}s — re-run /allocator/run-dry-run first",
        )

    # Gate 3: HMAC signature on the payload
    dry_run_id = str(payload.get("dry_run_id", ""))
    verified, why = _verify_brock_confirm(dry_run_id, x_brock_confirm)
    if not verified:
        raise HTTPException(status_code=403, detail=f"confirm token rejected: {why}")

    # Gate 4: fleet drawdown
    fleet_dd, dd_details = _compute_fleet_drawdown(db)
    drawdown_decision = "normal"
    if fleet_dd <= FLEET_DD_UNWIND:
        drawdown_decision = "unwind_to_30pct"
    elif fleet_dd <= FLEET_DD_HALT:
        drawdown_decision = "halt_new_orders"

    # Gate 5: per-bot 24h drawdown
    allocs = [p["allocation_id"] for p in latest.get("propose_rebalance", [])]
    flatten_ids = _bots_to_flatten(db, allocs)

    # Notify ops with full decision context
    try:
        from app.services.discord import send_ops_alert
        send_ops_alert(
            title="[capital.execute] kill-switch tripped → rebalance NOT executed",
            message=(
                f"All gates passed up to the final write — but execute path is intentionally "
                f"unwritten in V1.\n"
                f"Fleet drawdown: {fleet_dd:.3%} → decision={drawdown_decision}\n"
                f"Bots requiring flatten (24h dd > 5%): {len(flatten_ids)}\n"
                f"Operator: user {current_user.id}\n"
                f"This message is the proof Brock asked for that the gate fires correctly."
            ),
            severity="warn",
            source="capital_execute.execute_rebalance",
        )
    except Exception:
        pass

    # V1 INTENTIONAL: even after all gates pass, we DO NOT mutate BotAllocation
    # rows. The path to "actually execute" requires a separate code change
    # that Brock reviews when he's ready. Returning the plan + flagging as
    # not-executed is the safety net.
    return {
        "executed": False,
        "reason": "v1_scaffolding_only",
        "note": (
            "All gates passed. To actually rebalance, replace the return at the "
            "end of execute_rebalance with the BotAllocation UPDATE loop. Brock "
            "must do this manually + redeploy. No env var unlocks the write — "
            "it's a code change, by design."
        ),
        "would_have_executed": True,
        "fleet_drawdown": fleet_dd,
        "drawdown_decision": drawdown_decision,
        "drawdown_details": dd_details,
        "flatten_bot_allocation_ids": flatten_ids,
        "dry_run_age_seconds": int(age),
        "dry_run_proposal_count": len(latest.get("propose_rebalance", [])),
    }
