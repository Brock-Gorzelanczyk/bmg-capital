from __future__ import annotations

import json
from datetime import datetime, date
from typing import Optional

from sqlalchemy import DateTime, Date, Float, Integer, String, Boolean, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserProgress(Base):
    __tablename__ = "learn_progress"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True, unique=True)
    xp: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    streak: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    longest_streak: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    streak_freezes: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    last_activity_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    selected_track: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    onboarding_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # JSON-encoded list of lesson IDs
    completed_lesson_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # JSON-encoded list of badge IDs
    badges: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # JSON-encoded dict of lessonId -> best score 0-1
    quiz_best: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def completed_ids(self) -> list[str]:
        return json.loads(self.completed_lesson_ids)

    def badge_ids(self) -> list[str]:
        return json.loads(self.badges)

    def quiz_scores(self) -> dict[str, float]:
        return json.loads(self.quiz_best)


class LessonCompletion(Base):
    __tablename__ = "learn_completions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    lesson_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    xp_earned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, server_default=func.now())


class QuizAttempt(Base):
    __tablename__ = "learn_quiz_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    lesson_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    score: Mapped[float] = mapped_column(Float, nullable=False)  # 0.0 - 1.0
    attempted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, server_default=func.now())


class UserBadge(Base):
    __tablename__ = "learn_badges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    badge_id: Mapped[str] = mapped_column(String, nullable=False)
    earned_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, server_default=func.now())


class DailyChallenge(Base):
    __tablename__ = "learn_daily_challenges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    challenge_date: Mapped[date] = mapped_column(Date, nullable=False)
    lesson_id: Mapped[str] = mapped_column(String, nullable=False)
    completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
