from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, JSON, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class StrategyDefinition(Base):
    __tablename__ = "strategy_definitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    strategy_key: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_originator: Mapped[str] = mapped_column(String, nullable=False, default="")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    tier_required: Mapped[str] = mapped_column(String, nullable=False, default="plus")
    comprehension_quiz_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    required_data_sources: Mapped[Any] = mapped_column(JSON, nullable=False, default=list)
    default_universe: Mapped[Any] = mapped_column(JSON, nullable=False, default=list)
    parameters: Mapped[Any] = mapped_column(JSON, nullable=False, default=dict)
    entry_conditions: Mapped[Any] = mapped_column(JSON, nullable=False, default=list)
    exit_conditions: Mapped[Any] = mapped_column(JSON, nullable=False, default=list)
    context_conditions: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    structure_type: Mapped[str] = mapped_column(String, nullable=False, default="simple")
    execution_schedule: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    signal_duration_required: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    category_accent_from: Mapped[str] = mapped_column(String, nullable=False, default="#10b981")
    category_accent_to: Mapped[str] = mapped_column(String, nullable=False, default="#06b6d4")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
