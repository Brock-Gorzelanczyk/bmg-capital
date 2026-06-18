from __future__ import annotations
from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func
from app.db.base import Base

class PriceAlert(Base):
    __tablename__ = "price_alerts"
    id             = Column(Integer, primary_key=True)
    workshop_chart_id = Column(Integer, ForeignKey("workshop_charts.id", ondelete="CASCADE"), nullable=True, index=True)
    user_id        = Column(Integer, nullable=False, index=True)
    ticker         = Column(String(20), nullable=False)
    price_cents    = Column(Integer, nullable=False)   # price * 100
    direction      = Column(String(10), nullable=False) # "above" | "below"
    message        = Column(Text, nullable=True)
    status         = Column(String(20), nullable=False, default="armed")  # armed|triggered|cancelled|snoozed
    notif_discord  = Column(Boolean, nullable=False, default=True)
    notif_inapp    = Column(Boolean, nullable=False, default=True)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())
    triggered_at   = Column(DateTime(timezone=True), nullable=True)
