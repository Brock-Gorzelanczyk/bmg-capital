"""SQLAlchemy model for v2 algorithm shadow run audit records.

Each row is one full iteration: what would the v2 runner have done?
Compare against v1 runner output in bot_signals to validate parity.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Float, Integer, String, Text, Boolean
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.db.base import Base


class V2ShadowRun(Base):
    """One iteration of the v2 LEAN-style runner in shadow mode."""
    __tablename__ = "v2_shadow_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    bot_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    run_ts: Mapped[datetime] = mapped_column(
        DateTime, nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    universe_size: Mapped[int] = mapped_column(Integer, default=0)
    insights_count: Mapped[int] = mapped_column(Integer, default=0)
    targets_count: Mapped[int] = mapped_column(Integer, default=0)
    orders_count: Mapped[int] = mapped_column(Integer, default=0)
    shadow_mode: Mapped[bool] = mapped_column(Boolean, default=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    insights_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    targets_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    orders_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    events_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
