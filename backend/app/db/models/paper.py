from __future__ import annotations
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from sqlalchemy import DateTime, Float, Integer, String, Boolean, JSON, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

STARTING_BALANCE = 100_000.0

class PaperAccount(Base):
    __tablename__ = "paper_accounts_archived"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True, unique=True)
    cash: Mapped[float] = mapped_column(Float, nullable=False, default=STARTING_BALANCE)
    starting_balance: Mapped[float] = mapped_column(Float, nullable=False, default=STARTING_BALANCE)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), server_default=func.now())

class PaperPosition(Base):
    __tablename__ = "paper_positions_archived"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    qty: Mapped[float] = mapped_column(Float, nullable=False)
    avg_cost: Mapped[float] = mapped_column(Float, nullable=False)
    prev_close: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # for day P&L
    opened_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), server_default=func.now())

class PaperOrder(Base):
    __tablename__ = "paper_orders_archived"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    side: Mapped[str] = mapped_column(String, nullable=False)  # buy | sell
    qty: Mapped[float] = mapped_column(Float, nullable=False)
    notional: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # dollar-based order
    order_type: Mapped[str] = mapped_column(String, nullable=False, default="market")
    limit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    stop_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    take_profit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    stop_loss_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    trailing_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    trailing_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # amount | percent
    tif: Mapped[str] = mapped_column(String, nullable=False, default="day")  # day | gtc | ioc | fok
    extended_hours: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="working")  # working | filled | cancelled | rejected | expired
    fill_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fill_qty: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    slippage: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reject_reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    parent_order_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # for bracket/OCO legs
    filled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), server_default=func.now())

class PaperTransaction(Base):
    """Realized P&L ledger — one row per fill that closes or reduces a position."""
    __tablename__ = "paper_transactions_archived"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    order_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    side: Mapped[str] = mapped_column(String, nullable=False)  # buy | sell | reset
    qty: Mapped[float] = mapped_column(Float, nullable=False)
    fill_price: Mapped[float] = mapped_column(Float, nullable=False)
    cost_basis: Mapped[float] = mapped_column(Float, nullable=False)  # avg_cost at time of sell
    realized_pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    notes: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), server_default=func.now())

class PaperDailySnapshot(Base):
    """End-of-day equity snapshot for performance chart."""
    __tablename__ = "paper_daily_snapshots_archived"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    date: Mapped[str] = mapped_column(String, nullable=False)  # YYYY-MM-DD
    equity: Mapped[float] = mapped_column(Float, nullable=False)
    cash: Mapped[float] = mapped_column(Float, nullable=False)
    positions_value: Mapped[float] = mapped_column(Float, nullable=False)
    day_pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), server_default=func.now())
