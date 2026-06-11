"""SQLAlchemy models for the strategy candidate pipeline."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class StrategyCandidate(Base):
    __tablename__ = "strategy_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    asset_class: Mapped[str | None] = mapped_column(String, nullable=True)
    style: Mapped[str | None] = mapped_column(String, nullable=True)
    state: Mapped[str] = mapped_column(String, nullable=False, default="CANDIDATE")
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    candidate_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("strategy_candidates.id"), nullable=True, index=True
    )
    job_id: Mapped[str | None] = mapped_column(String, unique=True, nullable=True, index=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="queued")
    start_date: Mapped[str | None] = mapped_column(String, nullable=True)
    end_date: Mapped[str | None] = mapped_column(String, nullable=True)
    params_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    gross_sharpe: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_sharpe: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_drawdown_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    win_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    profit_factor: Mapped[float | None] = mapped_column(Float, nullable=True)
    beta_spy: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_cost_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    n_trades: Mapped[int | None] = mapped_column(Integer, nullable=True)
    equity_curve_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class WfaRun(Base):
    __tablename__ = "wfa_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    candidate_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("strategy_candidates.id"), nullable=True, index=True
    )
    job_id: Mapped[str | None] = mapped_column(String, unique=True, nullable=True, index=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="queued")
    is_years: Mapped[float | None] = mapped_column(Float, nullable=True)
    oos_years: Mapped[float | None] = mapped_column(Float, nullable=True)
    embargo_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    wfe: Mapped[float | None] = mapped_column(Float, nullable=True)
    pbo: Mapped[float | None] = mapped_column(Float, nullable=True)
    dsr: Mapped[float | None] = mapped_column(Float, nullable=True)
    aggregate_oos_sharpe: Mapped[float | None] = mapped_column(Float, nullable=True)
    aggregate_is_sharpe: Mapped[float | None] = mapped_column(Float, nullable=True)
    n_walks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    walks_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class CandidateStateHistory(Base):
    __tablename__ = "candidate_state_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    candidate_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("strategy_candidates.id"), nullable=True, index=True
    )
    from_state: Mapped[str | None] = mapped_column(String, nullable=True)
    to_state: Mapped[str | None] = mapped_column(String, nullable=True)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    triggered_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
