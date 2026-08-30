"""SQLAlchemy model for confluence_picks table (m101).

See research/2026-08-20-confluence-selection-framework.md for framework
design + expected hit rates + anti-goodhart rules.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, Float, Integer, String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ConfluencePick(Base):
    __tablename__ = "confluence_picks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    ticker: Mapped[str] = mapped_column(String, nullable=False, index=True)
    entry_date: Mapped[str] = mapped_column(String, nullable=False, index=True)  # YYYY-MM-DD
    entry_price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    spy_price_cents_at_entry: Mapped[int] = mapped_column(Integer, nullable=False)

    # Signals — locked at entry, never mutated
    insider_cluster: Mapped[bool] = mapped_column(Boolean, nullable=False)
    short_surprise_dir: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    analyst_revisions_dir: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    fundamental_momentum: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    inst_13f_net_add: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    signals_fired_count: Mapped[int] = mapped_column(Integer, nullable=False)

    # Thesis — locked at entry
    thesis_text: Mapped[str] = mapped_column(String, nullable=False)
    target_price_cents: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    invalidation_price_cents: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    horizon_months: Mapped[int] = mapped_column(Integer, nullable=False)

    # Close — filled by close endpoint or auto-close cron
    closed_date: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)  # YYYY-MM-DD
    closed_price_cents: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    spy_price_cents_at_close: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    close_reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Denormalized computed fields (populated on close)
    absolute_return_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    excess_vs_spy_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    hit_win_criterion: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    created_by: Mapped[str] = mapped_column(String, nullable=False, default="confluence_framework_v1")
    notes: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )

    # m102 arm state — makes a pick executable, not just journaled
    arm_state: Mapped[Optional[str]] = mapped_column(String, nullable=True, default="LOGGED")
    arm_mode: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    arm_expires_at: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    size_dollars_cents: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=500000)
    play_a_trigger_price_cents: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    play_a_stop_price_cents: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    play_a_volume_multiple: Mapped[Optional[float]] = mapped_column(Float, nullable=True, default=1.2)
    play_b_trigger_price_cents: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    play_b_stop_price_cents: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    target_1_cents: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    target_2_cents: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    alpaca_bracket_order_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    filled_at: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    filled_price_cents: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # m103 rule-compliance record — stored as JSON string. Populated at pick creation
    # by services/rule_evaluator.py from vault:research/decision-rules.md.
    # Schema: {rules: {RULE-ID: {verdict, notes}, ...}, rules_version, evaluated_by}
    rule_compliance: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    rule_compliance_evaluated_at: Mapped[Optional[str]] = mapped_column(String, nullable=True)
