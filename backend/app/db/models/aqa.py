"""ORM models for AQA Phase A tables: aqa_state and aqa_proposals."""
from __future__ import annotations

from datetime import datetime, date, timezone
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AqaState(Base):
    """Single-row config + per-day counters for the Autonomous Quant Agent.

    Only one row ever exists (id=1). Freeze state + daily budget counters.
    """
    __tablename__ = "aqa_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    frozen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # bool 0/1
    frozen_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    frozen_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    frozen_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    deploys_today: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    llm_calls_today: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    counter_date: Mapped[date] = mapped_column(Date, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )


class AqaProposal(Base):
    """One row per AQA LLM proposal cycle.

    Posted to Discord #aqa-proposals and stored for Brock's manual review.
    outcome NULL = pending review; 'approved'|'rejected'|'ignored' set by admin endpoint.
    """
    __tablename__ = "aqa_proposals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cycle_id: Mapped[str] = mapped_column(String, nullable=False)  # e.g. "aqa-20260630T0312Z-<uuid8>"
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
    issue_tags: Mapped[str] = mapped_column(Text, nullable=False)  # JSON list as TEXT
    llm_response_md: Mapped[str] = mapped_column(Text, nullable=False)
    context_summary: Mapped[str] = mapped_column(Text, nullable=False)  # JSON snapshot
    discord_message_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    outcome: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # NULL | 'approved' | 'rejected' | 'ignored'
