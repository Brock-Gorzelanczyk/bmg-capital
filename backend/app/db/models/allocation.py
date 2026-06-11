"""SQLAlchemy models for bot performance stats and tier history."""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import BigInteger, Date, DateTime, Float, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class BotPerformanceStats(Base):
    """Daily snapshot of per-allocation performance metrics."""

    __tablename__ = "bot_performance_stats"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    allocation_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("bot_allocations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stat_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # Return metrics
    total_return_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    return_30d_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    return_7d_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    win_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    profit_factor: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_drawdown_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    sharpe_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Trade counts
    total_trades: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    winning_trades: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    losing_trades: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Capital
    starting_capital_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_value_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    realized_pnl_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class BotTierHistory(Base):
    """Records each time a bot's allocation tier changes."""

    __tablename__ = "bot_tier_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    allocation_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("bot_allocations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    previous_tier: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_tier: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    triggered_by: Mapped[str] = mapped_column(Text, nullable=False, default="daily_job")

    # Snapshot of key metrics at time of transition
    return_30d_pct_at_change: Mapped[float | None] = mapped_column(Float, nullable=True)
    win_rate_at_change: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_drawdown_at_change: Mapped[float | None] = mapped_column(Float, nullable=True)
    trade_count_at_change: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
