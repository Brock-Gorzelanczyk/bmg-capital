from __future__ import annotations

from datetime import datetime, date, timezone
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, JSON, String, Text, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class BotProfile(Base):
    __tablename__ = "bot_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    asset_class: Mapped[str] = mapped_column(String, nullable=False)  # stock|crypto
    config_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), server_default=func.now()
    )


class BotAllocation(Base):
    __tablename__ = "bot_allocations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    profile_id: Mapped[int] = mapped_column(Integer, ForeignKey("bot_profiles.id"), nullable=False, index=True)
    capital_pct: Mapped[float] = mapped_column(Float, default=10.0, nullable=False)
    risk_profile: Mapped[str] = mapped_column(String, default="standard", nullable=False)  # conservative|standard|aggressive
    paper_mode: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    go_live_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc), nullable=False
    )


class BotSignal(Base):
    __tablename__ = "bot_signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    allocation_id: Mapped[int] = mapped_column(Integer, ForeignKey("bot_allocations.id"), nullable=False, index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    side: Mapped[str] = mapped_column(String, nullable=False)  # buy|sell|hold
    confidence: Mapped[float] = mapped_column(Float, nullable=False)  # 0-1
    size_hint: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    strategy: Mapped[Optional[str]] = mapped_column(String, nullable=True)


class BotPosition(Base):
    __tablename__ = "bot_positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    allocation_id: Mapped[int] = mapped_column(Integer, ForeignKey("bot_allocations.id"), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    qty: Mapped[float] = mapped_column(Float, nullable=False)
    avg_cost_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    exit_reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    is_paper: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class BotTrade(Base):
    __tablename__ = "bot_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    allocation_id: Mapped[int] = mapped_column(Integer, ForeignKey("bot_allocations.id"), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    side: Mapped[str] = mapped_column(String, nullable=False)  # buy|sell
    qty: Mapped[float] = mapped_column(Float, nullable=False)
    fill_price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    fees_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    alpaca_order_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    position_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("bot_positions.id"), nullable=True)
    is_paper: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class BotDailyPnL(Base):
    __tablename__ = "bot_daily_pnl"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    allocation_id: Mapped[int] = mapped_column(Integer, ForeignKey("bot_allocations.id"), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    realized_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unrealized_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fees_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class GoLiveWaitlist(Base):
    __tablename__ = "go_live_waitlist"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    bot_profile_id: Mapped[int] = mapped_column(Integer, ForeignKey("bot_profiles.id"), nullable=False, index=True)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    opted_out_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
