from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, unique=True, index=True)
    # Investment preferences
    goal: Mapped[Optional[str]] = mapped_column(String, nullable=True)            # invest | trade | learn | all
    experience: Mapped[Optional[str]] = mapped_column(String, nullable=True)      # beginner | intermediate | advanced
    risk_tolerance: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # conservative | moderate | aggressive
    time_horizon: Mapped[Optional[str]] = mapped_column(String, nullable=True)    # short | medium | long | very_long
    # State
    onboarding_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    onboarding_completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
