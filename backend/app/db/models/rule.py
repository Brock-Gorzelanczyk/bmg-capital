from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserRule(Base):
    __tablename__ = "user_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Trigger
    trigger_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # "price_above" | "price_below" | "vix_above" | "rsi_below" | "rsi_above" | "regime_is"
    trigger_symbol: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    trigger_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    trigger_regime: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Action
    action_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # "buy" | "sell" | "notify" | "reduce_position"
    action_symbol: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    action_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    action_unit: Mapped[str] = mapped_column(String, default="dollars", nullable=False)
    # "dollars" | "shares" | "pct_of_account"

    last_triggered: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    trigger_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, server_default=func.now()
    )
