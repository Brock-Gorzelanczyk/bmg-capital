from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class BarCache(Base):
    __tablename__ = "bar_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    cache_key: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    data_json: Mapped[str] = mapped_column(String, nullable=False)  # compressed JSON
    cached_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
