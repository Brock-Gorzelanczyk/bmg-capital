from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LinkedBrokerage(Base):
    __tablename__ = "linked_brokerages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    institution_name: Mapped[str] = mapped_column(String, nullable=False)
    plaid_item_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    plaid_access_token: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, default="active", nullable=False)
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ExternalHolding(Base):
    __tablename__ = "external_holdings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    linked_brokerage_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("linked_brokerages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    cost_basis: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    current_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    security_type: Mapped[str] = mapped_column(String, nullable=False)  # equity | etf | mutual_fund | crypto
    synced_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
