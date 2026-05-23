from __future__ import annotations

from datetime import datetime, date
from typing import Optional

from sqlalchemy import Date, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class JournalEntry(Base):
    __tablename__ = "journal_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    # Link to the paper order that triggered this entry (nullable for manual entries)
    paper_order_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    symbol: Mapped[str] = mapped_column(String, nullable=False, index=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    side: Mapped[str] = mapped_column(String, nullable=False)          # buy | sell
    qty: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    exit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pnl: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Subjective fields
    setup: Mapped[Optional[str]] = mapped_column(String, nullable=True)           # e.g. "breakout", "pullback"
    mood: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)           # 1-5
    confidence: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)    # 1-5
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    lessons: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)        # 1-5 post-trade quality
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
