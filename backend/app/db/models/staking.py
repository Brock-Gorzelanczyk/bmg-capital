from __future__ import annotations
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from app.db.base import Base

class StakingPosition(Base):
    __tablename__ = "staking_positions"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    asset = Column(String, nullable=False)
    amount_staked = Column(Float, nullable=False)
    apy = Column(Float, nullable=False)
    rewards_earned = Column(Float, default=0.0)
    status = Column(String, default="active")  # active | unstaking | unstaked
    staked_at = Column(DateTime, default=datetime.utcnow)
    unstake_requested_at = Column(DateTime, nullable=True)
    estimated_unstake_at = Column(DateTime, nullable=True)

class StakingRewardLog(Base):
    __tablename__ = "staking_reward_logs"
    id = Column(Integer, primary_key=True, index=True)
    position_id = Column(Integer, ForeignKey("staking_positions.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    asset = Column(String, nullable=False)
    reward_amount = Column(Float, nullable=False)
    reward_usd = Column(Float, nullable=False)
    logged_at = Column(DateTime, default=datetime.utcnow)
