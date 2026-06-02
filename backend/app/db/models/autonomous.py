from __future__ import annotations

from datetime import datetime, date, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Date, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AutonomousAction(Base):
    __tablename__ = "autonomous_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    lab: Mapped[str] = mapped_column(String, nullable=False)
    strategy_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    action_type: Mapped[str] = mapped_column(String, nullable=False)
    asset: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    params: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rationale: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    result: Mapped[str] = mapped_column(String, nullable=False, default="success")
    outcome_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, index=True,
        default=lambda: datetime.now(timezone.utc),
    )


class AutonomousGuardrail(Base):
    __tablename__ = "autonomous_guardrails"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True, unique=True)
    daily_loss_limit_pct: Mapped[float] = mapped_column(Float, nullable=False, default=3.0)
    weekly_loss_limit_pct: Mapped[float] = mapped_column(Float, nullable=False, default=7.0)
    max_consecutive_losses: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    max_drawdown_pct: Mapped[float] = mapped_column(Float, nullable=False, default=25.0)
    max_position_concentration: Mapped[float] = mapped_column(Float, nullable=False, default=15.0)
    max_open_positions: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    autonomous_paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    paused_reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    paused_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class AutonomousDigest(Base):
    __tablename__ = "autonomous_digests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    digest_date: Mapped[date] = mapped_column(Date, nullable=False)
    tldr: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    highlights: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    strategy_spotlight: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    signals_fired: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    paper_buys: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    paper_sells: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    best_action: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    worst_action: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    tomorrow_preview: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    market_regime_note: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    full_narrative: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    portfolio_delta: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
