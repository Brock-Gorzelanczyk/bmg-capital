from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

try:
    from sqlalchemy import JSON
except ImportError:
    from sqlalchemy import Text as JSON  # type: ignore

from app.db.base import Base


class DailyBrief(Base):
    __tablename__ = "daily_briefs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    brief_date: Mapped[date] = mapped_column(Date, nullable=False)
    content_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    reading_level: Mapped[str] = mapped_column(String, nullable=False, default="investor")
    generated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, server_default=func.now()
    )
