from __future__ import annotations
import secrets
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from app.db.base import Base

class CFPBooking(Base):
    __tablename__ = "cfp_bookings"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    slot_datetime = Column(DateTime, nullable=False)
    topic = Column(String, default="")
    format = Column(String, default="video")  # video | phone
    confirmation_id = Column(String, default=lambda: secrets.token_hex(4).upper())
    zoom_link = Column(String, default="https://zoom.us/j/99999999999?pwd=demo")
    status = Column(String, default="confirmed")
    created_at = Column(DateTime, default=datetime.utcnow)
