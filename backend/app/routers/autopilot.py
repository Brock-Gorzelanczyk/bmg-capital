"""
Autopilot unified framework router.

GET   /api/autopilot/status              — dashboard status + health score
GET   /api/autopilot/activity            — paginated action log (filterable by category)
GET   /api/autopilot/policies            — all 9 category policies for current user
PATCH /api/autopilot/policies/{category} — update enabled + config for a category
GET   /api/autopilot/guardrails          — user's autopilot guardrail settings
PATCH /api/autopilot/guardrails          — update guardrail values
POST  /api/autopilot/pause               — globally pause all autopilot automation
POST  /api/autopilot/resume              — resume all autopilot automation
GET   /api/autopilot/activity/export     — StreamingResponse CSV of all actions
GET   /api/autopilot/summary/today       — today's aggregate + highlights
"""
from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user, require_admin
from app.db.models.autopilot import AutopilotAction, AutopilotGuardrail, AutopilotPolicy
from app.core.tz import iso_utc
from app.services.autopilot_policy import (
    CATEGORIES,
    get_or_create_autopilot_guardrail,
    get_or_create_policies,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/autopilot", tags=["autopilot"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _action_to_dict(a: AutopilotAction) -> dict:
    return {
        "id": a.id,
        "user_id": a.user_id,
        "category": a.category,
        "action_type": a.action_type,
        "asset": a.asset,
        "params": a.params if isinstance(a.params, dict) else {},
        "ai_rationale": a.ai_rationale,
        "result": a.result,
        "outcome_value": a.outcome_value,
        "created_at": iso_utc(a.created_at),
    }


def _policy_to_dict(p: AutopilotPolicy) -> dict:
    return {
        "id": p.id,
        "user_id": p.user_id,
        "category": p.category,
        "enabled": p.enabled,
        "config": p.config if isinstance(p.config, dict) else {},
        "created_at": iso_utc(p.created_at),
        "updated_at": iso_utc(p.updated_at),
    }


def _guardrail_to_dict(g: AutopilotGuardrail) -> dict:
    return {
        "id": g.id,
        "user_id": g.user_id,
        "daily_loss_limit_pct": g.daily_loss_limit_pct,
        "weekly_loss_limit_pct": g.weekly_loss_limit_pct,
        "max_open_positions": g.max_open_positions,
        "cash_drain_per_week": g.cash_drain_per_week,
        "max_position_concentration_pct": g.max_position_concentration_pct,
        "max_subscriptions_cancel_per_week": g.max_subscriptions_cancel_per_week,
        "global_paused": g.global_paused,
        "paused_at": iso_utc(g.paused_at),
        "updated_at": iso_utc(g.updated_at),
    }


def _compute_health_score(actions_today: list[AutopilotAction], policies: dict[str, AutopilotPolicy]) -> int:
    """
    Health score 0–100. Normalized sum of (actions_today per active/enabled category).
    Active categories contribute proportionally; max = total active categories * 10, capped at 100.
    """
    active_categories = {cat for cat, p in policies.items() if p.enabled}
    if not active_categories:
        return 0

    by_cat: dict[str, int] = {}
    for a in actions_today:
        if a.category in active_categories:
            by_cat[a.category] = by_cat.get(a.category, 0) + 1

    # Each active category contributes up to 10 points; scale to 100
    max_possible = len(active_categories) * 10
    raw = sum(min(count, 10) for count in by_cat.values())
    score = int(min(100, round(raw / max_possible * 100))) if max_possible > 0 else 0
    return score


# ── Schemas ───────────────────────────────────────────────────────────────────

class PolicyUpdate(BaseModel):
    enabled: Optional[bool] = None
    config: Optional[dict] = None


class GuardrailUpdate(BaseModel):
    daily_loss_limit_pct: Optional[float] = None
    weekly_loss_limit_pct: Optional[float] = None
    max_open_positions: Optional[int] = None
    cash_drain_per_week: Optional[float] = None
    max_position_concentration_pct: Optional[float] = None
    max_subscriptions_cancel_per_week: Optional[int] = None


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/status")
def get_status(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Dashboard status + health score for all autopilot categories."""
    try:
        user_id = current_user.id
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        actions_today = (
            db.query(AutopilotAction)
            .filter(
                AutopilotAction.user_id == user_id,
                AutopilotAction.created_at >= today_start,
            )
            .all()
        )

        policies = get_or_create_policies(user_id, db)
        guardrail = get_or_create_autopilot_guardrail(user_id, db)

        # Build per-category stats
        by_cat_count: dict[str, int] = {}
        by_cat_last: dict[str, Optional[str]] = {}
        for a in actions_today:
            by_cat_count[a.category] = by_cat_count.get(a.category, 0) + 1

        for cat in CATEGORIES:
            last_action = (
                db.query(AutopilotAction)
                .filter(AutopilotAction.user_id == user_id, AutopilotAction.category == cat)
                .order_by(AutopilotAction.created_at.desc())
                .first()
            )
            by_cat_last[cat] = last_action.created_at.isoformat() if last_action and last_action.created_at else None

        categories_out = [
            {
                "name": cat,
                "enabled": policies[cat].enabled if cat in policies else True,
                "last_action": by_cat_last.get(cat),
                "actions_today": by_cat_count.get(cat, 0),
            }
            for cat in CATEGORIES
        ]

        guardrail_status = "paused" if guardrail.global_paused else "ok"
        health_score = _compute_health_score(actions_today, policies)

        # Also count bot strategy signals from AutonomousAction (Mission Control source)
        # so Autopilot and Mission Control always show the same total
        bot_signals_today = 0
        if _HAS_AUTONOMOUS and _AutonomousAction is not None:
            try:
                bot_signals_today = (
                    db.query(_AutonomousAction)
                    .filter(
                        _AutonomousAction.user_id == user_id,
                        _AutonomousAction.created_at >= today_start,
                    )
                    .count()
                )
            except Exception:
                pass

        total_combined = len(actions_today) + bot_signals_today

        return {
            "total_actions_today": total_combined,
            "autopilot_actions_today": len(actions_today),
            "bot_signals_today": bot_signals_today,
            "categories": categories_out,
            "global_paused": guardrail.global_paused,
            "guardrail_status": guardrail_status,
            "health_score": health_score,
        }
    except Exception as e:
        logger.error(f"autopilot /status error: {e}", exc_info=True)
        return {
            "total_actions_today": 0,
            "autopilot_actions_today": 0,
            "bot_signals_today": 0,
            "categories": [{"name": c, "enabled": True, "last_action": None, "actions_today": 0} for c in CATEGORIES],
            "global_paused": False,
            "guardrail_status": "unknown",
            "health_score": 0,
        }


@router.get("/activity")
def get_activity(
    category: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Paginated autopilot action log, optionally filtered by category."""
    try:
        q = db.query(AutopilotAction).filter(AutopilotAction.user_id == current_user.id)
        if category:
            if category not in CATEGORIES:
                raise HTTPException(status_code=400, detail=f"Invalid category. Must be one of: {CATEGORIES}")
            q = q.filter(AutopilotAction.category == category)

        total = q.count()
        offset = (page - 1) * limit
        actions = q.order_by(AutopilotAction.created_at.desc()).offset(offset).limit(limit).all()

        return {
            "total": total,
            "page": page,
            "limit": limit,
            "pages": max(1, -(-total // limit)),  # ceiling division
            "items": [_action_to_dict(a) for a in actions],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"autopilot /activity error: {e}", exc_info=True)
        return {"total": 0, "page": page, "limit": limit, "pages": 1, "items": []}


@router.get("/policies")
def get_policies(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return all 9 category policies for the current user, creating defaults if missing."""
    try:
        policies = get_or_create_policies(current_user.id, db)
        return [_policy_to_dict(policies[cat]) for cat in CATEGORIES if cat in policies]
    except Exception as e:
        logger.error(f"autopilot /policies error: {e}", exc_info=True)
        return []


@router.patch("/policies/{category}")
def update_policy(
    category: str,
    body: PolicyUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
):
    """Update enabled flag and/or config for a single category policy."""
    if category not in CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Invalid category. Must be one of: {CATEGORIES}")

    policies = get_or_create_policies(current_user.id, db)
    policy = policies.get(category)
    if not policy:
        raise HTTPException(status_code=404, detail=f"Policy not found for category: {category}")

    if body.enabled is not None:
        policy.enabled = body.enabled
    if body.config is not None:
        # Merge incoming config into existing config (shallow merge)
        existing_config = policy.config if isinstance(policy.config, dict) else {}
        policy.config = {**existing_config, **body.config}

    policy.updated_at = datetime.now(timezone.utc)
    db.add(policy)
    db.commit()
    db.refresh(policy)
    return _policy_to_dict(policy)


@router.get("/guardrails")
def get_guardrails(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return the user's autopilot guardrail settings, creating defaults if none exist."""
    guardrail = get_or_create_autopilot_guardrail(current_user.id, db)
    return _guardrail_to_dict(guardrail)


@router.patch("/guardrails")
def update_guardrails(
    body: GuardrailUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
):
    """Update one or more guardrail values."""
    guardrail = get_or_create_autopilot_guardrail(current_user.id, db)

    if body.daily_loss_limit_pct is not None:
        if not (0.5 <= body.daily_loss_limit_pct <= 20.0):
            raise HTTPException(status_code=400, detail="daily_loss_limit_pct must be between 0.5 and 20")
        guardrail.daily_loss_limit_pct = body.daily_loss_limit_pct

    if body.weekly_loss_limit_pct is not None:
        if not (1.0 <= body.weekly_loss_limit_pct <= 40.0):
            raise HTTPException(status_code=400, detail="weekly_loss_limit_pct must be between 1 and 40")
        guardrail.weekly_loss_limit_pct = body.weekly_loss_limit_pct

    if body.max_open_positions is not None:
        if not (1 <= body.max_open_positions <= 100):
            raise HTTPException(status_code=400, detail="max_open_positions must be between 1 and 100")
        guardrail.max_open_positions = body.max_open_positions

    if body.cash_drain_per_week is not None:
        if body.cash_drain_per_week < 0:
            raise HTTPException(status_code=400, detail="cash_drain_per_week must be >= 0")
        guardrail.cash_drain_per_week = body.cash_drain_per_week

    if body.max_position_concentration_pct is not None:
        if not (1.0 <= body.max_position_concentration_pct <= 100.0):
            raise HTTPException(status_code=400, detail="max_position_concentration_pct must be between 1 and 100")
        guardrail.max_position_concentration_pct = body.max_position_concentration_pct

    if body.max_subscriptions_cancel_per_week is not None:
        if body.max_subscriptions_cancel_per_week < 0:
            raise HTTPException(status_code=400, detail="max_subscriptions_cancel_per_week must be >= 0")
        guardrail.max_subscriptions_cancel_per_week = body.max_subscriptions_cancel_per_week

    guardrail.updated_at = datetime.now(timezone.utc)
    db.add(guardrail)
    db.commit()
    db.refresh(guardrail)
    return _guardrail_to_dict(guardrail)


@router.post("/pause")
def pause_autopilot(
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
):
    """Globally pause all autopilot automation for this user."""
    guardrail = get_or_create_autopilot_guardrail(current_user.id, db)
    guardrail.global_paused = True
    guardrail.paused_at = datetime.now(timezone.utc)
    guardrail.updated_at = datetime.now(timezone.utc)
    db.add(guardrail)
    db.commit()
    db.refresh(guardrail)

    from app.services.autopilot_logger import log_autopilot_action
    log_autopilot_action(
        user_id=current_user.id,
        category="account",
        action_type="autopilot_paused",
        params={},
        ai_rationale="User paused all autopilot automation globally. All category actions will be skipped until resumed.",
        result="success",
    )

    return _guardrail_to_dict(guardrail)


@router.post("/resume")
def resume_autopilot(
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
):
    """Resume all autopilot automation for this user."""
    guardrail = get_or_create_autopilot_guardrail(current_user.id, db)
    guardrail.global_paused = False
    guardrail.paused_at = None
    guardrail.updated_at = datetime.now(timezone.utc)
    db.add(guardrail)
    db.commit()
    db.refresh(guardrail)

    from app.services.autopilot_logger import log_autopilot_action
    log_autopilot_action(
        user_id=current_user.id,
        category="account",
        action_type="autopilot_resumed",
        params={},
        ai_rationale="User resumed all autopilot automation globally. All enabled category policies are now active.",
        result="success",
    )

    return _guardrail_to_dict(guardrail)


@router.get("/activity/export")
def export_activity(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """StreamingResponse CSV of ALL autopilot_actions for the user (permanent audit log)."""
    user_id = current_user.id

    def generate_csv():
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "id", "category", "action_type", "asset",
            "ai_rationale", "result", "outcome_value",
            "params", "created_at",
        ])
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)

        # Stream in batches of 500 to avoid loading everything into memory
        batch_size = 500
        offset = 0
        while True:
            batch = (
                db.query(AutopilotAction)
                .filter(AutopilotAction.user_id == user_id)
                .order_by(AutopilotAction.created_at.asc())
                .offset(offset)
                .limit(batch_size)
                .all()
            )
            if not batch:
                break
            for a in batch:
                writer.writerow([
                    a.id,
                    a.category,
                    a.action_type,
                    a.asset or "",
                    a.ai_rationale,
                    a.result,
                    a.outcome_value if a.outcome_value is not None else "",
                    str(a.params) if a.params else "{}",
                    a.created_at.isoformat() if a.created_at else "",
                ])
            yield output.getvalue()
            output.seek(0)
            output.truncate(0)
            offset += batch_size

    filename = f"autopilot_actions_user{current_user.id}.csv"
    return StreamingResponse(
        generate_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/summary/today")
def get_summary_today(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Today's aggregate action counts per category plus highlights.

    Merges AutopilotAction (manual/policy-driven) with AutonomousAction (worker-driven)
    so the banner count reflects everything BMG did for the user today.
    Returns 0 counts when the worker hasn't run yet — never raises.
    """
    try:
        user_id = current_user.id
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        actions = (
            db.query(AutopilotAction)
            .filter(
                AutopilotAction.user_id == user_id,
                AutopilotAction.created_at >= today_start,
            )
            .order_by(AutopilotAction.created_at.desc())
            .all()
        )

        # Also count autonomous_actions generated by the background worker
        autonomous_count_today = 0
        try:
            from app.db.models.autonomous import AutonomousAction as _AutonomousAction
            autonomous_count_today = (
                db.query(_AutonomousAction)
                .filter(
                    _AutonomousAction.user_id == user_id,
                    _AutonomousAction.created_at >= today_start,
                )
                .count()
            )
        except Exception as _e:
            logger.debug(f"autonomous_actions count unavailable: {_e}")

        by_category: dict[str, int] = {cat: 0 for cat in CATEGORIES}
        for a in actions:
            if a.category in by_category:
                by_category[a.category] += 1

        # Build highlights from most recent distinct categories
        seen_cats: set[str] = set()
        highlights: list[dict[str, Any]] = []
        for a in actions:
            if a.category not in seen_cats and len(highlights) < 5:
                highlights.append({
                    "category": a.category,
                    "action_type": a.action_type,
                    "asset": a.asset,
                    "ai_rationale": a.ai_rationale,
                    "result": a.result,
                    "created_at": iso_utc(a.created_at),
                })
                seen_cats.add(a.category)

        # total_actions = autopilot actions + autonomous worker actions
        total_actions = len(actions) + autonomous_count_today

        return {
            "total_actions": total_actions,
            "autopilot_actions": len(actions),
            "autonomous_actions": autonomous_count_today,
            "by_category": by_category,
            "highlights": highlights,
        }
    except Exception as e:
        logger.error(f"autopilot /summary/today error: {e}", exc_info=True)
        return {
            "total_actions": 0,
            "autopilot_actions": 0,
            "autonomous_actions": 0,
            "by_category": {cat: 0 for cat in CATEGORIES},
            "highlights": [],
        }
