from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Pod(Base):
    __tablename__ = "pods"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String)
    color: Mapped[str] = mapped_column(String, default="#3B82F6")
    emoji: Mapped[str] = mapped_column(String, default="📊")
    allocated_capital: Mapped[float] = mapped_column(Float, default=0.0)
    drawdown_stop_pct: Mapped[float] = mapped_column(Float, default=7.0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_derisked: Mapped[bool] = mapped_column(Boolean, default=False)
    derisked_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    positions: Mapped[list[PodPosition]] = relationship(
        "PodPosition", back_populates="pod", cascade="all, delete-orphan"
    )


class PodPosition(Base):
    __tablename__ = "pod_positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pod_id: Mapped[int] = mapped_column(Integer, ForeignKey("pods.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    shares: Mapped[float] = mapped_column(Float, default=0.0)
    average_cost: Mapped[float] = mapped_column(Float, default=0.0)
    opened_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    pod: Mapped[Pod] = relationship("Pod", back_populates="positions")
