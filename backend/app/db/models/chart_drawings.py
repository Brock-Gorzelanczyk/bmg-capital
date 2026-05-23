from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

class ChartDrawing(Base):
    __tablename__ = "chart_drawings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    timeframe: Mapped[str] = mapped_column(String, nullable=False)
    drawings_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, server_default=func.now())
