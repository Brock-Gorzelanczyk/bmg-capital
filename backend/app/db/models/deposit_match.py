from __future__ import annotations
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from app.db.base import Base

class DepositMatch(Base):
    __tablename__ = "deposit_matches"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    deposit_amount = Column(Float, nullable=False)
    match_pct = Column(Float, nullable=False)
    match_amount = Column(Float, nullable=False)
    deposit_type = Column(String, default="recurring")  # recurring | ira | acat
    status = Column(String, default="pending")  # pending | credited | expired
    created_at = Column(DateTime, default=datetime.utcnow)
    credited_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
