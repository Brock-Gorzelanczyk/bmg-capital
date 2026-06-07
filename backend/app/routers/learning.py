"""
IMCP Learning Center API

GET  /api/learning/tracks                                           — all tracks with modules + user progress
GET  /api/learning/tracks/{track_slug}                             — single track with modules + lesson summaries
GET  /api/learning/tracks/{track_slug}/modules/{module_slug}       — single module with lesson summaries
GET  /api/learning/tracks/{track_slug}/modules/{module_slug}/lessons/{lesson_slug}  — full lesson content
POST /api/learning/lessons/{lesson_id}/complete                    — mark lesson complete
GET  /api/learning/progress                                        — user progress summary
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
from app.db.models.users import User
from app.db.models.learning import (
    LearningTrack,
    LearningModule,
    LearningLesson,
    UserLessonProgress,
    UserCertificate,
)

router = APIRouter(prefix="/api/learning", tags=["learning"])


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class LessonSummary(BaseModel):
    id: int
    slug: str
    title: str
    estimated_minutes: Optional[int]
    order: int
    completed: bool = False

    class Config:
        from_attributes = True


class ModuleSummary(BaseModel):
    id: int
    slug: str
    name: str
    description: Optional[str]
    order: int
    estimated_hours: Optional[float]
    is_published: bool
    lesson_count: int
    completed_count: int
    lessons: list[LessonSummary] = []

    class Config:
        from_attributes = True


class TrackResponse(BaseModel):
    id: int
    slug: str
    name: str
    description: Optional[str]
    order: int
    cert_tier: Optional[str]
    prereq_track_slugs: Optional[list]
    estimated_hours: Optional[float]
    modules: list[ModuleSummary]
    total_lessons: int
    completed_lessons: int

    class Config:
        from_attributes = True


class LessonDetail(BaseModel):
    id: int
    slug: str
    title: str
    content_md: Optional[str]
    video_url: Optional[str]
    exercise_md: Optional[str]
    quiz_json: Optional[list]
    estimated_minutes: Optional[int]
    order: int
    completed: bool = False
    quiz_score: Optional[int] = None
    module_slug: str
    track_slug: str
    prev_lesson: Optional[dict] = None
    next_lesson: Optional[dict] = None

    class Config:
        from_attributes = True


class CompleteBody(BaseModel):
    quiz_score: Optional[int] = None
    time_spent_seconds: Optional[int] = None


class ProgressResponse(BaseModel):
    completed_lesson_ids: list[int]
    completed_per_track: dict[str, int]  # track_slug -> completed count
    total_per_track: dict[str, int]      # track_slug -> total lessons
    cert_eligibility: dict[str, bool]    # cert_tier -> eligible?


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_completed_ids(user_id: int, db: Session) -> set[int]:
    rows = db.query(UserLessonProgress.lesson_id).filter(
        UserLessonProgress.user_id == user_id,
        UserLessonProgress.completed_at.isnot(None),
    ).all()
    return {r[0] for r in rows}


def _build_module_summary(
    module: LearningModule,
    completed_ids: set[int],
    include_lessons: bool = False,
) -> ModuleSummary:
    lesson_count = len(module.lessons)
    completed_count = sum(1 for l in module.lessons if l.id in completed_ids)
    lessons = []
    if include_lessons:
        lessons = [
            LessonSummary(
                id=l.id,
                slug=l.slug,
                title=l.title,
                estimated_minutes=l.estimated_minutes,
                order=l.order,
                completed=l.id in completed_ids,
            )
            for l in sorted(module.lessons, key=lambda x: x.order)
        ]
    return ModuleSummary(
        id=module.id,
        slug=module.slug,
        name=module.name,
        description=module.description,
        order=module.order,
        estimated_hours=module.estimated_hours,
        is_published=module.is_published,
        lesson_count=lesson_count,
        completed_count=completed_count,
        lessons=lessons,
    )


def _build_track_response(
    track: LearningTrack,
    completed_ids: set[int],
    include_lessons: bool = False,
) -> TrackResponse:
    modules = [
        _build_module_summary(m, completed_ids, include_lessons)
        for m in sorted(track.modules, key=lambda x: x.order)
    ]
    total_lessons = sum(m.lesson_count for m in modules)
    completed_lessons = sum(m.completed_count for m in modules)
    return TrackResponse(
        id=track.id,
        slug=track.slug,
        name=track.name,
        description=track.description,
        order=track.order,
        cert_tier=track.cert_tier,
        prereq_track_slugs=track.prereq_track_slugs or [],
        estimated_hours=track.estimated_hours,
        modules=modules,
        total_lessons=total_lessons,
        completed_lessons=completed_lessons,
    )


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/tracks", response_model=list[TrackResponse])
def list_tracks(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List all tracks with module summaries and per-user progress."""
    tracks = db.query(LearningTrack).order_by(LearningTrack.order).all()
    completed_ids = _get_completed_ids(user.id, db)
    return [_build_track_response(t, completed_ids, include_lessons=False) for t in tracks]


@router.get("/tracks/{track_slug}", response_model=TrackResponse)
def get_track(
    track_slug: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Single track with all modules and lesson summaries (no lesson content)."""
    track = db.query(LearningTrack).filter(LearningTrack.slug == track_slug).first()
    if not track:
        raise HTTPException(status_code=404, detail="Track not found")
    completed_ids = _get_completed_ids(user.id, db)
    return _build_track_response(track, completed_ids, include_lessons=True)


@router.get("/tracks/{track_slug}/modules/{module_slug}")
def get_module(
    track_slug: str,
    module_slug: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Single module with all lesson summaries (no lesson content body)."""
    track = db.query(LearningTrack).filter(LearningTrack.slug == track_slug).first()
    if not track:
        raise HTTPException(status_code=404, detail="Track not found")

    module = (
        db.query(LearningModule)
        .filter(LearningModule.track_id == track.id, LearningModule.slug == module_slug)
        .first()
    )
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")

    completed_ids = _get_completed_ids(user.id, db)
    return _build_module_summary(module, completed_ids, include_lessons=True)


@router.get("/tracks/{track_slug}/modules/{module_slug}/lessons/{lesson_slug}", response_model=LessonDetail)
def get_lesson(
    track_slug: str,
    module_slug: str,
    lesson_slug: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Full lesson content."""
    track = db.query(LearningTrack).filter(LearningTrack.slug == track_slug).first()
    if not track:
        raise HTTPException(status_code=404, detail="Track not found")

    module = (
        db.query(LearningModule)
        .filter(LearningModule.track_id == track.id, LearningModule.slug == module_slug)
        .first()
    )
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")

    lesson = (
        db.query(LearningLesson)
        .filter(LearningLesson.module_id == module.id, LearningLesson.slug == lesson_slug)
        .first()
    )
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")

    # Check progress
    progress_row = (
        db.query(UserLessonProgress)
        .filter(
            UserLessonProgress.user_id == user.id,
            UserLessonProgress.lesson_id == lesson.id,
        )
        .first()
    )

    # Build prev/next navigation within the module
    ordered = sorted(module.lessons, key=lambda x: x.order)
    idx = next((i for i, l in enumerate(ordered) if l.id == lesson.id), None)
    prev_lesson = None
    next_lesson = None
    if idx is not None:
        if idx > 0:
            p = ordered[idx - 1]
            prev_lesson = {"id": p.id, "slug": p.slug, "title": p.title}
        if idx < len(ordered) - 1:
            n = ordered[idx + 1]
            next_lesson = {"id": n.id, "slug": n.slug, "title": n.title}

    return LessonDetail(
        id=lesson.id,
        slug=lesson.slug,
        title=lesson.title,
        content_md=lesson.content_md,
        video_url=lesson.video_url,
        exercise_md=lesson.exercise_md,
        quiz_json=lesson.quiz_json,
        estimated_minutes=lesson.estimated_minutes,
        order=lesson.order,
        completed=progress_row is not None and progress_row.completed_at is not None,
        quiz_score=progress_row.quiz_score if progress_row else None,
        module_slug=module.slug,
        track_slug=track.slug,
        prev_lesson=prev_lesson,
        next_lesson=next_lesson,
    )


@router.post("/lessons/{lesson_id}/complete")
def complete_lesson(
    lesson_id: int,
    body: CompleteBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Mark a lesson complete and optionally record quiz score and time spent."""
    lesson = db.get(LearningLesson, lesson_id)
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")

    row = (
        db.query(UserLessonProgress)
        .filter(
            UserLessonProgress.user_id == user.id,
            UserLessonProgress.lesson_id == lesson_id,
        )
        .first()
    )
    if row is None:
        row = UserLessonProgress(user_id=user.id, lesson_id=lesson_id)
        db.add(row)

    row.completed_at = datetime.now(timezone.utc)
    if body.quiz_score is not None:
        row.quiz_score = body.quiz_score
    if body.time_spent_seconds is not None:
        row.time_spent_seconds = body.time_spent_seconds

    db.commit()
    db.refresh(row)
    return {"ok": True, "completed_at": row.completed_at.isoformat()}


@router.get("/progress", response_model=ProgressResponse)
def get_progress(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Summary of user progress: completed lessons per track, cert eligibility."""
    completed_ids = _get_completed_ids(user.id, db)
    tracks = db.query(LearningTrack).order_by(LearningTrack.order).all()

    completed_per_track: dict[str, int] = {}
    total_per_track: dict[str, int] = {}

    for track in tracks:
        all_lesson_ids = [
            l.id
            for m in track.modules
            for l in m.lessons
        ]
        total_per_track[track.slug] = len(all_lesson_ids)
        completed_per_track[track.slug] = sum(1 for lid in all_lesson_ids if lid in completed_ids)

    # Cert eligibility: all lessons in all tracks for that tier must be completed
    def _tier_complete(tier: str) -> bool:
        tier_tracks = [t for t in tracks if t.cert_tier == tier]
        if not tier_tracks:
            return False
        for t in tier_tracks:
            if completed_per_track.get(t.slug, 0) < total_per_track.get(t.slug, 1):
                return False
        return True

    cert_eligibility = {
        "1": _tier_complete("1"),
        "2": _tier_complete("2"),
        "3": _tier_complete("3"),
        "exam_prep": _tier_complete("exam_prep"),
    }

    return ProgressResponse(
        completed_lesson_ids=list(completed_ids),
        completed_per_track=completed_per_track,
        total_per_track=total_per_track,
        cert_eligibility=cert_eligibility,
    )
