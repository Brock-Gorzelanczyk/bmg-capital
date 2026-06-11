"""SQLAlchemy models for signal IC metrics and classification alerts."""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, Float, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SignalIcMetric(Base):
    __tablename__ = "signal_ic_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    window_days: Mapped[int] = mapped_column(Integer, nullable=False)
    n_signals: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ic_spearman: Mapped[float | None] = mapped_column(Float, nullable=True)
    ic_pearson: Mapped[float | None] = mapped_column(Float, nullable=True)
    ic_p_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    ic_t_stat: Mapped[float | None] = mapped_column(Float, nullable=True)
    direction_hit_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_correlation: Mapped[float | None] = mapped_column(Float, nullable=True)
    classification: Mapped[str | None] = mapped_column(String, nullable=True)
    recommendation: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        UniqueConstraint("strategy_name", "snapshot_date", "window_days", name="uq_ic_strategy_date_window"),
        Index("idx_ic_strategy_date", "strategy_name", "snapshot_date"),
    )


class SignalIcAlert(Base):
    __tablename__ = "signal_ic_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    ic_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    classification: Mapped[str | None] = mapped_column(String, nullable=True)
    previous_classification: Mapped[str | None] = mapped_column(String, nullable=True)
    discord_posted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by: Mapped[str | None] = mapped_column(String, nullable=True)
