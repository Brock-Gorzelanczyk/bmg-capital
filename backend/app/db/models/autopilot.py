from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AutopilotPolicy(Base):
    """User's per-category on/off + configuration."""
    __tablename__ = "autopilot_policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (UniqueConstraint("user_id", "category"),)


class AutopilotGuardrail(Base):
    """Hard risk limits across ALL automation (extends existing AutonomousGuardrail pattern)."""
    __tablename__ = "autopilot_guardrails"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    daily_loss_limit_pct: Mapped[float] = mapped_column(Float, nullable=False, default=3.0)
    weekly_loss_limit_pct: Mapped[float] = mapped_column(Float, nullable=False, default=7.0)
    max_open_positions: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    cash_drain_per_week: Mapped[float] = mapped_column(Float, nullable=False, default=500.0)
    max_position_concentration_pct: Mapped[float] = mapped_column(Float, nullable=False, default=15.0)
    max_subscriptions_cancel_per_week: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    global_paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    paused_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class AutopilotAction(Base):
    """Immutable audit log — every automated action across ALL categories."""
    __tablename__ = "autopilot_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String, nullable=False, index=True)
    action_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    asset: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    ai_rationale: Mapped[str] = mapped_column(String, nullable=False, default="")
    result: Mapped[str] = mapped_column(String, nullable=False, default="success")
    outcome_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, index=True,
        default=lambda: datetime.now(timezone.utc),
    )
