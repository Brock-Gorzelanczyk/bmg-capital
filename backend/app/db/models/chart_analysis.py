from __future__ import annotations
from datetime import datetime
from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class ChartAnalysis(Base):
    __tablename__ = "chart_analyses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String, nullable=False, index=True)
    timeframe: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    thesis: Mapped[str] = mapped_column(Text, nullable=False, default="")
    drawings_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    ai_analysis_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, server_default=func.now())
