from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import Boolean, DateTime, Float, Integer, JSON, String, Text, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

class BotTemplate(Base):
    __tablename__ = "bot_templates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    emoji: Mapped[str] = mapped_column(String(10), nullable=False)
    tagline: Mapped[str] = mapped_column(String(300), nullable=False)
    strategies: Mapped[dict] = mapped_column(JSON, nullable=False)   # list of module_names
    default_config: Mapped[dict] = mapped_column(JSON, nullable=False)
    popularity_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), server_default=func.now())

class UserCustomBotDraft(Base):
    __tablename__ = "user_custom_bot_drafts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    template_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("bot_templates.id"), nullable=True)
    strategies: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)   # list of module_names
    config: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)       # capital_dollars, risk_profile, schedule
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    deployed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    deployed_bot_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("bot_profiles.id"), nullable=True)
