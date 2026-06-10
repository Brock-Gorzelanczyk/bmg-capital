from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    BigInteger, Boolean, DateTime, Index, Integer, Numeric,
    String, Text, ARRAY, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class AgentEvent(Base):
    __tablename__ = "agent_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)  # info|warning|critical
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_agent_events_open", "state", postgresql_where="state = 'open'"),
        Index("idx_agent_events_fingerprint", "fingerprint"),
    )


class AgentFix(Base):
    __tablename__ = "agent_fixes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fixer_agent: Mapped[str] = mapped_column(String(64), nullable=False)
    pr_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    pr_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    files_changed: Mapped[Optional[list]] = mapped_column(ARRAY(Text), nullable=True)
    diff_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    llm_model: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    cost_usd: Mapped[Optional[float]] = mapped_column(Numeric(10, 6), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)  # proposed|merged|rejected|failed
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AgentCircuitBreaker(Base):
    __tablename__ = "agent_circuit_breakers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    breaker_type: Mapped[str] = mapped_column(String(32), nullable=False)
    key: Mapped[str] = mapped_column(String(256), nullable=False)
    tripped_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resets_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index(
            "idx_agent_breakers_active",
            "resets_at",
            postgresql_where="resets_at > NOW()",
        ),
    )


class AgentEscalation(Base):
    __tablename__ = "agent_escalations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    paste_ready: Mapped[str] = mapped_column(Text, nullable=False)
    sent_to_discord: Mapped[bool] = mapped_column(Boolean, default=False)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    user_action: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # fixed|ignored|snoozed
