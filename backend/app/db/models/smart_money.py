from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import BigInteger, Column, Date, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.sql import func

from app.db.base import Base


class SmartMoneyCongressTrade(Base):
    __tablename__ = "smart_money_congress"

    # Integer (not BigInteger) required for SQLite rowid alias → auto-increment
    id = Column(Integer, primary_key=True, autoincrement=True)
    member_name = Column(String(200), nullable=False)
    party = Column(String(1))
    chamber = Column(String(1))           # 'S' or 'H'
    state = Column(String(2))
    ticker = Column(String(20))
    asset_description = Column(Text)
    transaction_type = Column(String(20))  # 'purchase', 'sale', 'exchange'
    amount_range = Column(String(50))
    amount_lower_cents = Column(BigInteger)
    amount_upper_cents = Column(BigInteger)
    transaction_date = Column(Date, nullable=False)
    disclosure_date = Column(Date)
    source = Column(String(50))            # 'senate_stock_watcher' or 'house_stock_watcher'
    source_id = Column(String(200))
    fetched_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("source", "source_id", name="uq_smc_source_id"),
        Index("idx_smc_ticker", "ticker", "transaction_date"),
        Index("idx_smc_date", "transaction_date"),
    )
