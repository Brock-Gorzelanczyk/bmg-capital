"""SQLAlchemy model for bot_daily_journals — Phase 1 closed-loop learning system.

One row per (allocation_id, journal_date). Written by the nightly
daily_journal job; read by the /api/admin/strategy-journal/* endpoints.

Bot_id is denormalised from BotProfile.name for query speed.
User_id is denormalised from BotAllocation.user_id for future multi-user expansion.

Standing decisions:
  - No cascade delete on allocation_id FK (bot_allocations rows are never deleted).
  - starting_capital_cents is the day's working capital baseline only — NOT
    used for any all-time % calc (decision-history item 10).
"""
from __future__ import annotations

from datetime import datetime, date
from typing import Optional

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class BotDailyJournal(Base):
    __tablename__ = "bot_daily_journals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    allocation_id: Mapped[int] = mapped_column(Integer, ForeignKey("bot_allocations.id"), nullable=False, index=True)
    bot_id: Mapped[str] = mapped_column(String, nullable=False, index=True)           # BotProfile.name (denormalised)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)         # denormalised from allocation
    journal_date: Mapped[date] = mapped_column(Date, nullable=False)
    sleeve: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    asset_class: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    starting_capital_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ending_pv_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    day_pnl_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    day_return_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    trades_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    winning_trades: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    losing_trades: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    win_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    avg_winner_cents: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    avg_loser_cents: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    profit_factor: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    avg_hold_minutes: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max_concurrent_positions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    end_of_day_positions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    end_of_day_deployed_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deployment_pct_avg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    regime_vix_band: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    regime_trend: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    regime_btc_dom_band: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    strategies_breakdown_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON dict
    errors_24h: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sentry_issues_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)         # JSON array
    body_md: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    frontmatter_yaml: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(__import__("datetime").timezone.utc),
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("allocation_id", "journal_date", name="uq_bot_daily_journals_alloc_date"),
    )
