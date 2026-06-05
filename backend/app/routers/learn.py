from __future__ import annotations

import json
import hashlib
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
from app.db.models.learn import UserProgress, LessonCompletion, QuizAttempt, UserBadge, DailyChallenge
from app.db.models.users import User

router = APIRouter(prefix="/api/learn", tags=["learn"])

LEVEL_THRESHOLDS = [0, 150, 400, 800, 1500, 2500, 4000, 6000, 9000, 13000, 20000]

# Rotating set of lesson IDs for daily challenge (by day-of-year hash)
DAILY_POOL = [
    "if-stocks-101-l1", "if-stocks-101-l2", "if-stocks-101-l3",
    "if-charts-l1", "if-charts-l2", "if-charts-l3",
    "if-first-trade-l1", "if-first-trade-l2",
    "ta-trend-l1", "ta-trend-l2", "ta-trend-l3",
    "ta-momentum-l1", "ta-momentum-l2", "ta-momentum-l3",
    "ta-patterns-l1", "ta-patterns-l2",
    "fa-financials-l1", "fa-financials-l2", "fa-financials-l3",
    "fa-valuation-l1", "fa-valuation-l2",
]


def _xp_to_level(xp: int) -> int:
    for i in range(len(LEVEL_THRESHOLDS) - 1, -1, -1):
        if xp >= LEVEL_THRESHOLDS[i]:
            return i + 1
    return 1


def _get_or_create_progress(user_id: int, db: Session) -> UserProgress:
    p = db.query(UserProgress).filter(UserProgress.user_id == user_id).first()
    if not p:
        p = UserProgress(user_id=user_id)
        db.add(p)
        db.commit()
        db.refresh(p)
    return p


def _award_badge(badge_id: str, progress: UserProgress, db: Session) -> bool:
    existing = db.query(UserBadge).filter(
        UserBadge.user_id == progress.user_id,
        UserBadge.badge_id == badge_id,
    ).first()
    if existing:
        return False
    db.add(UserBadge(user_id=progress.user_id, badge_id=badge_id))
    badges = progress.badge_ids()
    if badge_id not in badges:
        badges.append(badge_id)
        progress.badges = json.dumps(badges)
    return True


def _check_badges(progress: UserProgress, db: Session) -> list[str]:
    earned = []
    completed = progress.completed_ids()

    if len(completed) >= 1:
        if _award_badge("first_lesson", progress, db):
            earned.append("first_lesson")

    if progress.streak >= 3:
        if _award_badge("streak_3", progress, db):
            earned.append("streak_3")
    if progress.streak >= 7:
        if _award_badge("streak_7", progress, db):
            earned.append("streak_7")
    if progress.streak >= 30:
        if _award_badge("streak_30", progress, db):
            earned.append("streak_30")

    if progress.level >= 5:
        if _award_badge("level_5", progress, db):
            earned.append("level_5")
    if progress.level >= 10:
        if _award_badge("level_10", progress, db):
            earned.append("level_10")

    return earned


def _progress_to_dict(p: UserProgress) -> dict:
    return {
        "xp": p.xp,
        "level": p.level,
        "streak": p.streak,
        "longestStreak": p.longest_streak,
        "streakFreezes": p.streak_freezes,
        "lastActivityDate": p.last_activity_date.isoformat() if p.last_activity_date else None,
        "selectedTrack": p.selected_track,
        "onboardingComplete": p.onboarding_complete,
        "completedLessonIds": p.completed_ids(),
        "badges": p.badge_ids(),
        "quizBest": p.quiz_scores(),
    }


@router.get("/progress")
def get_progress(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    p = _get_or_create_progress(current_user.id, db)
    return _progress_to_dict(p)


class CompleteLessonBody(BaseModel):
    xp_earned: int = 50


@router.post("/complete/{lesson_id}")
def complete_lesson(
    lesson_id: str,
    body: CompleteLessonBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    p = _get_or_create_progress(current_user.id, db)

    # Idempotent — already completed
    completed = p.completed_ids()
    if lesson_id in completed:
        return {"alreadyCompleted": True, "progress": _progress_to_dict(p), "newBadges": []}

    # Record completion
    db.add(LessonCompletion(user_id=current_user.id, lesson_id=lesson_id, xp_earned=body.xp_earned))

    # Update completed list
    completed.append(lesson_id)
    p.completed_lesson_ids = json.dumps(completed)

    # Award XP
    p.xp += body.xp_earned

    # Update level
    p.level = _xp_to_level(p.xp)

    # Update streak with 25-hour grace window to handle timezone edge cases
    now_utc = datetime.now(timezone.utc)
    today = now_utc.date()
    if p.last_activity_date is None:
        p.streak = 1
    elif p.last_activity_date == today:
        pass  # same day, no change
    else:
        days_since = (today - p.last_activity_date).days
        hours_since = days_since * 24
        if days_since == 1 or hours_since <= 25:
            # consecutive day or within 25-hour grace window
            p.streak += 1
        elif days_since == 2 and p.streak_freezes > 0:
            p.streak_freezes -= 1  # burn a freeze
        else:
            p.streak = 1

    if p.streak > p.longest_streak:
        p.longest_streak = p.streak

    p.last_activity_date = today

    # Check daily challenge completion
    dc = db.query(DailyChallenge).filter(
        DailyChallenge.user_id == current_user.id,
        DailyChallenge.challenge_date == today,
        DailyChallenge.lesson_id == lesson_id,
    ).first()
    new_badges = []
    if dc and not dc.completed:
        dc.completed = True
        dc.completed_at = datetime.now(timezone.utc)
        if _award_badge("daily_challenge", p, db):
            new_badges.append("daily_challenge")

    # Check lesson-triggered badges
    new_badges.extend(_check_badges(p, db))

    db.commit()
    db.refresh(p)
    return {"alreadyCompleted": False, "progress": _progress_to_dict(p), "newBadges": new_badges}


class QuizBody(BaseModel):
    score: float  # 0.0 - 1.0


@router.post("/quiz/{lesson_id}")
def submit_quiz(
    lesson_id: str,
    body: QuizBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not 0.0 <= body.score <= 1.0:
        raise HTTPException(status_code=422, detail="Score must be between 0 and 1")

    db.add(QuizAttempt(user_id=current_user.id, lesson_id=lesson_id, score=body.score))

    p = _get_or_create_progress(current_user.id, db)
    scores = p.quiz_scores()
    if body.score > scores.get(lesson_id, 0.0):
        scores[lesson_id] = body.score
        p.quiz_best = json.dumps(scores)

    new_badges = []
    if body.score == 1.0:
        if _award_badge("first_quiz_100", p, db):
            new_badges.append("first_quiz_100")

    db.commit()
    db.refresh(p)
    return {"quizBest": p.quiz_scores(), "newBadges": new_badges}


@router.get("/badges")
def get_badges(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    badges = db.query(UserBadge).filter(UserBadge.user_id == current_user.id).all()
    return [{"badgeId": b.badge_id, "earnedAt": b.earned_at.isoformat()} for b in badges]


class OnboardingBody(BaseModel):
    track_id: str


@router.post("/onboarding")
def complete_onboarding(
    body: OnboardingBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    p = _get_or_create_progress(current_user.id, db)
    p.selected_track = body.track_id
    p.onboarding_complete = True
    db.commit()
    db.refresh(p)
    return _progress_to_dict(p)


@router.get("/leaderboard")
def get_leaderboard(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    rows = (
        db.query(UserProgress, User)
        .join(User, User.id == UserProgress.user_id)
        .order_by(UserProgress.xp.desc())
        .limit(20)
        .all()
    )
    return [
        {
            "userId": u.id,
            "username": u.username,
            "xp": p.xp,
            "streak": p.streak,
            "rank": i + 1,
        }
        for i, (p, u) in enumerate(rows)
    ]


def _daily_lesson_for_date(d: date) -> str:
    idx = int(hashlib.md5(d.isoformat().encode()).hexdigest(), 16) % len(DAILY_POOL)
    return DAILY_POOL[idx]


@router.get("/daily")
def get_daily_challenge(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    today = date.today()
    lesson_id = _daily_lesson_for_date(today)

    dc = db.query(DailyChallenge).filter(
        DailyChallenge.user_id == current_user.id,
        DailyChallenge.challenge_date == today,
    ).first()
    if not dc:
        dc = DailyChallenge(
            user_id=current_user.id,
            challenge_date=today,
            lesson_id=lesson_id,
        )
        db.add(dc)
        db.commit()
        db.refresh(dc)

    return {
        "lessonId": dc.lesson_id,
        "date": today.isoformat(),
        "completed": dc.completed,
    }


@router.post("/freeze")
def use_freeze(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    p = _get_or_create_progress(current_user.id, db)
    if p.streak_freezes <= 0:
        raise HTTPException(status_code=400, detail="No streak freezes remaining")
    p.streak_freezes -= 1
    db.commit()
    db.refresh(p)
    return {"streakFreezes": p.streak_freezes}
