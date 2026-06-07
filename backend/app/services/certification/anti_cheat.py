from __future__ import annotations

from datetime import datetime, timezone

from app.db.models.exams import ExamAttempt

TAB_SWITCH_WARNING_1 = 1
TAB_SWITCH_WARNING_2 = 2
TAB_SWITCH_DISQUALIFY = 3

TIME_LIMIT_SECONDS: dict[str, int] = {
    "learning_center": 4 * 3600,  # 4 hours
    "track": 120 * 60,            # 2 hours (legacy)
    "tier1": 180 * 60,            # 3 hours (legacy)
    "tier2": 180 * 60,
    "tier3": 180 * 60,
}


def check_time_expired(attempt: ExamAttempt) -> bool:
    """Return True if the attempt has exceeded its allowed time."""
    time_limit = TIME_LIMIT_SECONDS.get(attempt.exam_type, TIME_LIMIT_SECONDS["track"])
    now = datetime.now(timezone.utc)
    # started_at may be naive or aware
    started = attempt.started_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    elapsed = (now - started).total_seconds()
    return elapsed > time_limit


def should_disqualify(tab_switches: int) -> bool:
    """Return True if the tab switch count warrants disqualification."""
    return tab_switches >= TAB_SWITCH_DISQUALIFY


def compute_time_remaining(attempt: ExamAttempt) -> int:
    """Return seconds remaining for an in-progress attempt (never negative)."""
    time_limit = TIME_LIMIT_SECONDS.get(attempt.exam_type, TIME_LIMIT_SECONDS["track"])
    now = datetime.now(timezone.utc)
    started = attempt.started_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    elapsed = int((now - started).total_seconds())
    remaining = time_limit - elapsed
    return max(remaining, 0)
