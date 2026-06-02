from __future__ import annotations

from datetime import datetime, date
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MarketChallenge(Base):
    __tablename__ = "market_challenges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    challenge_date: Mapped[date] = mapped_column(Date, nullable=False, unique=True, index=True)
    challenge_type: Mapped[str] = mapped_column(String, nullable=False)
    # "chart_pattern" | "predict_close" | "earnings_beat" | "10k_translation"
    # | "strategy_fit" | "risk_check" | "greek_check"
    category: Mapped[str] = mapped_column(String, nullable=False)
    # "Technical" | "Fundamental" | "Options" | "Risk" | "Macro"
    difficulty: Mapped[str] = mapped_column(String, nullable=False)
    # "beginner" | "intermediate" | "advanced"
    question: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[str] = mapped_column(Text, nullable=False)       # JSON list of strings (3-5 options)
    correct_idx: Mapped[int] = mapped_column(Integer, nullable=False) # 0-based index of correct answer
    explanation: Mapped[str] = mapped_column(Text, nullable=False)    # shown after attempt
    share_emoji: Mapped[str] = mapped_column(String, nullable=False)  # e.g. "🟩🟥🟩🟩"
    xp_value: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, server_default=func.now())


class MarketChallengeAttempt(Base):
    __tablename__ = "market_challenge_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    challenge_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    choice_idx: Mapped[int] = mapped_column(Integer, nullable=False)
    correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    time_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # how fast they answered
    attempted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, server_default=func.now())


class LeagueCohort(Base):
    __tablename__ = "league_cohorts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    week_iso: Mapped[str] = mapped_column(String, nullable=False, index=True)  # "2026-W22"
    tier: Mapped[str] = mapped_column(String, nullable=False)
    # "Bronze" | "Silver" | "Gold" | "Platinum" | "Diamond"
    user_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON list of user ids (30 max)
    finalized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, server_default=func.now())


class LeaguePoints(Base):
    __tablename__ = "league_points"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    week_iso: Mapped[str] = mapped_column(String, nullable=False, index=True)
    points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    breakdown: Mapped[str] = mapped_column(
        Text, nullable=False, default='{"lessons": 0, "challenges": 0, "journal": 0, "backtests": 0}'
    )
    last_updated: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
