"""v2 LEAN framework — shadow run inspection endpoints.

GET /api/v2/shadow/{bot_id}/latest   — most recent shadow run
GET /api/v2/shadow/{bot_id}/history  — last N runs (default 10)
POST /api/v2/shadow/{bot_id}/run     — trigger an ad-hoc shadow run (admin)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies import get_current_user

_ADMIN_EMAILS = {"32bgorzelanczyk@gmail.com"}

def _require_admin(current_user=Depends(get_current_user)):
    if not getattr(current_user, "is_admin", False) and current_user.email not in _ADMIN_EMAILS:
        raise HTTPException(403, "Admin access required")
    return current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v2/shadow", tags=["v2-shadow"])

_ALLOWED_BOTS = {"crypto_lt"}


@router.get("/{bot_id}/latest")
def get_latest_shadow_run(
    bot_id: str,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    """Return the most recent shadow run for a bot."""
    if bot_id not in _ALLOWED_BOTS:
        raise HTTPException(404, f"No v2 definition for '{bot_id}'")

    from app.db.models.v2_shadow import V2ShadowRun
    row = (
        db.query(V2ShadowRun)
        .filter_by(bot_id=bot_id)
        .order_by(V2ShadowRun.run_ts.desc())
        .first()
    )
    if not row:
        return {"bot_id": bot_id, "run": None, "message": "No shadow runs yet"}

    return {"bot_id": bot_id, "run": _serialize(row)}


@router.get("/{bot_id}/history")
def get_shadow_history(
    bot_id: str,
    limit: int = 10,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    """Return the last N shadow runs for a bot."""
    if bot_id not in _ALLOWED_BOTS:
        raise HTTPException(404, f"No v2 definition for '{bot_id}'")

    from app.db.models.v2_shadow import V2ShadowRun
    rows = (
        db.query(V2ShadowRun)
        .filter_by(bot_id=bot_id)
        .order_by(V2ShadowRun.run_ts.desc())
        .limit(max(1, min(limit, 100)))
        .all()
    )
    return {
        "bot_id": bot_id,
        "count": len(rows),
        "runs": [_serialize(r, include_detail=False) for r in rows],
    }


@router.post("/{bot_id}/run")
def trigger_shadow_run(
    bot_id: str,
    db: Session = Depends(get_db),
    _admin=Depends(_require_admin),
):
    """Ad-hoc shadow run — admin only.  Useful for testing before scheduled run."""
    if bot_id not in _ALLOWED_BOTS:
        raise HTTPException(404, f"No v2 definition for '{bot_id}'")

    try:
        from strategy_lab.v2.shadow_runner import run_v2_shadow
        result = run_v2_shadow(bot_id)
        return {"ok": True, **result}
    except Exception as exc:
        logger.error("ad-hoc shadow run failed for %s: %s", bot_id, exc)
        raise HTTPException(500, str(exc))


def _serialize(row, include_detail: bool = True) -> dict:
    d = {
        "id": row.id,
        "bot_id": row.bot_id,
        "run_ts": row.run_ts.isoformat() if row.run_ts else None,
        "universe_size": row.universe_size,
        "insights_count": row.insights_count,
        "targets_count": row.targets_count,
        "orders_count": row.orders_count,
        "shadow_mode": row.shadow_mode,
        "duration_ms": row.duration_ms,
        "error": row.error,
    }
    if include_detail:
        d["insights"] = _parse_json(row.insights_json)
        d["targets"] = _parse_json(row.targets_json)
        d["orders"] = _parse_json(row.orders_json)
        d["events"] = _parse_json(row.events_json)
    return d


def _parse_json(s: str | None) -> list:
    if not s:
        return []
    try:
        return json.loads(s)
    except Exception:
        return []
