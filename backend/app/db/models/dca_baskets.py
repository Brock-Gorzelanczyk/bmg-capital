from __future__ import annotations
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, ForeignKey, JSON
from sqlalchemy.orm import relationship
from app.db.base import Base

class DCABasket(Base):
    __tablename__ = "dca_baskets"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    total_amount = Column(Float, nullable=False)
    frequency = Column(String, default="weekly")  # daily | weekly | biweekly | monthly
    day_of_week = Column(Integer, nullable=True)
    status = Column(String, default="active")  # active | paused | cancelled
    executions_count = Column(Integer, default=0)
    total_invested = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    assets = relationship("DCABasketAsset", back_populates="basket", cascade="all, delete-orphan")

class DCABasketAsset(Base):
    __tablename__ = "dca_basket_assets"
    id = Column(Integer, primary_key=True, index=True)
    basket_id = Column(Integer, ForeignKey("dca_baskets.id", ondelete="CASCADE"), nullable=False)
    symbol = Column(String, nullable=False)
    allocation_pct = Column(Float, nullable=False)
    asset_type = Column(String, default="etf")  # stock | crypto | etf
    basket = relationship("DCABasket", back_populates="assets")
