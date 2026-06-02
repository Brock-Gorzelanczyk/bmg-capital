from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class PlaybookPhase(Base):
    __tablename__ = "playbook_phases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    phase_number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    day_start: Mapped[int] = mapped_column(Integer, nullable=False)
    day_end: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome_target: Mapped[str] = mapped_column(Text, nullable=False)

    weeks: Mapped[list["PlaybookWeek"]] = relationship(
        "PlaybookWeek", back_populates="phase", cascade="all, delete-orphan", order_by="PlaybookWeek.week_number"
    )


class PlaybookWeek(Base):
    __tablename__ = "playbook_weeks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    phase_id: Mapped[int] = mapped_column(Integer, ForeignKey("playbook_phases.id"), nullable=False)
    week_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    day_start: Mapped[int] = mapped_column(Integer, nullable=False)
    day_end: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome_target: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")

    phase: Mapped["PlaybookPhase"] = relationship("PlaybookPhase", back_populates="weeks")
    tasks: Mapped[list["PlaybookTask"]] = relationship(
        "PlaybookTask", back_populates="week", cascade="all, delete-orphan", order_by="PlaybookTask.sort_order"
    )


class PlaybookTask(Base):
    __tablename__ = "playbook_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    week_id: Mapped[int] = mapped_column(Integer, ForeignKey("playbook_weeks.id"), nullable=False)
    day_focus: Mapped[str] = mapped_column(String, nullable=False, default="")
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    effort_hours: Mapped[float] = mapped_column(Float, nullable=False, default=4.0)
    priority: Mapped[str] = mapped_column(String, nullable=False, default="P1")
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    completion_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    week: Mapped["PlaybookWeek"] = relationship("PlaybookWeek", back_populates="tasks")


class PlaybookStart(Base):
    __tablename__ = "playbook_start"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
