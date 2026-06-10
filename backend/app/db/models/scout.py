"""SQLAlchemy models for Strategy Scout — user-defined (ticker, strategy) signal monitors."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, Float, ForeignKey, Text, DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class UserScoutSetup(Base):
    __tablename__ = "user_scout_setups"
    __table_args__ = (
        UniqueConstraint("user_id", "ticker", "strategy_id", name="uq_scout_setup"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    ticker: Mapped[str] = mapped_column(Text, nullable=False)
    strategy_id: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    last_scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    signals: Mapped[list[UserScoutSignal]] = relationship(
        "UserScoutSignal", back_populates="setup", cascade="all, delete-orphan"
    )


class UserScoutSignal(Base):
    __tablename__ = "user_scout_signals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    setup_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_scout_setups.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    ticker: Mapped[str] = mapped_column(Text, nullable=False)
    strategy_id: Mapped[str] = mapped_column(Text, nullable=False)
    side: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    entry_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    discord_message_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    setup: Mapped[UserScoutSetup] = relationship("UserScoutSetup", back_populates="signals")
