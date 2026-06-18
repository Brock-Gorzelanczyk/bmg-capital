from __future__ import annotations

from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.sql import func

from app.db.base import Base


class WorkshopChart(Base):
    __tablename__ = "workshop_charts"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    ticker = Column(String(20), nullable=False)
    strategy_id = Column(String(80), nullable=False)
    name = Column(String(200), nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Setup quality rating (Phase 4)
    rating_overall = Column(Integer, nullable=True)
    rating_chart_pattern = Column(Integer, nullable=True)
    rating_indicator_confluence = Column(Integer, nullable=True)
    rating_volume = Column(Integer, nullable=True)
    rating_risk_reward = Column(Integer, nullable=True)
    rating_conviction = Column(String(10), nullable=True)  # low | medium | high
    rating_notes = Column(Text, nullable=True)
    rating_updated_at = Column(DateTime(timezone=True), nullable=True)
