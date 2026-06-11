"""SQLAlchemy models for live performance alerts, decay signals, factor attribution, HRP weights."""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LivePerformanceAlert(Base):
    __tablename__ = "live_performance_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bot_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    severity: Mapped[str | None] = mapped_column(String, nullable=True)
    zscore: Mapped[float | None] = mapped_column(Float, nullable=True)
    live_sharpe: Mapped[float | None] = mapped_column(Float, nullable=True)
    backtest_sharpe: Mapped[float | None] = mapped_column(Float, nullable=True)
    ks_diverged: Mapped[int | None] = mapped_column(Integer, nullable=True)
    posterior_prob_below_0_5: Mapped[float | None] = mapped_column(Float, nullable=True)
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DecaySignal(Base):
    __tablename__ = "decay_signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bot_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    ou_half_life_days: Mapped[float | None] = mapped_column(Float, nullable=True)
    sprt_llr: Mapped[float | None] = mapped_column(Float, nullable=True)
    sprt_alarm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cusum_up: Mapped[float | None] = mapped_column(Float, nullable=True)
    cusum_down: Mapped[float | None] = mapped_column(Float, nullable=True)
    cusum_alarm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rolling_ic: Mapped[float | None] = mapped_column(Float, nullable=True)

    __table_args__ = (
        UniqueConstraint("bot_id", "snapshot_date", name="uq_decay_bot_date"),
    )


class FactorAttribution(Base):
    __tablename__ = "factor_attribution"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bot_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    alpha_daily: Mapped[float | None] = mapped_column(Float, nullable=True)
    alpha_annualized: Mapped[float | None] = mapped_column(Float, nullable=True)
    alpha_tstat: Mapped[float | None] = mapped_column(Float, nullable=True)
    beta_market: Mapped[float | None] = mapped_column(Float, nullable=True)
    beta_smb: Mapped[float | None] = mapped_column(Float, nullable=True)
    beta_hml: Mapped[float | None] = mapped_column(Float, nullable=True)
    r_squared: Mapped[float | None] = mapped_column(Float, nullable=True)
    alpha_significant: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        UniqueConstraint("bot_id", "snapshot_date", name="uq_factor_bot_date"),
    )


class HrpRecommendedWeight(Base):
    __tablename__ = "hrp_recommended_weights"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bot_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    current_weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    hrp_weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    cluster_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        UniqueConstraint("bot_id", "snapshot_date", name="uq_hrp_bot_date"),
    )
