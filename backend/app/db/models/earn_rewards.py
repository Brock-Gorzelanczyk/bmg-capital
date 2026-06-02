from __future__ import annotations
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, JSON, ForeignKey
from app.db.base import Base

class LearnEarnLesson(Base):
    __tablename__ = "learn_earn_lessons"
    id = Column(Integer, primary_key=True, index=True)
    lesson_id = Column(String, unique=True, nullable=False)
    title = Column(String, nullable=False)
    description = Column(String, default="")
    sponsor = Column(String, nullable=True)
    reward_amount = Column(Float, default=5.0)
    reward_symbol = Column(String, default="SPY")
    quiz_questions = Column(JSON, default=list)
    is_active = Column(Boolean, default=True)
    total_completions = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

class EarnReward(Base):
    __tablename__ = "earn_rewards"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    lesson_id = Column(String, nullable=False)
    quiz_score = Column(Integer, default=0)
    reward_amount = Column(Float, nullable=True)
    reward_symbol = Column(String, nullable=True)
    status = Column(String, default="pending")  # pending | credited | expired
    earned_at = Column(DateTime, default=datetime.utcnow)
    credited_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
