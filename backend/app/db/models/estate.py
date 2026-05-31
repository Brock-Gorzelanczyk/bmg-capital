from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class BeneficiaryRecord(Base):
    __tablename__ = "beneficiary_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    account_name: Mapped[str] = mapped_column(String, nullable=False)
    account_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # "retirement"|"brokerage"|"bank"|"life_insurance"
    beneficiary_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    beneficiary_relationship: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # "spouse"|"child"|"sibling"|"other"
    beneficiary_pct: Mapped[int] = mapped_column(Integer, default=100)
    has_tod: Mapped[bool] = mapped_column(Boolean, default=False)  # transfer-on-death designation
    has_pod: Mapped[bool] = mapped_column(Boolean, default=False)  # payable-on-death
    last_reviewed: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # ISO date string
    notes: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class DigitalAssetRecord(Base):
    __tablename__ = "digital_asset_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    asset_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # "crypto_wallet"|"password_manager"|"email"|"social"|"other"
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # "Ledger hardware wallet — BTC and ETH"
    location_hint: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # "Safe in office, combo 1234" (NOT the actual key)
    recovery_contact: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
