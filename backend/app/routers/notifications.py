from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
from app.db.models.users import User
from app.db.models.notifications import Notification, NotificationPrefs

router = APIRouter(prefix="/api/notifications", tags=["notifications"])

# ── Default prefs — all in_app on, email/push off ──────────────────────────

EVENT_TYPES = [
    "price_alert", "signal", "paper_fill", "earnings",
    "news", "streak", "xp_levelup", "badge", "system",
]

CHANNELS = ["in_app", "email", "push"]

DEFAULT_PREFS: dict[str, dict[str, bool]] = {
    event: {"in_app": True, "email": False, "push": False}
    for event in EVENT_TYPES
}


def _merge_prefs(stored: dict) -> dict:
    """Fill any missing keys with defaults."""
    result = {}
    for event in EVENT_TYPES:
        result[event] = {
            ch: stored.get(event, {}).get(ch, DEFAULT_PREFS[event][ch])
            for ch in CHANNELS
        }
    return result


# ── Helpers used by other routers ──────────────────────────────────────────

def create_notification(
    db: Session,
    user_id: int,
    event_type: str,
    title: str,
    body: str = "",
    meta: dict | None = None,
) -> Notification:
    """Create a notification — checks user prefs before persisting."""
    prefs_row = db.query(NotificationPrefs).filter_by(user_id=user_id).first()
    prefs = _merge_prefs(prefs_row.prefs if prefs_row else {})
    if not prefs.get(event_type, {}).get("in_app", True):
        return None  # user opted out
    notif = Notification(
        user_id=user_id,
        event_type=event_type,
        title=title,
        body=body,
        meta=meta or {},
    )
    db.add(notif)
    db.commit()
    db.refresh(notif)
    return notif


# ── Routes ─────────────────────────────────────────────────────────────────

@router.get("")
def list_notifications(
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(Notification)
        .filter_by(user_id=current_user.id)
        .order_by(Notification.created_at.desc())
        .limit(limit)
        .all()
    )
    return [_serialize(n) for n in rows]


@router.get("/unread-count")
def unread_count(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    count = (
        db.query(Notification)
        .filter_by(user_id=current_user.id, is_read=False)
        .count()
    )
    return {"count": count}


@router.post("/{notif_id}/read")
def mark_read(
    notif_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    n = db.query(Notification).filter_by(id=notif_id, user_id=current_user.id).first()
    if not n:
        raise HTTPException(status_code=404, detail="Notification not found")
    n.is_read = True
    db.commit()
    return {"ok": True}


@router.post("/read-all")
def mark_all_read(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db.query(Notification).filter_by(user_id=current_user.id, is_read=False).update({"is_read": True})
    db.commit()
    return {"ok": True}


@router.delete("/{notif_id}")
def delete_notification(
    notif_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    n = db.query(Notification).filter_by(id=notif_id, user_id=current_user.id).first()
    if not n:
        raise HTTPException(status_code=404, detail="Notification not found")
    db.delete(n)
    db.commit()
    return {"ok": True}


@router.delete("")
def clear_all(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db.query(Notification).filter_by(user_id=current_user.id).delete()
    db.commit()
    return {"ok": True}


# ── Prefs ──────────────────────────────────────────────────────────────────

@router.get("/settings")
def get_settings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.query(NotificationPrefs).filter_by(user_id=current_user.id).first()
    prefs = _merge_prefs(row.prefs if row else {})
    return {"prefs": prefs, "event_types": EVENT_TYPES, "channels": CHANNELS}


class PrefsUpdate(BaseModel):
    prefs: dict[str, dict[str, bool]]


@router.put("/settings")
def update_settings(
    body: PrefsUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.query(NotificationPrefs).filter_by(user_id=current_user.id).first()
    if row:
        row.prefs = body.prefs
        row.updated_at = datetime.utcnow()
    else:
        row = NotificationPrefs(user_id=current_user.id, prefs=body.prefs)
        db.add(row)
    db.commit()
    return {"ok": True, "prefs": _merge_prefs(body.prefs)}


# ── Serializer ─────────────────────────────────────────────────────────────

def _serialize(n: Notification) -> dict:
    return {
        "id": n.id,
        "event_type": n.event_type,
        "title": n.title,
        "body": n.body,
        "is_read": n.is_read,
        "meta": n.meta or {},
        "created_at": n.created_at.isoformat() if n.created_at else None,
    }


# ── Push-policy endpoints ───────────────────────────────────────────────────

AUTOPILOT_CATEGORIES = [
    "trading", "portfolio", "money", "research",
    "learning", "journal", "tax", "alerts", "account",
]


@router.get("/policy")
def get_notification_policy(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Returns the user's full notification / push policy:
    - max_push_per_day
    - quiet_hours start/end (UTC)
    - push_per_category: {category: bool}
    - push_used_today
    - is_quiet_hours_now
    """
    from app.db.models.autopilot import AutopilotPolicy
    from app.services.notification_policy import (
        is_quiet_hours,
        get_push_budget,
        get_push_count_today,
        QUIET_HOURS_START_UTC,
        QUIET_HOURS_END_UTC,
    )

    push_per_category: dict[str, bool] = {}
    for category in AUTOPILOT_CATEGORIES:
        policy = db.query(AutopilotPolicy).filter_by(
            user_id=current_user.id, category=category
        ).first()
        if policy and policy.config:
            push_per_category[category] = bool(policy.config.get("push_enabled", True))
        else:
            push_per_category[category] = True

    return {
        "max_push_per_day": get_push_budget(current_user.id, db),
        "quiet_hours_start": QUIET_HOURS_START_UTC,
        "quiet_hours_end": QUIET_HOURS_END_UTC,
        "push_per_category": push_per_category,
        "push_used_today": get_push_count_today(current_user.id, db),
        "is_quiet_hours_now": is_quiet_hours(),
    }


class PolicyUpdate(BaseModel):
    max_push_per_day: Optional[int] = None
    quiet_hours_start: Optional[int] = None
    quiet_hours_end: Optional[int] = None
    category_push: Optional[dict[str, bool]] = None


@router.patch("/policy")
def update_notification_policy(
    body: PolicyUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Update push notification policy.
    - max_push_per_day stored in AutopilotPolicy "alerts" config
    - category_push: {category: bool} → stored as push_enabled in each category's config
    """
    from app.db.models.autopilot import AutopilotPolicy

    def _get_or_create_policy(category: str) -> AutopilotPolicy:
        policy = db.query(AutopilotPolicy).filter_by(
            user_id=current_user.id, category=category
        ).first()
        if not policy:
            policy = AutopilotPolicy(
                user_id=current_user.id,
                category=category,
                enabled=True,
                config={},
            )
            db.add(policy)
        return policy

    if body.max_push_per_day is not None:
        alerts_policy = _get_or_create_policy("alerts")
        config = dict(alerts_policy.config or {})
        config["max_push_per_day"] = body.max_push_per_day
        alerts_policy.config = config
        alerts_policy.updated_at = datetime.now(timezone.utc)

    if body.category_push:
        for category, enabled in body.category_push.items():
            if category not in AUTOPILOT_CATEGORIES:
                continue
            cat_policy = _get_or_create_policy(category)
            config = dict(cat_policy.config or {})
            config["push_enabled"] = bool(enabled)
            cat_policy.config = config
            cat_policy.updated_at = datetime.now(timezone.utc)

    db.commit()
    return {"ok": True}


@router.get("/quiet-hours")
def get_quiet_hours(
    current_user: User = Depends(get_current_user),
):
    """
    Returns quiet-hours state:
    { active: bool, start_utc: int, end_utc: int, local_description: str }
    """
    from app.services.notification_policy import (
        is_quiet_hours,
        QUIET_HOURS_START_UTC,
        QUIET_HOURS_END_UTC,
    )

    return {
        "active": is_quiet_hours(),
        "start_utc": QUIET_HOURS_START_UTC,
        "end_utc": QUIET_HOURS_END_UTC,
        "local_description": "9PM–7AM",
    }
