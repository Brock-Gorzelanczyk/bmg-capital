from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class AlertConfig(Base):
    __tablename__ = "alert_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    signal_type: Mapped[str] = mapped_column(String, nullable=False)
    threshold: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, server_default=func.now()
    )
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)

    triggers: Mapped[list[AlertTrigger]] = relationship(
        "AlertTrigger", back_populates="alert_config", cascade="all, delete-orphan"
    )


class AlertTrigger(Base):
    __tablename__ = "alert_triggers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    alert_config_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("alert_configs.id", ondelete="CASCADE"), nullable=False
    )
    signal_type: Mapped[str] = mapped_column(String, nullable=False)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, server_default=func.now()
    )
    message: Mapped[str] = mapped_column(String, nullable=False, default="")

    alert_config: Mapped[AlertConfig] = relationship("AlertConfig", back_populates="triggers")


class SignalState(Base):
    __tablename__ = "signal_states"

    __table_args__ = (UniqueConstraint("symbol", "signal_type"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    signal_type: Mapped[str] = mapped_column(String, nullable=False)
    state: Mapped[str] = mapped_column(String, default="inactive", nullable=False)
    last_triggered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    cooldown_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
