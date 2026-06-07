from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Integer, JSON,
    String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class LearningTrack(Base):
    __tablename__ = "learning_tracks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    order: Mapped[int] = mapped_column(Integer, default=0)
    cert_tier: Mapped[Optional[str]] = mapped_column(String)  # "1", "2", "3", "exam_prep"
    prereq_track_slugs: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    estimated_hours: Mapped[Optional[float]] = mapped_column(Float)

    modules: Mapped[list[LearningModule]] = relationship(
        "LearningModule", back_populates="track", order_by="LearningModule.order"
    )


class LearningModule(Base):
    __tablename__ = "learning_modules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    track_id: Mapped[int] = mapped_column(Integer, ForeignKey("learning_tracks.id"), nullable=False)
    slug: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    order: Mapped[int] = mapped_column(Integer, default=0)
    estimated_hours: Mapped[Optional[float]] = mapped_column(Float)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False)
    capstone_exercise: Mapped[Optional[str]] = mapped_column(Text)

    track: Mapped[LearningTrack] = relationship("LearningTrack", back_populates="modules")
    lessons: Mapped[list[LearningLesson]] = relationship(
        "LearningLesson", back_populates="module", order_by="LearningLesson.order"
    )


class LearningLesson(Base):
    __tablename__ = "learning_lessons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    module_id: Mapped[int] = mapped_column(Integer, ForeignKey("learning_modules.id"), nullable=False)
    slug: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    content_md: Mapped[Optional[str]] = mapped_column(Text)
    video_url: Mapped[Optional[str]] = mapped_column(String)
    exercise_md: Mapped[Optional[str]] = mapped_column(Text)
    quiz_json: Mapped[Optional[list]] = mapped_column(JSON)
    estimated_minutes: Mapped[Optional[int]] = mapped_column(Integer)
    order: Mapped[int] = mapped_column(Integer, default=0)

    module: Mapped[LearningModule] = relationship("LearningModule", back_populates="lessons")


class UserLessonProgress(Base):
    __tablename__ = "user_lesson_progress"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    lesson_id: Mapped[int] = mapped_column(Integer, ForeignKey("learning_lessons.id"), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    quiz_score: Mapped[Optional[int]] = mapped_column(Integer)
    time_spent_seconds: Mapped[Optional[int]] = mapped_column(Integer)

    __table_args__ = (UniqueConstraint("user_id", "lesson_id"),)


class UserCertificate(Base):
    __tablename__ = "user_certificates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    cert_tier: Mapped[str] = mapped_column(String, nullable=False)  # "1", "2", "3", "exam_prep"
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    verification_token: Mapped[Optional[str]] = mapped_column(String, unique=True)
    share_url: Mapped[Optional[str]] = mapped_column(String)
