"""
/api/admin/cash-floor/* — passive index ETF deployment of idle cash.

GET  /cash-floor/status     — snapshot of current vs target allocation
POST /cash-floor/propose    — return the rebalance trade list (no writes)
POST /cash-floor/rebalance  — SCAFFOLDING. Executes the trades IF kill
                              switches off and X-Brock-Confirm valid.
                              The actual position-write loop is
                              INTENTIONALLY ABSENT — matches the V1
                              capital_execute pattern, by design.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/cash-floor", tags=["admin"])


def _verify_brock_confirm(payload: str, header_value: Optional[str]) -> tuple[bool, str]:
    secret = os.getenv("BROCK_CONFIRM_SECRET", "")
    if not secret:
        return False, "BROCK_CONFIRM_SECRET not configured"
    if not header_value:
        return False, "missing X-Brock-Confirm header"
    expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, header_value):
        return False, "X-Brock-Confirm signature mismatch"
    return True, "ok"


@router.get("/status")
def status(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    """Read-only snapshot. No writes."""
    from app.services.cash_floor import compute_status
    return compute_status(db)


@router.post("/propose")
def propose(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    """Return the trade list the rebalance WOULD place. Still no writes."""
    from app.services.cash_floor import propose_rebalance
    return propose_rebalance(db)


@router.post("/rebalance")
def rebalance(
    x_brock_confirm: Optional[str] = Header(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    """Execute the Cash Floor rebalance — gated by the same kill switch as
    capital/execute-rebalance.

    Even when CAPITAL_EXECUTE_ENABLED=true and the X-Brock-Confirm signature
    validates, the actual position-write loop is INTENTIONALLY ABSENT. To
    actually buy SPY/QQQ, the operator replaces the final return statement
    with the trade-write loop and redeploys. No env-var alone unlocks the
    write. By design.
    """
    from app.services.cash_floor import propose_rebalance

    if os.getenv("CAPITAL_EXECUTE_ENABLED", "false").strip().lower() != "true":
        plan = propose_rebalance(db)
        return {
            "executed": False,
            "reason": "kill_switch_off",
            "note": (
                "Set CAPITAL_EXECUTE_ENABLED=true in Railway when ready to "
                "activate the gate. The final write step is still a manual "
                "code change."
            ),
            "plan": plan,
        }

    plan = propose_rebalance(db)
    if "error" in plan:
        raise HTTPException(status_code=400, detail=plan["error"])

    # HMAC on the trade plan canonical id.
    plan_id = f"cash-floor-{plan.get('as_of')}-{plan.get('trade_count')}"
    verified, why = _verify_brock_confirm(plan_id, x_brock_confirm)
    if not verified:
        raise HTTPException(status_code=403, detail=f"confirm token rejected: {why}")

    # Ops alert: the gate fired, but V1 still refuses the write.
    try:
        from app.services.discord import send_ops_alert
        send_ops_alert(
            title="[cash-floor] gate passed → write step intentionally absent",
            message=(
                f"All gates passed for Cash Floor rebalance.\n"
                f"Trades to place: {plan.get('trade_count')}\n"
                f"To actually execute, edit cash_floor.rebalance and replace "
                f"the return with the trade-write loop."
            ),
            severity="warn",
            source="cash_floor.rebalance",
        )
    except Exception:
        pass

    return {
        "executed": False,
        "reason": "v1_scaffolding_only",
        "note": (
            "All gates passed. The actual BotTrade + BotPosition writes for "
            "SPY / QQQ are intentionally not generated. Replace the final "
            "return with the position-write loop manually + redeploy."
        ),
        "would_have_executed": True,
        "plan": plan,
        "operator_user_id": current_user.id,
    }
