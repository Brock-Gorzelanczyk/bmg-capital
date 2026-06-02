from __future__ import annotations
import random, string
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from app.db.base import Base

def _gen_code() -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=8))

class ReferralCode(Base):
    __tablename__ = "referral_codes"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    code = Column(String, unique=True, nullable=False, default=_gen_code)
    total_referrals = Column(Integer, default=0)
    total_rewards_earned = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)

class ReferralReward(Base):
    __tablename__ = "referral_rewards"
    id = Column(Integer, primary_key=True, index=True)
    referrer_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    referred_email = Column(String, nullable=False)
    code_used = Column(String, nullable=False)
    status = Column(String, default="pending")  # pending | qualified | rewarded | expired
    reward_amount = Column(Float, nullable=True)
    reward_symbol = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)
