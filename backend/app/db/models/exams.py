from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger, Boolean, DateTime, ForeignKey, Integer,
    JSON, Numeric, String, Text, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ExamQuestion(Base):
    __tablename__ = "exam_questions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    track_slug: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    module_slug: Mapped[Optional[str]] = mapped_column(String(50))
    question_type: Mapped[str] = mapped_column(String(20), nullable=False)  # 'mc','calc','chart','scenario'
    difficulty: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-5
    body: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[Optional[list]] = mapped_column(JSON)  # list of 4 strings for MC
    correct_answer: Mapped[str] = mapped_column(Text, nullable=False)
    numeric_tolerance: Mapped[Optional[Decimal]] = mapped_column(Numeric)
    chart_image_url: Mapped[Optional[str]] = mapped_column(Text)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    source_citation: Mapped[Optional[str]] = mapped_column(Text)
    tags: Mapped[Optional[list]] = mapped_column(JSON)  # list of tag strings
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, server_default=func.now())


class ExamAttempt(Base):
    __tablename__ = "exam_attempts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    exam_type: Mapped[str] = mapped_column(String(20), nullable=False)   # 'track','tier1','tier2','tier3'
    exam_target: Mapped[str] = mapped_column(String(50), nullable=False)  # track slug or 'tier1' etc
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # 'in_progress','submitted','passed','failed','disqualified'
    score_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric)
    questions_correct: Mapped[Optional[int]] = mapped_column(Integer)
    questions_total: Mapped[Optional[int]] = mapped_column(Integer)
    tab_switch_count: Mapped[int] = mapped_column(Integer, default=0)
    honor_code_accepted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    honor_code_name: Mapped[Optional[str]] = mapped_column(String(200))
    question_ids: Mapped[Optional[list]] = mapped_column(JSON)   # list of question IDs for this attempt
    question_order: Mapped[Optional[dict]] = mapped_column(JSON)  # shuffled option order per question
    time_remaining_seconds: Mapped[Optional[int]] = mapped_column(Integer)

    responses: Mapped[list[ExamResponse]] = relationship(
        "ExamResponse", back_populates="attempt", cascade="all, delete-orphan"
    )
    certificate: Mapped[Optional[Certificate]] = relationship(
        "Certificate", back_populates="attempt", uselist=False
    )


class ExamResponse(Base):
    __tablename__ = "exam_responses"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    attempt_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("exam_attempts.id"), nullable=False, index=True)
    question_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("exam_questions.id"), nullable=False)
    question_index: Mapped[int] = mapped_column(Integer, nullable=False)  # 0-based position in attempt
    user_answer: Mapped[Optional[str]] = mapped_column(Text)
    is_correct: Mapped[Optional[bool]] = mapped_column(Boolean)
    answered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, server_default=func.now())

    attempt: Mapped[ExamAttempt] = relationship("ExamAttempt", back_populates="responses")
    question: Mapped[ExamQuestion] = relationship("ExamQuestion")


class Certificate(Base):
    __tablename__ = "certificates"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)  # BMG-T1-IT-2026-0001
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    recipient_name: Mapped[str] = mapped_column(String(200), nullable=False)
    cert_type: Mapped[str] = mapped_column(String(20), nullable=False)    # 'track' or 'tier'
    cert_target: Mapped[str] = mapped_column(String(50), nullable=False)  # 'investment-tools' or 'tier1'
    display_title: Mapped[str] = mapped_column(String(200), nullable=False)
    exam_attempt_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("exam_attempts.id"))
    score_pct: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    issued_at: Mapped[Optional[datetime]] = mapped_column(DateTime, server_default=func.now())
    pdf_url: Mapped[str] = mapped_column(Text, nullable=False)
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    revoked_reason: Mapped[Optional[str]] = mapped_column(Text)
    verification_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    attempt: Mapped[Optional[ExamAttempt]] = relationship("ExamAttempt", back_populates="certificate")
