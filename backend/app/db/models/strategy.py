from __future__ import annotations

from datetime import datetime, date
from typing import Optional

from sqlalchemy import DateTime, Date, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class StrategyTrade(Base):
    __tablename__ = "strategy_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    preset_key: Mapped[str] = mapped_column(String, nullable=False)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    entry_date: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, server_default=func.now()
    )
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    shares: Mapped[float] = mapped_column(Float, nullable=False)
    stop_price: Mapped[float] = mapped_column(Float, nullable=False)
    target_price: Mapped[float] = mapped_column(Float, nullable=False)
    exit_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    exit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    exit_reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="open", nullable=False)
    candidate_since: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    entry_trigger: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    entry_notes: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    atr: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    risk_dollars: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    last_known_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    prev_close: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


class DailyLog(Base):
    __tablename__ = "strategy_daily_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    logged_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, server_default=func.now()
    )
    log_date: Mapped[date] = mapped_column(Date, nullable=False)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    symbol: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    preset_key: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    preset_label: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pnl_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    notes: Mapped[str] = mapped_column(String, nullable=False, default="")
    trade_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)


class DailyEquitySnapshot(Base):
    __tablename__ = "strategy_equity_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    portfolio_value: Mapped[float] = mapped_column(Float, nullable=False)
    realized_pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    open_pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    open_positions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    candidates: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    new_entries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    exits_today: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
