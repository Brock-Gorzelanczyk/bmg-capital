"""DB model for regime history — daily snapshots of composite market regime."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Date, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RegimeSnapshot(Base):
    """One row per trading day — confirmed regime after persistence filter."""
    __tablename__ = "regime_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_date: Mapped[datetime] = mapped_column(Date, nullable=False, unique=True, index=True)
    regime: Mapped[str] = mapped_column(String, nullable=False)
    raw_regime: Mapped[str | None] = mapped_column(String, nullable=True)  # pre-filter label
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    vix_level: Mapped[float | None] = mapped_column(Float, nullable=True)
    spx_vs_200ma: Mapped[float | None] = mapped_column(Float, nullable=True)   # SPY close / 200MA
    hy_spread_proxy: Mapped[float | None] = mapped_column(Float, nullable=True) # HYG/IEF ratio
    vix_ts_slope: Mapped[float | None] = mapped_column(Float, nullable=True)   # VIX/VIX3M
    signals_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
