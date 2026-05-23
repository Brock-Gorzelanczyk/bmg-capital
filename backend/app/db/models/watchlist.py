from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Watchlist(Base):
    __tablename__ = "watchlists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, server_default=func.now()
    )
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)

    items: Mapped[list[WatchlistItem]] = relationship(
        "WatchlistItem", back_populates="watchlist", cascade="all, delete-orphan"
    )


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"

    __table_args__ = (UniqueConstraint("watchlist_id", "symbol"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    watchlist_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("watchlists.id", ondelete="CASCADE"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    added_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, server_default=func.now()
    )

    watchlist: Mapped[Watchlist] = relationship("Watchlist", back_populates="items")
