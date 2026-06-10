"""SQLAlchemy models for The Forge — user-built custom bots."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, Float, ForeignKey, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class UserForgeBot(Base):
    __tablename__ = "user_forge_bots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    # JSON-encoded lists stored as TEXT (SQLite compatibility)
    strategies: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    watchlist: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    capital_pct: Mapped[float] = mapped_column(Float, nullable=False, default=5.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    last_scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    signals: Mapped[list[UserForgeSignal]] = relationship(
        "UserForgeSignal", back_populates="forge_bot", cascade="all, delete-orphan"
    )


class UserForgeSignal(Base):
    __tablename__ = "user_forge_signals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    forge_bot_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_forge_bots.id", ondelete="CASCADE"), nullable=False
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

    forge_bot: Mapped[UserForgeBot] = relationship("UserForgeBot", back_populates="signals")
