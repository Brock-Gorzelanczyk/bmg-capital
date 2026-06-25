"""
/api/admin/allocator/* — vol-targeting allocator dry-run + last-result viewer.

POST /allocator/run-dry-run  — fire a fresh dry-run, persist result in-memory + return JSON
GET  /allocator/last-dry-run — return the most recent persisted dry-run output
GET  /allocator/history      — return all in-memory dry-run results (most recent first)

Does NOT execute. Execute path lives in COMMIT 18 behind X-Brock-Confirm.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies import get_current_user

router = APIRouter(prefix="/api/admin/allocator", tags=["admin"])

_DRY_RUN_HISTORY: List[dict] = []  # in-process history
_MAX_HISTORY = 50


@router.post("/run-dry-run")
def run_dry_run(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    """Fire a fresh vol-targeting dry-run. Persists in-memory + posts to ops."""
    from app.services.capital_allocator import propose_rebalance
    result = propose_rebalance(db, current_user.id)
    result["computed_by_user_id"] = current_user.id
    result["computed_at"] = datetime.now(timezone.utc).isoformat()

    _DRY_RUN_HISTORY.append(result)
    if len(_DRY_RUN_HISTORY) > _MAX_HISTORY:
        _DRY_RUN_HISTORY.pop(0)

    # Ops channel notification — short summary, not the whole JSON (Discord 2K char limit)
    try:
        from app.services.discord import send_ops_alert
        summary = (
            f"V1 dry-run computed.\n"
            f"Excluded: {len(result.get('excluded_bots', []))}\n"
            f"Survivors: {len(result.get('survivor_bots', []))}\n"
            f"Current deployment: {result.get('current_deployment_pct')}%\n"
            f"Proposed deployment: {result.get('proposed_deployment_pct')}%\n"
            f"Constraint violations: {len(result.get('constraint_violations', []))}\n"
            f"Estimated portfolio vol: {result.get('estimated_portfolio_vol_annualized')}\n"
            f"Full JSON: GET /api/admin/allocator/last-dry-run"
        )
        send_ops_alert(
            title="[allocator] V1 dry-run output",
            message=summary,
            severity="info",
            source="allocator.run_dry_run",
        )
    except Exception:
        pass

    return result


@router.get("/last-dry-run")
def last_dry_run(current_user=Depends(get_current_user)) -> Dict[str, Any]:
    """Most recent dry-run output. Empty dict if none yet."""
    if not _DRY_RUN_HISTORY:
        return {"empty": True, "note": "no dry-runs run yet — POST /run-dry-run to compute"}
    return _DRY_RUN_HISTORY[-1]


@router.get("/history")
def history(current_user=Depends(get_current_user)) -> Dict[str, Any]:
    """All cached dry-runs. In-process only; cleared on restart."""
    return {"count": len(_DRY_RUN_HISTORY), "history": list(reversed(_DRY_RUN_HISTORY))}
