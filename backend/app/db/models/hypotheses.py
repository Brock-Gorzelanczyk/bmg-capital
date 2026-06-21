"""Hypothesis tracking — each tradable strategy is a hypothesis about market edge.

Live stats (n_trades, win_rate, expected_r) are DERIVED from BotTrade at
query time, not stored here — so this table needs no writes from the
signal-execution pipeline. Only status/factor_exposures/regime_preference
live here as config.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, Float, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class Hypothesis(Base):
    __tablename__ = "hypotheses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    strategy_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    direction: Mapped[str] = mapped_column(String(10), nullable=False, default="both")  # long|short|both
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="testing", index=True)  # live|testing|retired
    regime_preference: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    factor_exposures: Mapped[Any] = mapped_column(JSON, nullable=False, default=dict)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("idx_hyp_status_strategy", "status", "strategy_id"),
    )


class SystemEvent(Base):
    __tablename__ = "system_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    event_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    # signal_engine_start | weight_update | hypothesis_promoted | hypothesis_retired | regime_change | lesson_recorded
    message: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class Lesson(Base):
    __tablename__ = "lessons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    hypothesis_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    context: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    lesson_text: Mapped[str] = mapped_column(Text, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
