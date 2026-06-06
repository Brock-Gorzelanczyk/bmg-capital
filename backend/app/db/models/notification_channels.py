from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NotificationChannel(Base):
    __tablename__ = "notification_channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String, nullable=False)          # discord|telegram|slack|email
    name: Mapped[str] = mapped_column(String, nullable=False)          # user-friendly label
    webhook_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    telegram_chat_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class NotificationSubscription(Base):
    __tablename__ = "notification_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    channel_id: Mapped[int] = mapped_column(Integer, ForeignKey("notification_channels.id", ondelete="CASCADE"), nullable=False, index=True)
    bot_name: Mapped[str] = mapped_column(String, nullable=False)      # stock_swing | crypto_day | etc
    signal_types: Mapped[list] = mapped_column(JSON, default=list)     # ['entry','exit','rebalance','alert']
    min_confidence: Mapped[float] = mapped_column(Float, default=0.6)
    quiet_hours_start: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # "22:00"
    quiet_hours_end: Mapped[Optional[str]] = mapped_column(String, nullable=True)    # "08:00"
    quiet_hours_tz: Mapped[str] = mapped_column(String, default="America/Chicago")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class NotificationLog(Base):
    __tablename__ = "notification_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    channel_id: Mapped[int] = mapped_column(Integer, ForeignKey("notification_channels.id", ondelete="CASCADE"), nullable=False, index=True)
    signal_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)        # sent|failed|rate_limited|quiet_hours
    error_msg: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
