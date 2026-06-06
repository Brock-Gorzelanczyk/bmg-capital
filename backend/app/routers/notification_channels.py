"""
Notification channels API — CRUD for user-defined alert destinations.

POST   /api/notifications/channels              — create channel
GET    /api/notifications/channels              — list channels
PATCH  /api/notifications/channels/:id          — update channel
DELETE /api/notifications/channels/:id          — delete channel
POST   /api/notifications/channels/:id/test     — send test message
GET    /api/notifications/subscriptions         — list subscriptions
PUT    /api/notifications/subscriptions         — upsert all subscriptions
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
from app.db.models.notification_channels import (
    NotificationChannel, NotificationSubscription, NotificationLog,
)
from app.db.models.users import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/notifications", tags=["notifications"])

_ALL_BOTS = [
    "stock_swing", "stock_day", "stock_lt",
    "crypto_swing", "crypto_day", "crypto_lt",
    "options_income", "options_directional",
]


# ── Schemas ───────────────────────────────────────────────────────────────────

class ChannelCreate(BaseModel):
    type: str                             # discord|telegram|slack|email
    name: str
    webhook_url: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    email: Optional[str] = None


class ChannelUpdate(BaseModel):
    name: Optional[str] = None
    webhook_url: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    email: Optional[str] = None
    enabled: Optional[bool] = None


class SubscriptionUpsert(BaseModel):
    channel_id: int
    bot_name: str
    signal_types: list[str] = ["entry", "exit"]
    min_confidence: float = 0.6
    quiet_hours_start: Optional[str] = None   # "22:00"
    quiet_hours_end: Optional[str] = None     # "08:00"
    quiet_hours_tz: str = "America/Chicago"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _channel_to_dict(ch: NotificationChannel) -> dict:
    return {
        "id": ch.id,
        "type": ch.type,
        "name": ch.name,
        "webhook_url": ch.webhook_url,
        "telegram_chat_id": ch.telegram_chat_id,
        "email": ch.email,
        "enabled": ch.enabled,
        "verified": ch.verified,
        "created_at": ch.created_at.isoformat(),
    }


def _sub_to_dict(s: NotificationSubscription) -> dict:
    return {
        "id": s.id,
        "channel_id": s.channel_id,
        "bot_name": s.bot_name,
        "signal_types": s.signal_types,
        "min_confidence": s.min_confidence,
        "quiet_hours_start": s.quiet_hours_start,
        "quiet_hours_end": s.quiet_hours_end,
        "quiet_hours_tz": s.quiet_hours_tz,
    }


# ── Channel CRUD ──────────────────────────────────────────────────────────────

@router.post("/channels")
def create_channel(
    body: ChannelCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if body.type not in ("discord", "telegram", "slack", "email"):
        raise HTTPException(400, "type must be discord|telegram|slack|email")
    ch = NotificationChannel(
        user_id=current_user.id,
        type=body.type,
        name=body.name,
        webhook_url=body.webhook_url,
        telegram_chat_id=body.telegram_chat_id,
        email=body.email,
        enabled=True,
        verified=False,
    )
    db.add(ch)
    db.commit()
    db.refresh(ch)
    return _channel_to_dict(ch)


@router.get("/channels")
def list_channels(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    channels = (
        db.query(NotificationChannel)
        .filter(NotificationChannel.user_id == current_user.id)
        .order_by(NotificationChannel.id)
        .all()
    )
    return {"channels": [_channel_to_dict(c) for c in channels]}


@router.patch("/channels/{channel_id}")
def update_channel(
    channel_id: int,
    body: ChannelUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ch = db.query(NotificationChannel).filter_by(id=channel_id, user_id=current_user.id).first()
    if not ch:
        raise HTTPException(404, "Channel not found")
    if body.name is not None:
        ch.name = body.name
    if body.webhook_url is not None:
        ch.webhook_url = body.webhook_url
    if body.telegram_chat_id is not None:
        ch.telegram_chat_id = body.telegram_chat_id
    if body.email is not None:
        ch.email = body.email
    if body.enabled is not None:
        ch.enabled = body.enabled
    db.commit()
    db.refresh(ch)
    return _channel_to_dict(ch)


@router.delete("/channels/{channel_id}", status_code=204)
def delete_channel(
    channel_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ch = db.query(NotificationChannel).filter_by(id=channel_id, user_id=current_user.id).first()
    if not ch:
        raise HTTPException(404, "Channel not found")
    db.delete(ch)
    db.commit()


@router.post("/channels/{channel_id}/test")
def test_channel(
    channel_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ch = db.query(NotificationChannel).filter_by(id=channel_id, user_id=current_user.id).first()
    if not ch:
        raise HTTPException(404, "Channel not found")

    from app.services.notify import TEST_SIGNAL, _dispatch_to_channel
    try:
        _dispatch_to_channel(ch, TEST_SIGNAL, db)
        ch.verified = True
        db.commit()
        return {"ok": True, "message": "Test message sent successfully."}
    except Exception as exc:
        return {"ok": False, "message": str(exc)}


# ── Subscriptions ─────────────────────────────────────────────────────────────

@router.get("/subscriptions")
def list_subscriptions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    channels = (
        db.query(NotificationChannel)
        .filter(NotificationChannel.user_id == current_user.id)
        .all()
    )
    channel_ids = [c.id for c in channels]
    subs = (
        db.query(NotificationSubscription)
        .filter(NotificationSubscription.channel_id.in_(channel_ids))
        .all()
    ) if channel_ids else []
    return {"subscriptions": [_sub_to_dict(s) for s in subs]}


@router.put("/subscriptions")
def upsert_subscriptions(
    body: list[SubscriptionUpsert],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Validate channel ownership
    channel_ids = {s.channel_id for s in body}
    owned = {
        c.id for c in db.query(NotificationChannel)
        .filter(
            NotificationChannel.id.in_(channel_ids),
            NotificationChannel.user_id == current_user.id,
        )
        .all()
    }
    for item in body:
        if item.channel_id not in owned:
            raise HTTPException(403, f"Channel {item.channel_id} not owned by user")

    for item in body:
        existing = db.query(NotificationSubscription).filter_by(
            channel_id=item.channel_id, bot_name=item.bot_name
        ).first()
        if existing:
            existing.signal_types = item.signal_types
            existing.min_confidence = item.min_confidence
            existing.quiet_hours_start = item.quiet_hours_start
            existing.quiet_hours_end = item.quiet_hours_end
            existing.quiet_hours_tz = item.quiet_hours_tz
        else:
            db.add(NotificationSubscription(
                channel_id=item.channel_id,
                bot_name=item.bot_name,
                signal_types=item.signal_types,
                min_confidence=item.min_confidence,
                quiet_hours_start=item.quiet_hours_start,
                quiet_hours_end=item.quiet_hours_end,
                quiet_hours_tz=item.quiet_hours_tz,
            ))
    db.commit()
    return {"ok": True, "upserted": len(body)}


@router.delete("/subscriptions/{sub_id}", status_code=204)
def delete_subscription(
    sub_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    sub = db.query(NotificationSubscription).filter_by(id=sub_id).first()
    if not sub:
        raise HTTPException(404, "Subscription not found")
    ch = db.query(NotificationChannel).filter_by(id=sub.channel_id, user_id=current_user.id).first()
    if not ch:
        raise HTTPException(403, "Not authorized")
    db.delete(sub)
    db.commit()


@router.get("/logs")
def get_notification_logs(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    limit: int = 50,
):
    channels = db.query(NotificationChannel).filter_by(user_id=current_user.id).all()
    ch_ids = [c.id for c in channels]
    logs = (
        db.query(NotificationLog)
        .filter(NotificationLog.channel_id.in_(ch_ids))
        .order_by(NotificationLog.sent_at.desc())
        .limit(limit)
        .all()
    ) if ch_ids else []
    return {"logs": [
        {"id": l.id, "channel_id": l.channel_id, "status": l.status,
         "error_msg": l.error_msg, "sent_at": l.sent_at.isoformat()}
        for l in logs
    ]}
