"""Daily LLM cost tracking with automatic escalate-only mode."""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import func, text

logger = logging.getLogger(__name__)


def get_today_cost(db: Session) -> float:
    row = db.execute(text("""
        SELECT COALESCE(SUM(cost_usd), 0)
        FROM agent_fixes
        WHERE created_at >= CURRENT_DATE
    """)).fetchone()
    return float(row[0]) if row else 0.0


def get_today_pr_count(db: Session) -> int:
    row = db.execute(text("""
        SELECT COUNT(*)
        FROM agent_fixes
        WHERE created_at >= CURRENT_DATE
          AND status IN ('proposed', 'merged')
    """)).fetchone()
    return int(row[0]) if row else 0


def record_fix_cost(db: Session, fix_id: int, cost_usd: float) -> None:
    db.execute(text("""
        UPDATE agent_fixes SET cost_usd = :cost WHERE id = :id
    """), {"cost": cost_usd, "id": fix_id})
    db.commit()


def is_cost_cap_reached(db: Session, cap: float) -> bool:
    today = get_today_cost(db)
    if today >= cap:
        logger.warning("[cost-tracker] Daily cost cap reached: $%.4f / $%.2f", today, cap)
        return True
    return False


def is_pr_limit_reached(db: Session, limit: int) -> bool:
    count = get_today_pr_count(db)
    if count >= limit:
        logger.warning("[cost-tracker] Daily PR limit reached: %d / %d", count, limit)
        return True
    return False


def is_circuit_breaker_tripped(db: Session, key: str) -> bool:
    row = db.execute(text("""
        SELECT id FROM agent_circuit_breakers
        WHERE key = :key AND resets_at > NOW()
        LIMIT 1
    """), {"key": key}).fetchone()
    return row is not None


def trip_circuit_breaker(
    db: Session,
    breaker_type: str,
    key: str,
    cooldown_hours: int,
    reason: str,
) -> None:
    db.execute(text("""
        INSERT INTO agent_circuit_breakers (breaker_type, key, resets_at, reason)
        VALUES (:bt, :key, NOW() + INTERVAL ':h hours', :reason)
    """).bindparams(h=cooldown_hours), {"bt": breaker_type, "key": key, "reason": reason})
    db.commit()
    logger.warning("[circuit-breaker] Tripped %s / %s for %dh: %s", breaker_type, key, cooldown_hours, reason)


def trip_file_loop_breaker(db: Session, file_path: str, reason: str = "2 PRs in 24h") -> None:
    """Convenience wrapper for the file-loop pattern."""
    db.execute(text("""
        INSERT INTO agent_circuit_breakers (breaker_type, key, resets_at, reason)
        VALUES ('file-loop', :key, NOW() + INTERVAL '48 hours', :reason)
        ON CONFLICT DO NOTHING
    """), {"key": file_path, "reason": reason})
    db.commit()


def file_pr_count_today(db: Session, file_path: str) -> int:
    row = db.execute(text("""
        SELECT COUNT(*) FROM agent_fixes af
        JOIN agent_events ae ON ae.id = af.event_id
        WHERE af.created_at >= NOW() - INTERVAL '24 hours'
          AND ae.payload->>'file' = :fp
          AND af.status IN ('proposed', 'merged')
    """), {"fp": file_path}).fetchone()
    return int(row[0]) if row else 0
