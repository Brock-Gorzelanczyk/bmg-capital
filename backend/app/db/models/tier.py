from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column
from typing import Optional
from datetime import datetime
from app.db.base import Base

class UserTier(Base):
    __tablename__ = "user_tiers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, unique=True, index=True)
    tier: Mapped[str] = mapped_column(String, nullable=False, default="free")  # free|plus|premium
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")  # active|trialing|past_due|cancelled
    billing_interval: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # monthly|annual
    trial_ends_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    current_period_end: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    stripe_customer_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    stripe_subscription_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    stripe_sub_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # keep for migration compat
    aum_override: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # tier granted by AUM
    aum_override_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
