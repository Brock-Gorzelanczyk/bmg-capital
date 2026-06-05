"""
BMG Capital — Engagement Router
Prefix: /api/engagement
Covers: daily market challenges, streaks, achievements, leagues, weekly/annual recap.
"""
from __future__ import annotations

import json
import hashlib
from datetime import timezone, datetime, date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.dependencies import get_db, get_current_user
from app.db.models.users import User
from app.db.models.learn import UserProgress, UserBadge, LessonCompletion
from app.db.models.journal import JournalEntry
from app.db.models.paper import PaperPosition, PaperTransaction
from app.db.models.watchlist import WatchlistItem
from app.db.models.engagement import (
    MarketChallenge,
    MarketChallengeAttempt,
    LeagueCohort,
    LeaguePoints,
)
from app.services.challenge_library import CHALLENGE_LIBRARY

router = APIRouter(prefix="/api/engagement", tags=["engagement"])


# ── Helpers ──────────────────────────────────────────────────────────────────

def _current_week_iso() -> str:
    """Return ISO week string like '2026-W22'."""
    today = date.today()
    year, week, _ = today.isocalendar()
    return f"{year}-W{week:02d}"


def _get_or_create_progress(db: Session, user_id: int) -> UserProgress:
    progress = db.query(UserProgress).filter_by(user_id=user_id).first()
    if not progress:
        progress = UserProgress(user_id=user_id)
        db.add(progress)
        db.commit()
        db.refresh(progress)
    return progress


def _award_badge(db: Session, user_id: int, badge_id: str) -> bool:
    """Award a badge if not already held. Returns True if newly awarded."""
    existing = db.query(UserBadge).filter_by(user_id=user_id, badge_id=badge_id).first()
    if existing:
        return False
    db.add(UserBadge(user_id=user_id, badge_id=badge_id))
    db.commit()
    return True


def _add_league_points(
    db: Session, user_id: int, week_iso: str, amount: int, category: str
) -> int:
    """Add points to the user's league_points row for this week. Returns new total."""
    lp = db.query(LeaguePoints).filter_by(user_id=user_id, week_iso=week_iso).first()
    if not lp:
        lp = LeaguePoints(
            user_id=user_id,
            week_iso=week_iso,
            points=0,
            breakdown=json.dumps({"lessons": 0, "challenges": 0, "journal": 0, "backtests": 0}),
            last_updated=datetime.now(timezone.utc),
        )
        db.add(lp)
        db.flush()

    lp.points += amount
    breakdown = json.loads(lp.breakdown or "{}")
    breakdown[category] = breakdown.get(category, 0) + amount
    lp.breakdown = json.dumps(breakdown)
    lp.last_updated = datetime.now(timezone.utc)
    db.commit()
    return lp.points


def _select_challenge_for_date(target_date: date) -> dict:
    """Deterministically pick a challenge from the library for a given date."""
    day_of_year = target_date.timetuple().tm_yday
    idx = day_of_year % len(CHALLENGE_LIBRARY)
    return CHALLENGE_LIBRARY[idx]


# ── ACHIEVEMENTS CATALOGUE ───────────────────────────────────────────────────
# 50 achievements with id, name, description, category, icon_emoji, max_progress
_ACHIEVEMENT_CATALOGUE: list[dict] = [
    # ONBOARDING (1-7)
    {"id": "onboarding_complete",       "name": "Welcome Aboard",         "description": "Complete onboarding",                                           "category": "Onboarding",  "icon_emoji": "🎉", "max_progress": 1},
    {"id": "first_lesson",              "name": "First Step",             "description": "Complete your first lesson",                                     "category": "Onboarding",  "icon_emoji": "📚", "max_progress": 1},
    {"id": "first_quiz",                "name": "Quiz Starter",           "description": "Take your first quiz",                                           "category": "Onboarding",  "icon_emoji": "❓", "max_progress": 1},
    {"id": "first_watchlist",           "name": "Market Watcher",         "description": "Add your first ticker to a watchlist",                           "category": "Onboarding",  "icon_emoji": "👁️", "max_progress": 1},
    {"id": "first_paper_trade",         "name": "Paper Trader",           "description": "Place your first paper trade",                                   "category": "Onboarding",  "icon_emoji": "📝", "max_progress": 1},
    {"id": "profile_complete",          "name": "Fully Loaded",           "description": "Complete your profile",                                          "category": "Onboarding",  "icon_emoji": "✅", "max_progress": 1},
    {"id": "first_challenge",           "name": "Challenge Accepted",     "description": "Attempt your first market challenge",                            "category": "Onboarding",  "icon_emoji": "🎯", "max_progress": 1},

    # SKILL / LEARNING (8-20)
    {"id": "lessons_5",                 "name": "Quick Learner",          "description": "Complete 5 lessons",                                             "category": "Learning",    "icon_emoji": "⚡", "max_progress": 5},
    {"id": "lessons_25",                "name": "Knowledge Builder",      "description": "Complete 25 lessons",                                            "category": "Learning",    "icon_emoji": "🧠", "max_progress": 25},
    {"id": "lessons_50",                "name": "Dedicated Student",      "description": "Complete 50 lessons",                                            "category": "Learning",    "icon_emoji": "🎓", "max_progress": 50},
    {"id": "lessons_100",               "name": "Scholar",                "description": "Complete 100 lessons",                                           "category": "Learning",    "icon_emoji": "🏛️", "max_progress": 100},
    {"id": "perfect_quiz",              "name": "Perfect Score",          "description": "Score 100% on a quiz",                                           "category": "Learning",    "icon_emoji": "💯", "max_progress": 1},
    {"id": "challenge_correct_10",      "name": "Sharp Mind",             "description": "Answer 10 challenges correctly",                                 "category": "Learning",    "icon_emoji": "🎯", "max_progress": 10},
    {"id": "challenge_streak_7",        "name": "Challenge Streak 7",     "description": "Answer 7 market challenges correctly in a row",                  "category": "Learning",    "icon_emoji": "🔥", "max_progress": 7},
    {"id": "challenge_perfect_10",      "name": "Challenge Master",       "description": "Answer 10 market challenges correctly total",                    "category": "Learning",    "icon_emoji": "🏆", "max_progress": 10},
    {"id": "all_categories",            "name": "Well Rounded",           "description": "Complete a challenge in every category",                         "category": "Learning",    "icon_emoji": "🌐", "max_progress": 5},
    {"id": "level_5",                   "name": "Level 5 Trader",         "description": "Reach level 5",                                                  "category": "Learning",    "icon_emoji": "5️⃣", "max_progress": 1},
    {"id": "level_10",                  "name": "Level 10 Trader",        "description": "Reach level 10",                                                 "category": "Learning",    "icon_emoji": "🔟", "max_progress": 1},
    {"id": "xp_1000",                   "name": "XP Milestone",           "description": "Earn 1,000 total XP",                                           "category": "Learning",    "icon_emoji": "⭐", "max_progress": 1000},

    # BEHAVIORAL (21-32)
    {"id": "streak_7",                  "name": "One Week Streak",        "description": "Maintain a 7-day streak",                                        "category": "Behavioral",  "icon_emoji": "🗓️", "max_progress": 7},
    {"id": "streak_30",                 "name": "Monthly Momentum",       "description": "Maintain a 30-day streak",                                       "category": "Behavioral",  "icon_emoji": "📅", "max_progress": 30},
    {"id": "streak_100",                "name": "Century Streak",         "description": "Maintain a 100-day streak",                                      "category": "Behavioral",  "icon_emoji": "💎", "max_progress": 100},
    {"id": "journal_1",                 "name": "First Journal",          "description": "Write your first trade journal entry",                           "category": "Behavioral",  "icon_emoji": "📓", "max_progress": 1},
    {"id": "journal_10",                "name": "Journal Habit",          "description": "Write 10 trade journal entries",                                 "category": "Behavioral",  "icon_emoji": "📔", "max_progress": 10},
    {"id": "journal_30",                "name": "Journal Keeper",         "description": "Write 30 trade journal entries",                                 "category": "Behavioral",  "icon_emoji": "📒", "max_progress": 30},
    {"id": "daily_active_20",           "name": "Monthly Regular",        "description": "Be active on 20 separate days in a month",                       "category": "Behavioral",  "icon_emoji": "🗓️", "max_progress": 20},
    {"id": "morning_trader",            "name": "Early Bird",             "description": "Log in before 9:30am ET on 5 different trading days",            "category": "Behavioral",  "icon_emoji": "🌅", "max_progress": 5},
    {"id": "no_freeze_month",           "name": "Unbroken",               "description": "Complete a full month without using a streak freeze",            "category": "Behavioral",  "icon_emoji": "🧊", "max_progress": 1},
    {"id": "comeback",                  "name": "The Comeback",           "description": "Resume activity after a 7+ day absence",                        "category": "Behavioral",  "icon_emoji": "🔄", "max_progress": 1},
    {"id": "weekend_warrior",           "name": "Weekend Warrior",        "description": "Study on 5 different Saturdays or Sundays",                      "category": "Behavioral",  "icon_emoji": "⚔️", "max_progress": 5},
    {"id": "night_owl",                 "name": "Night Owl",              "description": "Log activity after 10pm on 5 different days",                    "category": "Behavioral",  "icon_emoji": "🦉", "max_progress": 5},

    # STRATEGY / LAB (33-42)
    {"id": "first_backtest",            "name": "Time Machine",           "description": "Run your first backtest",                                        "category": "Strategy",    "icon_emoji": "⏱️", "max_progress": 1},
    {"id": "backtests_10",              "name": "Strategy Lab",           "description": "Run 10 backtests",                                               "category": "Strategy",    "icon_emoji": "🔬", "max_progress": 10},
    {"id": "paper_trades_10",           "name": "Market Simulator",       "description": "Execute 10 paper trades",                                        "category": "Strategy",    "icon_emoji": "💹", "max_progress": 10},
    {"id": "paper_trades_50",           "name": "Simulated Pro",          "description": "Execute 50 paper trades",                                        "category": "Strategy",    "icon_emoji": "📊", "max_progress": 50},
    {"id": "profitable_week",           "name": "Green Week",             "description": "Achieve a profitable week in paper trading",                     "category": "Strategy",    "icon_emoji": "💚", "max_progress": 1},
    {"id": "win_rate_60",               "name": "Precision Trader",       "description": "Maintain 60%+ win rate over 20+ paper trades",                  "category": "Strategy",    "icon_emoji": "🎯", "max_progress": 1},
    {"id": "risk_reward_3",             "name": "Risk Manager",           "description": "Close 5 trades with 3:1+ risk/reward",                          "category": "Strategy",    "icon_emoji": "⚖️", "max_progress": 5},
    {"id": "watchlist_20",              "name": "Market Scanner",         "description": "Have 20+ tickers across all watchlists",                         "category": "Strategy",    "icon_emoji": "🔍", "max_progress": 20},
    {"id": "multi_sector",              "name": "Sector Diversified",     "description": "Hold paper positions in 3 different sectors simultaneously",     "category": "Strategy",    "icon_emoji": "🌍", "max_progress": 3},
    {"id": "options_user",              "name": "Options Explorer",       "description": "Complete 5 options-category challenges",                         "category": "Strategy",    "icon_emoji": "⚗️", "max_progress": 5},

    # COMMUNITY (43-47)
    {"id": "first_post",                "name": "First Post",             "description": "Publish your first social post",                                 "category": "Community",   "icon_emoji": "📢", "max_progress": 1},
    {"id": "first_like",                "name": "Appreciator",            "description": "Like someone else's post",                                       "category": "Community",   "icon_emoji": "❤️", "max_progress": 1},
    {"id": "posts_10",                  "name": "Active Voice",           "description": "Publish 10 social posts",                                        "category": "Community",   "icon_emoji": "📣", "max_progress": 10},
    {"id": "league_top_10",             "name": "Leaderboard Climber",    "description": "Finish in the top 10 of your league cohort",                     "category": "Community",   "icon_emoji": "🏅", "max_progress": 1},
    {"id": "league_promotion",          "name": "Promoted",               "description": "Get promoted to a higher league tier",                           "category": "Community",   "icon_emoji": "⬆️", "max_progress": 1},

    # VANITY (48-50)
    {"id": "platinum_tier",             "name": "Platinum Member",        "description": "Reach Platinum league tier",                                     "category": "Vanity",      "icon_emoji": "🔮", "max_progress": 1},
    {"id": "diamond_tier",              "name": "Diamond Elite",          "description": "Reach Diamond league tier",                                      "category": "Vanity",      "icon_emoji": "💎", "max_progress": 1},
    {"id": "completionist",             "name": "Completionist",          "description": "Unlock 40 out of 50 achievements",                               "category": "Vanity",      "icon_emoji": "🌟", "max_progress": 40},
]


# ── Challenge endpoints ───────────────────────────────────────────────────────

@router.get("/challenge/today")
def get_today_challenge(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    today = date.today()

    # Deterministically select puzzle from library
    puzzle = _select_challenge_for_date(today)

    # Get or create MarketChallenge row for today
    challenge = db.query(MarketChallenge).filter_by(challenge_date=today).first()
    if not challenge:
        challenge = MarketChallenge(
            challenge_date=today,
            challenge_type=puzzle["challenge_type"],
            category=puzzle["category"],
            difficulty=puzzle["difficulty"],
            question=puzzle["question"],
            options=json.dumps(puzzle["options"]),
            correct_idx=puzzle["correct_idx"],
            explanation=puzzle["explanation"],
            share_emoji=puzzle["share_emoji"],
            xp_value=puzzle["xp_value"],
        )
        db.add(challenge)
        db.commit()
        db.refresh(challenge)

    # Check if user already attempted
    attempt = db.query(MarketChallengeAttempt).filter_by(
        user_id=current_user.id, challenge_id=challenge.id
    ).first()

    result = None
    if attempt:
        result = {
            "choice_idx": attempt.choice_idx,
            "correct": attempt.correct,
            "explanation": challenge.explanation,
            "share_emoji": challenge.share_emoji,
        }

    return {
        "challenge_id": challenge.id,
        "challenge_type": challenge.challenge_type,
        "question": challenge.question,
        "options": json.loads(challenge.options),
        "category": challenge.category,
        "difficulty": challenge.difficulty,
        "xp_value": challenge.xp_value,
        "already_answered": attempt is not None,
        "result": result,
    }


class AttemptBody(BaseModel):
    challenge_id: int
    choice_idx: int
    time_ms: Optional[int] = None


@router.post("/challenge/attempt")
def submit_challenge_attempt(
    body: AttemptBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    challenge = db.get(MarketChallenge, body.challenge_id)
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")

    # Enforce one attempt per user per challenge
    existing = db.query(MarketChallengeAttempt).filter_by(
        user_id=current_user.id, challenge_id=body.challenge_id
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Already attempted this challenge today")

    correct = body.choice_idx == challenge.correct_idx

    attempt = MarketChallengeAttempt(
        user_id=current_user.id,
        challenge_id=body.challenge_id,
        choice_idx=body.choice_idx,
        correct=correct,
        time_ms=body.time_ms,
        attempted_at=datetime.now(timezone.utc),
    )
    db.add(attempt)
    db.commit()

    # Update UserProgress
    progress = _get_or_create_progress(db, current_user.id)

    xp_earned = 0
    if correct:
        xp_earned = challenge.xp_value
        progress.xp = (progress.xp or 0) + xp_earned
        progress.market_challenges_correct = (getattr(progress, "market_challenges_correct", 0) or 0) + 1
        progress.market_challenge_streak = (getattr(progress, "market_challenge_streak", 0) or 0) + 1
    else:
        progress.market_challenge_streak = 0

    progress.market_challenges_total = (getattr(progress, "market_challenges_total", 0) or 0) + 1
    db.commit()

    # League points: +5 correct, +2 attempted
    week_iso = _current_week_iso()
    league_pts = 5 if correct else 2
    _add_league_points(db, current_user.id, week_iso, league_pts, "challenges")

    # Badge checks
    badges_earned: list[str] = []
    total_attempts = getattr(progress, "market_challenges_total", 0) or 0
    total_correct = getattr(progress, "market_challenges_correct", 0) or 0
    streak = getattr(progress, "market_challenge_streak", 0) or 0

    if total_attempts == 1:
        if _award_badge(db, current_user.id, "first_challenge"):
            badges_earned.append("first_challenge")

    if streak >= 7:
        if _award_badge(db, current_user.id, "challenge_streak_7"):
            badges_earned.append("challenge_streak_7")

    if total_correct >= 10:
        if _award_badge(db, current_user.id, "challenge_perfect_10"):
            badges_earned.append("challenge_perfect_10")

    if total_correct >= 10:
        if _award_badge(db, current_user.id, "challenge_correct_10"):
            badges_earned.append("challenge_correct_10")

    return {
        "correct": correct,
        "explanation": challenge.explanation,
        "xp_earned": xp_earned,
        "new_streak": streak,
        "share_emoji": challenge.share_emoji,
        "badges_earned": badges_earned,
    }


# ── Streak endpoints ──────────────────────────────────────────────────────────

@router.get("/streak")
def get_streak(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    progress = _get_or_create_progress(db, current_user.id)
    today = date.today()

    # Auto-apply freeze logic
    last = progress.last_activity_date
    if last and (today - last).days == 2:
        freezes = progress.streak_freezes or 0
        freeze_month = getattr(progress, "freeze_month", None)
        if freezes > 0 and freeze_month == today.month:
            progress.streak_freezes = freezes - 1
            # Treat yesterday as activity day (silent freeze use)
            progress.last_activity_date = today - timedelta(days=1)
            db.commit()

    # Reset freezes at new month
    freeze_month = getattr(progress, "freeze_month", None)
    if freeze_month != today.month:
        progress.streak_freezes = 2
        progress.freeze_month = today.month
        db.commit()

    # Compute active_this_month from last_activity_date being within this month
    active_this_month = (
        last is not None and last.month == today.month and last.year == today.year
    )

    return {
        "current_streak": progress.streak or 0,
        "longest_streak": progress.longest_streak or 0,
        "freezes_remaining": progress.streak_freezes or 0,
        "last_activity_date": progress.last_activity_date.isoformat() if progress.last_activity_date else None,
        "total_active_days": progress.streak or 0,
        "active_this_month": active_this_month,
    }


class ActivityBody(BaseModel):
    activity_type: str  # "lesson" | "challenge" | "journal" | "thesis" | "portfolio_review"


@router.post("/streak/activity")
def record_activity(
    body: ActivityBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    valid_types = {"lesson", "challenge", "journal", "thesis", "portfolio_review"}
    if body.activity_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"activity_type must be one of: {valid_types}")

    today = date.today()
    # Only Mon-Fri count for streak (weekends are grace days)
    is_weekday = today.isoweekday() <= 5

    progress = _get_or_create_progress(db, current_user.id)
    streak_updated = False

    if is_weekday:
        last = progress.last_activity_date
        if last is None or last < today:
            # Check for streak break (more than 1 weekday gap, ignoring weekends)
            if last is None:
                new_streak = 1
            else:
                days_gap = (today - last).days
                # Count business days in gap
                if days_gap == 1:
                    new_streak = (progress.streak or 0) + 1
                elif days_gap == 3 and last.isoweekday() == 5:
                    # Friday to Monday — weekend bridged
                    new_streak = (progress.streak or 0) + 1
                else:
                    new_streak = 1  # streak broken

            progress.streak = new_streak
            progress.longest_streak = max(progress.longest_streak or 0, new_streak)
            progress.last_activity_date = today
            streak_updated = True
            db.commit()

    # Award league points
    points_map = {
        "lesson": 10,
        "challenge": 5,
        "journal": 3,
        "thesis": 3,
        "portfolio_review": 2,
    }
    league_category_map = {
        "lesson": "lessons",
        "challenge": "challenges",
        "journal": "journal",
        "thesis": "journal",
        "portfolio_review": "backtests",
    }
    pts = points_map.get(body.activity_type, 2)
    cat = league_category_map.get(body.activity_type, "backtests")
    week_iso = _current_week_iso()
    _add_league_points(db, current_user.id, week_iso, pts, cat)

    return {
        "streak_updated": streak_updated,
        "current_streak": progress.streak or 0,
        "points_earned": pts,
    }


# ── Achievements endpoint ─────────────────────────────────────────────────────

@router.get("/achievements")
def get_achievements(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Fetch all badge ids the user has earned
    user_badges = db.query(UserBadge).filter_by(user_id=current_user.id).all()
    earned_map: dict[str, datetime] = {b.badge_id: b.earned_at for b in user_badges}

    # Progress tracking queries
    progress = _get_or_create_progress(db, current_user.id)
    lesson_count = len(json.loads(progress.completed_lesson_ids or "[]"))
    journal_count = db.query(JournalEntry).filter_by(user_id=current_user.id).count()
    paper_trade_count = db.query(PaperTransaction).filter_by(user_id=current_user.id).count()
    watchlist_count = (
        db.query(WatchlistItem)
        .join(WatchlistItem.__table__, isouter=False)
        .filter(WatchlistItem.watchlist_id.in_(
            db.query(WatchlistItem.watchlist_id)
        ))
        .count()
    )
    total_correct = getattr(progress, "market_challenges_correct", 0) or 0
    total_attempts = getattr(progress, "market_challenges_total", 0) or 0
    streak = progress.streak or 0
    xp = progress.xp or 0
    level = progress.level or 1
    challenge_streak = getattr(progress, "market_challenge_streak", 0) or 0

    def _progress_for(achievement_id: str) -> int:
        return {
            "onboarding_complete": 1 if progress.onboarding_complete else 0,
            "first_lesson": min(lesson_count, 1),
            "first_challenge": min(total_attempts, 1),
            "first_paper_trade": min(paper_trade_count, 1),
            "lessons_5": min(lesson_count, 5),
            "lessons_25": min(lesson_count, 25),
            "lessons_50": min(lesson_count, 50),
            "lessons_100": min(lesson_count, 100),
            "challenge_correct_10": min(total_correct, 10),
            "challenge_streak_7": min(challenge_streak, 7),
            "challenge_perfect_10": min(total_correct, 10),
            "journal_1": min(journal_count, 1),
            "journal_10": min(journal_count, 10),
            "journal_30": min(journal_count, 30),
            "streak_7": min(streak, 7),
            "streak_30": min(streak, 30),
            "streak_100": min(streak, 100),
            "paper_trades_10": min(paper_trade_count, 10),
            "paper_trades_50": min(paper_trade_count, 50),
            "xp_1000": min(xp, 1000),
            "level_5": 1 if level >= 5 else 0,
            "level_10": 1 if level >= 10 else 0,
            "completionist": min(len(earned_map), 40),
        }.get(achievement_id, 1 if achievement_id in earned_map else 0)

    result = []
    for ach in _ACHIEVEMENT_CATALOGUE:
        earned_at = earned_map.get(ach["id"])
        prog = _progress_for(ach["id"])
        result.append({
            "id": ach["id"],
            "name": ach["name"],
            "description": ach["description"],
            "category": ach["category"],
            "icon_emoji": ach["icon_emoji"],
            "unlocked": ach["id"] in earned_map,
            "unlocked_at": earned_at.isoformat() if earned_at else None,
            "progress": prog,
            "max_progress": ach["max_progress"],
        })
    return result


# ── League endpoints ──────────────────────────────────────────────────────────

@router.get("/leagues/me")
def get_my_league(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    progress = _get_or_create_progress(db, current_user.id)
    tier = getattr(progress, "league_tier", None) or "Bronze"
    week_iso = _current_week_iso()

    # Get or create cohort for this tier and week
    cohort = db.query(LeagueCohort).filter_by(week_iso=week_iso, tier=tier).first()
    if not cohort:
        cohort = LeagueCohort(
            week_iso=week_iso,
            tier=tier,
            user_ids=json.dumps([current_user.id]),
            finalized=False,
            created_at=datetime.now(timezone.utc),
        )
        db.add(cohort)
        db.commit()
        db.refresh(cohort)
    else:
        # Add user to cohort if not already present (max 30)
        ids: list[int] = json.loads(cohort.user_ids or "[]")
        if current_user.id not in ids and len(ids) < 30:
            ids.append(current_user.id)
            cohort.user_ids = json.dumps(ids)
            db.commit()

    cohort_user_ids: list[int] = json.loads(cohort.user_ids or "[]")

    # Get points for all users in cohort
    all_points = (
        db.query(LeaguePoints)
        .filter(
            LeaguePoints.week_iso == week_iso,
            LeaguePoints.user_id.in_(cohort_user_ids),
        )
        .all()
    )
    pts_map = {lp.user_id: lp.points for lp in all_points}

    # Build leaderboard rows
    leaderboard_users = (
        db.query(User).filter(User.id.in_(cohort_user_ids)).all()
    )
    user_map = {u.id: u for u in leaderboard_users}

    leaderboard = sorted(
        [
            {"user_id": uid, "username": user_map[uid].username if uid in user_map else "Unknown", "points": pts_map.get(uid, 0)}
            for uid in cohort_user_ids
        ],
        key=lambda x: x["points"],
        reverse=True,
    )

    my_points = pts_map.get(current_user.id, 0)
    cohort_rank = next((i + 1 for i, row in enumerate(leaderboard) if row["user_id"] == current_user.id), len(leaderboard))

    # Promotion zone = top 7, demotion zone = bottom 5
    promotion_zone = cohort_rank <= 7
    demotion_zone = cohort_rank > (len(leaderboard) - 5) and len(leaderboard) >= 10

    # Next reset = next Monday
    today = date.today()
    days_until_monday = (7 - today.isoweekday()) % 7 or 7
    next_reset = datetime.combine(today + timedelta(days=days_until_monday), datetime.min.time())

    ranked_cohort = [
        {
            "username": row["username"],
            "points": row["points"],
            "rank": i + 1,
            "is_me": row["user_id"] == current_user.id,
        }
        for i, row in enumerate(leaderboard)
    ]

    return {
        "tier": tier,
        "cohort_rank": cohort_rank,
        "points_this_week": my_points,
        "promotion_zone": promotion_zone,
        "demotion_zone": demotion_zone,
        "next_reset_at": next_reset.isoformat(),
        "cohort": ranked_cohort,
    }


# ── Recap endpoints ───────────────────────────────────────────────────────────

@router.get("/recap/weekly")
def get_weekly_recap(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    today = date.today()
    # Last completed Mon-Sun week
    # Monday of current week
    monday_this_week = today - timedelta(days=today.isoweekday() - 1)
    week_start = monday_this_week - timedelta(weeks=1)
    week_end = week_start + timedelta(days=6)
    week_label = f"{week_start.strftime('%b %d')} – {week_end.strftime('%b %d, %Y')}"

    # Count trades in that week
    trades = (
        db.query(PaperTransaction)
        .filter(
            PaperTransaction.user_id == current_user.id,
            func.date(PaperTransaction.created_at) >= week_start,
            func.date(PaperTransaction.created_at) <= week_end,
        )
        .all()
    )
    trades_count = len(trades)

    # Lesson completions
    completions = (
        db.query(LessonCompletion)
        .filter(
            LessonCompletion.user_id == current_user.id,
            func.date(LessonCompletion.completed_at) >= week_start,
            func.date(LessonCompletion.completed_at) <= week_end,
        )
        .count()
    )

    # Challenge stats
    challenge_attempts = (
        db.query(MarketChallengeAttempt)
        .join(MarketChallenge, MarketChallengeAttempt.challenge_id == MarketChallenge.id)
        .filter(
            MarketChallengeAttempt.user_id == current_user.id,
            MarketChallenge.challenge_date >= week_start,
            MarketChallenge.challenge_date <= week_end,
        )
        .all()
    )
    challenges_attempted = len(challenge_attempts)
    challenges_correct = sum(1 for a in challenge_attempts if a.correct)

    # Journal entries
    journal_count = (
        db.query(JournalEntry)
        .filter(
            JournalEntry.user_id == current_user.id,
            JournalEntry.trade_date >= week_start,
            JournalEntry.trade_date <= week_end,
        )
        .count()
    )

    # Streak days this week
    progress = _get_or_create_progress(db, current_user.id)
    streak_days = min(progress.streak or 0, 5)  # Max 5 weekdays in a week

    # League points this week
    year, week_num, _ = week_start.isocalendar()
    prev_week_iso = f"{year}-W{week_num:02d}"
    lp = db.query(LeaguePoints).filter_by(user_id=current_user.id, week_iso=prev_week_iso).first()
    points_earned = lp.points if lp else 0

    # Top mover from paper transactions this week
    top_mover = None
    if trades:
        best = max(trades, key=lambda t: abs(t.realized_pnl or 0), default=None)
        if best and best.realized_pnl and best.fill_price and best.cost_basis:
            pct = ((best.fill_price - best.cost_basis) / best.cost_basis) * 100 if best.cost_basis else 0
            top_mover = {"symbol": best.symbol, "pct": round(pct, 2)}

    return {
        "week_label": week_label,
        "trades_count": trades_count,
        "lessons_completed": completions,
        "challenges_correct": challenges_correct,
        "challenges_attempted": challenges_attempted,
        "streak_days": streak_days,
        "points_earned": points_earned,
        "top_mover": top_mover,
        "journal_entries": journal_count,
    }


@router.get("/recap/annual")
def get_annual_recap(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    today = date.today()
    year = today.year
    year_start = date(year, 1, 1)

    # Total paper trades this year
    annual_trades = (
        db.query(PaperTransaction)
        .filter(
            PaperTransaction.user_id == current_user.id,
            func.date(PaperTransaction.created_at) >= year_start,
        )
        .all()
    )
    total_trades = len(annual_trades)

    # Learning hours: lessons × 5 min = hours
    annual_lessons = (
        db.query(LessonCompletion)
        .filter(
            LessonCompletion.user_id == current_user.id,
            func.date(LessonCompletion.completed_at) >= year_start,
        )
        .count()
    )
    learning_hours = round((annual_lessons * 5) / 60, 1)

    # Most-watched ticker from watchlist items
    most_watched_ticker = None
    watchlist_items = (
        db.query(WatchlistItem.symbol, func.count(WatchlistItem.id).label("cnt"))
        .group_by(WatchlistItem.symbol)
        .order_by(func.count(WatchlistItem.id).desc())
        .first()
    )
    if watchlist_items:
        most_watched_ticker = watchlist_items.symbol

    # Best paper position by % gain
    best_position = None
    if annual_trades:
        profitable = [
            t for t in annual_trades
            if t.realized_pnl and t.realized_pnl > 0 and t.cost_basis and t.cost_basis > 0
        ]
        if profitable:
            best = max(profitable, key=lambda t: (t.fill_price - t.cost_basis) / t.cost_basis)
            pct_gain = ((best.fill_price - best.cost_basis) / best.cost_basis) * 100
            best_position = {"symbol": best.symbol, "pct_gain": round(pct_gain, 2)}

    # Average hold time (approx from created_at spread — simplified)
    avg_hold_days = None
    if len(annual_trades) >= 2:
        dates = sorted([t.created_at for t in annual_trades if t.created_at])
        if dates:
            span = (dates[-1] - dates[0]).days
            avg_hold_days = round(span / max(total_trades, 1), 1)

    # Sector personality from position symbols (simplified heuristic)
    sector_map = {
        "AAPL": "Technology", "MSFT": "Technology", "NVDA": "Technology",
        "GOOGL": "Technology", "META": "Technology", "AMZN": "Consumer",
        "TSLA": "Consumer", "JPM": "Financials", "GS": "Financials",
        "XOM": "Energy", "CVX": "Energy", "JNJ": "Healthcare",
        "UNH": "Healthcare", "PFE": "Healthcare", "SPY": "Index", "QQQ": "Index",
    }
    if annual_trades:
        sector_counts: dict[str, int] = {}
        for t in annual_trades:
            sector = sector_map.get(t.symbol, "Other")
            sector_counts[sector] = sector_counts.get(sector, 0) + 1
        sector_personality = max(sector_counts, key=sector_counts.get)
    else:
        sector_personality = "Diversified"

    # Streak summary
    progress = _get_or_create_progress(db, current_user.id)
    longest_streak = progress.longest_streak or 0

    # Challenge attempts this year
    annual_challenge_attempts = (
        db.query(MarketChallengeAttempt)
        .join(MarketChallenge, MarketChallengeAttempt.challenge_id == MarketChallenge.id)
        .filter(
            MarketChallengeAttempt.user_id == current_user.id,
            MarketChallenge.challenge_date >= year_start,
        )
        .count()
    )

    # Achievements count
    achievements_count = db.query(UserBadge).filter_by(user_id=current_user.id).count()

    # Total active days = streak
    total_active_days = progress.streak or 0

    shareable_text = (
        f"My {year} on BMG Capital: "
        f"{total_trades} trades, "
        f"{learning_hours}h of learning, "
        f"{longest_streak}-day streak, "
        f"{achievements_count} achievements unlocked."
    )

    return {
        "year": year,
        "total_trades": total_trades,
        "learning_hours": learning_hours,
        "most_watched_ticker": most_watched_ticker,
        "best_position": best_position,
        "avg_hold_days": avg_hold_days,
        "sector_personality": sector_personality,
        "longest_streak": longest_streak,
        "total_active_days": total_active_days,
        "achievements_count": achievements_count,
        "challenges_attempted": annual_challenge_attempts,
        "shareable_text": shareable_text,
    }
