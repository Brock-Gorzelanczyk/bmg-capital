from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

try:
    from sqlalchemy import JSON
except ImportError:
    from sqlalchemy import Text as JSON  # type: ignore

from app.db.base import Base


class DailyRecap(Base):
    __tablename__ = "daily_recaps"

    __table_args__ = (
        UniqueConstraint("user_id", "recap_date", name="uq_daily_recaps_user_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    recap_date: Mapped[str] = mapped_column(String(10), nullable=False)  # YYYY-MM-DD
    market_summary: Mapped[dict] = mapped_column(JSON, nullable=True)
    strategy_summary: Mapped[dict] = mapped_column(JSON, nullable=True)
    top_setups: Mapped[list] = mapped_column(JSON, nullable=True)
    narrative: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, server_default=func.now()
    )
