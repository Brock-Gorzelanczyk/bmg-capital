from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String

from app.db.base import Base


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = Column(String, nullable=False)  # price_alert | signal | paper_fill | earnings | news | streak | xp_levelup | badge | system
    title = Column(String, nullable=False)
    body = Column(String, default="")
    is_read = Column(Boolean, default=False, nullable=False)
    meta = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class NotificationPrefs(Base):
    __tablename__ = "notification_prefs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    # {event_type: {channel: bool}} — missing keys default to True (opted-in)
    prefs = Column(JSON, default=dict)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
