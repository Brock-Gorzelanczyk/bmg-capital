from __future__ import annotations

import json
from datetime import date as date_type, datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RiskProfile(Base):
    __tablename__ = "robo_risk_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True, unique=True)
    time_horizon: Mapped[str] = mapped_column(String, nullable=False)  # "<2yr"|"2-5"|"5-10"|"10-20"|"20+"
    goal_type: Mapped[str] = mapped_column(String, nullable=False)     # "retirement"|"house"|"education"|"emergency"|"wealth"|"income"
    income_bracket: Mapped[str] = mapped_column(String, nullable=False)  # "<50k"|"50-100k"|"100-200k"|"200-500k"|"500k+"
    savings_rate: Mapped[float] = mapped_column(Float, nullable=False)   # 0.0-1.0 fraction of income saved monthly
    loss_tolerance: Mapped[str] = mapped_column(String, nullable=False)  # "sell_all"|"sell_some"|"hold"|"buy_more"
    experience: Mapped[str] = mapped_column(String, nullable=False)      # "none"|"some"|"experienced"|"professional"
    has_emergency_fund: Mapped[bool] = mapped_column(Boolean, nullable=False)
    risk_score: Mapped[float] = mapped_column(Float, nullable=False)     # 1.0-10.0 computed
    target_allocation: Mapped[str] = mapped_column(Text, nullable=False) # JSON {"equity": 0.60, "bonds": 0.35, "cash": 0.05}
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class RoboGoal(Base):
    __tablename__ = "robo_goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)              # "Retirement", "House Down Payment", etc.
    goal_type: Mapped[str] = mapped_column(String, nullable=False)
    target_amount: Mapped[float] = mapped_column(Float, nullable=False)
    target_date: Mapped[Optional[date_type]] = mapped_column(Date, nullable=True)  # nullable for open-ended
    current_balance: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    monthly_contribution: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(String, nullable=False, default="on_track")  # "on_track"|"behind"|"ahead"|"completed"
    glide_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON list
    probability_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)  # 0-100 Monte Carlo
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)       # user notes / AI coaching
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    def glide_path_list(self) -> list[dict]:
        return json.loads(self.glide_path) if self.glide_path else []


class CorePortfolio(Base):
    __tablename__ = "robo_core_portfolios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True, unique=True)
    total_value: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    ytd_return_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    target_allocation: Mapped[str] = mapped_column(Text, nullable=False)     # JSON {"VTI": 0.45, "VXUS": 0.15, ...}
    current_allocation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON updated at rebalance
    last_rebalanced_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    rebalance_needed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    drift_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)  # max absolute drift from target
    direct_index_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    direct_index_min_value: Mapped[float] = mapped_column(Float, nullable=False, default=25000.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class DirectIndexPortfolio(Base):
    __tablename__ = "robo_direct_index"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True, unique=True)
    total_value: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    tracking_error_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)  # vs S&P 500, target <1.0
    num_positions: Mapped[int] = mapped_column(Integer, nullable=False, default=200)        # typically 150-250
    sector_exclusions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)           # JSON list of sectors
    ticker_exclusions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)           # JSON list of tickers
    tilts: Mapped[Optional[str]] = mapped_column(Text, nullable=True)                       # JSON {"esg": true, ...}
    last_rebalanced_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    ytd_harvested_losses: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)  # total TLH savings this year
    estimated_tax_savings: Mapped[float] = mapped_column(Float, nullable=False, default=0.0) # ytd_harvested_losses * bracket
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class RebalanceLog(Base):
    __tablename__ = "robo_rebalance_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    trigger: Mapped[str] = mapped_column(String, nullable=False)   # "drift"|"cash_inflow"|"calendar"|"manual"
    summary: Mapped[str] = mapped_column(Text, nullable=False)     # plain-English 2-sentence explanation
    trades: Mapped[str] = mapped_column(Text, nullable=False)      # JSON list of trades
    total_value_before: Mapped[float] = mapped_column(Float, nullable=False)
    total_value_after: Mapped[float] = mapped_column(Float, nullable=False)
    taxes_triggered: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class WashSaleGuard(Base):
    __tablename__ = "robo_wash_sale_guard"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    sold_at: Mapped[date_type] = mapped_column(Date, nullable=False)
    wash_sale_safe_after: Mapped[date_type] = mapped_column(Date, nullable=False)  # sold_at + 31 days
    account_type: Mapped[str] = mapped_column(String, nullable=False)  # "taxable"|"ira"|"joint"
    loss_amount: Mapped[float] = mapped_column(Float, nullable=False)
