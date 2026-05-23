from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserTier(Base):
    """Tracks the user's subscription tier. Defaults to 'free'."""
    __tablename__ = "user_tiers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, unique=True, index=True)
    tier: Mapped[str] = mapped_column(String, nullable=False, default="free")   # free | pro | premium
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    stripe_sub_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
