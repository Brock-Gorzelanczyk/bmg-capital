from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class StrategyMeta(Base):
    __tablename__ = "strategy_meta"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    module_name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    tagline: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)           # Momentum, Mean Reversion, etc.
    asset_class: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)         # stocks, crypto, options, multi
    time_horizon: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)        # intraday, swing, position, long_term
    difficulty: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)          # beginner, intermediate, advanced
    risk_profile: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)        # conservative, standard, aggressive
    published_sharpe: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    win_rate_pub: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max_dd_pub: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    decay_risk: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)          # low, medium, high
    source_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    paper_citation: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    required_inputs: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    suggested_bot: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    description_md: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    mechanics_md: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    when_works_md: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    when_fails_md: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    data_feed: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)          # free_alpaca, polygon_paid, options
    is_top_pick: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    popularity_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    added_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), server_default=func.now()
    )
    # Quant research evidence fields (A1)
    t_stat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    evidence_tier: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # very_strong|strong|moderate|weak
    haircut_pct: Mapped[int] = mapped_column(Integer, default=30, nullable=False)    # default 30%
    oos_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    @property
    def adjusted_sharpe(self) -> Optional[float]:
        """Published Sharpe after haircut (Barroso & Santa-Clara / AQR convention)."""
        if self.published_sharpe is None:
            return None
        return self.published_sharpe * (1 - self.haircut_pct / 100)
