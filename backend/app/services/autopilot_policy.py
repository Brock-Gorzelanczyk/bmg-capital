from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models.autopilot import AutopilotGuardrail, AutopilotPolicy

logger = logging.getLogger(__name__)

CATEGORIES = [
    "trading",
    "portfolio",
    "money",
    "research",
    "learning",
    "journal",
    "tax",
    "alerts",
    "account",
]

DEFAULT_POLICIES: dict[str, dict] = {
    "trading":   {"enabled": True,  "config": {}},
    "portfolio": {"enabled": True,  "config": {"rebalance_threshold_pct": 5.0, "dividend_reinvest": True}},
    "money":     {"enabled": False, "config": {"round_ups": False, "cash_sweep_threshold": 1000.0}},
    "research":  {"enabled": True,  "config": {"auto_curate_watchlist": True, "earnings_prep": True}},
    "learning":  {"enabled": True,  "config": {"daily_lesson": True, "auto_quiz": True}},
    "journal":   {"enabled": True,  "config": {"trade_prompts": True, "pattern_detection": True}},
    "tax":       {"enabled": True,  "config": {"tlh_scan": True, "wash_sale_guard": True}},
    "alerts":    {"enabled": True,  "config": {"smart_batch": True, "max_push_per_day": 4}},
    "account":   {"enabled": True,  "config": {}},
}


def get_or_create_policies(user_id: int, db: Session) -> dict[str, AutopilotPolicy]:
    """Return all 9 policies for user, creating defaults for any missing category."""
    existing_rows = (
        db.query(AutopilotPolicy)
        .filter(AutopilotPolicy.user_id == user_id)
        .all()
    )
    policies: dict[str, AutopilotPolicy] = {p.category: p for p in existing_rows}

    for category in CATEGORIES:
        if category not in policies:
            defaults = DEFAULT_POLICIES[category]
            policy = AutopilotPolicy(
                user_id=user_id,
                category=category,
                enabled=defaults["enabled"],
                config=defaults["config"],
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            db.add(policy)
            try:
                db.commit()
                db.refresh(policy)
                policies[category] = policy
            except Exception as e:
                db.rollback()
                logger.warning(f"autopilot_policy: could not create {category} policy for user {user_id}: {e}")
                # Re-fetch in case of race condition
                existing = (
                    db.query(AutopilotPolicy)
                    .filter_by(user_id=user_id, category=category)
                    .first()
                )
                if existing:
                    policies[category] = existing

    return policies


def get_or_create_autopilot_guardrail(user_id: int, db: Session) -> AutopilotGuardrail:
    """Return user's autopilot guardrail, creating defaults if none exist."""
    g = db.query(AutopilotGuardrail).filter_by(user_id=user_id).first()
    if not g:
        g = AutopilotGuardrail(user_id=user_id)
        db.add(g)
        db.commit()
        db.refresh(g)
    return g


def check_category_enabled(user_id: int, category: str, db: Session) -> bool:
    """Returns True if the category policy is enabled AND global autopilot is not paused."""
    guardrail = db.query(AutopilotGuardrail).filter_by(user_id=user_id).first()
    if guardrail and guardrail.global_paused:
        return False

    policy = db.query(AutopilotPolicy).filter_by(user_id=user_id, category=category).first()
    if policy is None:
        # Default from spec: most categories default to enabled
        defaults = DEFAULT_POLICIES.get(category, {})
        return bool(defaults.get("enabled", True))

    return policy.enabled
