"""SignalGate — discipline filter trace for each generated signal.

One row per BotSignal. Records which of the 3 gates passed/failed
and the underlying scores, so we can answer "why didn't this fire?"
without re-running the strategy.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class SignalGate(Base):
    __tablename__ = "signal_gates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    signal_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("bot_signals.id"), nullable=True, index=True
    )
    bot_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    strategy: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)
    side: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)

    # Gate 1: regime
    regime_gate_passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    regime_current: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    regime_required: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)

    # Gate 2: composite score
    composite_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    composite_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    score_gate_passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Gate 3: confluence (3 of 5)
    confluence_factors_passed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confluence_required: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    confluence_gate_passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Final outcome
    final_decision: Mapped[str] = mapped_column(String(20), nullable=False, default="executed")  # executed|filtered
    filter_reason: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)  # regime_mismatch|score_below_threshold|insufficient_confluence|multiple

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    __table_args__ = (
        Index("idx_signal_gates_bot_created", "bot_name", "created_at"),
        Index("idx_signal_gates_decision_created", "final_decision", "created_at"),
    )
