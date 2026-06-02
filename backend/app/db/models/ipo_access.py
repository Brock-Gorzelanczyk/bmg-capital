from __future__ import annotations
from datetime import datetime, date
from sqlalchemy import Column, Integer, String, Float, DateTime, Date, Boolean, ForeignKey
from app.db.base import Base

class IPODeal(Base):
    __tablename__ = "ipo_deals"
    id = Column(Integer, primary_key=True, index=True)
    company_name = Column(String, nullable=False)
    ticker = Column(String, nullable=True)
    expected_date = Column(Date, nullable=True)
    price_range_low = Column(Float, nullable=True)
    price_range_high = Column(Float, nullable=True)
    description = Column(String, default="")
    sector = Column(String, default="Technology")
    lead_underwriter = Column(String, nullable=True)
    status = Column(String, default="upcoming")  # upcoming | pricing | open | closed | trading
    min_tier = Column(String, default="premium")  # free | plus | premium
    created_at = Column(DateTime, default=datetime.utcnow)

class IPORegistration(Base):
    __tablename__ = "ipo_registrations"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    ipo_deal_id = Column(Integer, ForeignKey("ipo_deals.id"), nullable=False)
    requested_amount = Column(Float, default=500.0)
    status = Column(String, default="waitlisted")  # waitlisted | allocated | missed | cancelled
    created_at = Column(DateTime, default=datetime.utcnow)
