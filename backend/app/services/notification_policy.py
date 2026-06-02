from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

QUIET_HOURS_START_UTC = 3   # 9PM Central = 3AM UTC
QUIET_HOURS_END_UTC = 13    # 7AM Central = 1PM UTC


def is_quiet_hours() -> bool:
    """True if current UTC time falls in the default quiet window."""
    now_h = datetime.now(timezone.utc).hour
    if QUIET_HOURS_START_UTC < QUIET_HOURS_END_UTC:
        return QUIET_HOURS_START_UTC <= now_h < QUIET_HOURS_END_UTC
    # Wraps midnight
    return now_h >= QUIET_HOURS_START_UTC or now_h < QUIET_HOURS_END_UTC


def get_push_budget(user_id: int, db: Session) -> int:
    """Return user's configured max push per day (default 4)."""
    try:
        from app.db.models.autopilot import AutopilotPolicy
        policy = db.query(AutopilotPolicy).filter_by(
            user_id=user_id, category="alerts"
        ).first()
        if policy and policy.config:
            val = policy.config.get("max_push_per_day", 4)
            if val == "unlimited":
                return 999
            return int(val)
        return 4
    except Exception:
        return 4


def get_push_count_today(user_id: int, db: Session) -> int:
    """Count push notifications already sent to user today."""
    try:
        from app.db.models.autopilot import AutopilotAction
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return db.query(AutopilotAction).filter(
            AutopilotAction.user_id == user_id,
            AutopilotAction.action_type == "push_notification_sent",
            AutopilotAction.created_at >= today_start,
        ).count()
    except Exception:
        return 0


def should_send_push(
    user_id: int,
    db: Session,
    is_guardrail: bool = False,
    category: str = "alerts",
    event_age_seconds: float = 0,
) -> bool:
    """
    Returns True if a push notification should be sent.

    Logic:
    1. Guardrail trips always send (bypass everything)
    2. Stale events (> 6h) always skip
    3. Quiet hours → skip (except guardrail)
    4. Push budget exhausted → skip
    5. Category push disabled in policy → skip
    """
    if is_guardrail:
        return True

    # Stale event
    if event_age_seconds > 21600:  # 6 hours
        return False

    # Quiet hours
    if is_quiet_hours():
        return False

    # Push budget
    budget = get_push_budget(user_id, db)
    used = get_push_count_today(user_id, db)
    if used >= budget:
        return False

    # Category push enabled
    try:
        from app.db.models.autopilot import AutopilotPolicy
        policy = db.query(AutopilotPolicy).filter_by(
            user_id=user_id, category=category
        ).first()
        if policy and policy.config:
            if not policy.config.get("push_enabled", True):
                return False
    except Exception:
        pass

    return True


def log_push_sent(user_id: int, db: Session, message: str, category: str = "alerts") -> None:
    """Record that a push was sent (for budget tracking). Never raises."""
    try:
        from app.services.autopilot_logger import log_autopilot_action
        log_autopilot_action(
            user_id=user_id,
            category=category,
            action_type="push_notification_sent",
            params={"message": message[:200]},
            ai_rationale=f"Push notification delivered: {message[:100]}",
        )
    except Exception:
        logger.error("log_push_sent: failed to record push action", exc_info=True)


def batch_similar_actions(actions: list[dict]) -> list[dict]:
    """
    Group actions by category. If same category has >1 action,
    merge into a single summary entry.
    Returns list of (possibly batched) notification dicts.
    """
    groups: dict[str, list[dict]] = defaultdict(list)
    for action in actions:
        groups[action.get("category", "other")].append(action)

    result = []
    for category, items in groups.items():
        if len(items) == 1:
            result.append(items[0])
        else:
            # Batch into summary
            result.append({
                "category": category,
                "action_type": "batched_summary",
                "message": f"{len(items)} {category} events: " + "; ".join(
                    a.get("action_type", "") for a in items[:3]
                ),
                "count": len(items),
            })
    return result
