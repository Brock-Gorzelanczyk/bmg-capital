from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Float, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OnChainMetric(Base):
    __tablename__ = "onchain_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)   # BTC|ETH|SOL
    metric: Mapped[str] = mapped_column(String(100), nullable=False, index=True)  # mvrv_z|sopr_sth|funding_rate|...
    source: Mapped[str] = mapped_column(String(50), nullable=False)               # glassnode|coinglass|lunarcrush
    value: Mapped[float] = mapped_column(Float, nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    raw_payload: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("symbol", "metric", "source", "ts", name="uq_onchain_metric"),
    )
