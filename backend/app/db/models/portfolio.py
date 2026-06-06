from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Portfolio(Base):
    __tablename__ = "portfolios_archived"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, server_default=func.now()
    )
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)

    positions: Mapped[list[Position]] = relationship(
        "Position", back_populates="portfolio", cascade="all, delete-orphan"
    )


class Position(Base):
    __tablename__ = "positions_archived"

    __table_args__ = (UniqueConstraint("portfolio_id", "symbol"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    portfolio_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("portfolios_archived.id", ondelete="CASCADE"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    shares: Mapped[float] = mapped_column(Float, nullable=False)
    average_cost: Mapped[float] = mapped_column(Float, nullable=False)
    opened_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, server_default=func.now()
    )

    portfolio: Mapped[Portfolio] = relationship("Portfolio", back_populates="positions")
