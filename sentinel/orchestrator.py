"""
Sentinel Orchestrator — top-level coordinator.
Schedules agents, enforces guardrails, routes events to fixers or escalator.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import text

from sentinel.db.session import SessionLocal
from sentinel.settings import settings
from sentinel.guardrails import validate_fix_request
from sentinel.cost_tracker import (
    is_cost_cap_reached,
    is_pr_limit_reached,
    is_circuit_breaker_tripped,
    file_pr_count_today,
    trip_file_loop_breaker,
)

logger = logging.getLogger(__name__)

# Lazy imports to avoid circular deps at module load
def _get_railway_watcher():
    from sentinel.agents.railway_watcher import RailwayWatcher
    return RailwayWatcher

def _get_discord_health():
    from sentinel.agents.discord_health import DiscordHealthAgent
    return DiscordHealthAgent

def _get_app_scanner():
    from sentinel.agents.app_scanner import AppScannerAgent
    return AppScannerAgent

def _get_frontend_fixer():
    from sentinel.agents.frontend_fixer import FrontendFixerAgent
    return FrontendFixerAgent

def _get_backend_fixer():
    from sentinel.agents.backend_fixer import BackendFixerAgent
    return BackendFixerAgent

def _get_escalator():
    from sentinel.agents.escalator import EscalatorAgent
    return EscalatorAgent


def insert_event(
    db,
    agent_id: str,
    severity: str,
    category: str,
    fingerprint: str,
    payload: dict,
) -> int | None:
    """Insert a new event if fingerprint not seen in last hour. Returns event id or None."""
    existing = db.execute(text("""
        SELECT id FROM agent_events
        WHERE fingerprint = :fp
          AND detected_at > NOW() - INTERVAL '1 hour'
          AND state != 'suppressed'
        LIMIT 1
    """), {"fp": fingerprint}).fetchone()

    if existing:
        logger.debug("[orchestrator] Dedup — fingerprint %s already seen", fingerprint)
        return None

    row = db.execute(text("""
        INSERT INTO agent_events (agent_id, severity, category, fingerprint, payload, state)
        VALUES (:agent_id, :severity, :category, :fp, :payload::jsonb, 'open')
        RETURNING id
    """), {
        "agent_id": agent_id,
        "severity": severity,
        "category": category,
        "fp": fingerprint,
        "payload": __import__("json").dumps(payload),
    }).fetchone()
    db.commit()

    event_id = row[0]
    logger.info("[orchestrator] New event #%d — %s/%s (%s)", event_id, agent_id, category, severity)
    return event_id


def route_event(event_id: int, category: str, payload: dict) -> None:
    """Apply guardrails and dispatch to fixer or escalator."""
    if not settings.sentinel_enabled:
        logger.debug("[orchestrator] Sentinel disabled — skip routing")
        return

    file_path = payload.get("file", "")
    allowed, reason = validate_fix_request(category, file_path)

    db = SessionLocal()
    try:
        # Safety chain
        if not allowed:
            logger.info("[orchestrator] Auto-fix not allowed for event #%d: %s", event_id, reason)
            _escalate(db, event_id, reason)
            return

        if is_cost_cap_reached(db, settings.daily_cost_cap_usd):
            _escalate(db, event_id, "Daily cost cap reached — escalate-only mode")
            return

        if is_pr_limit_reached(db, settings.max_daily_prs):
            _escalate(db, event_id, "Daily PR limit reached")
            return

        if file_path and is_circuit_breaker_tripped(db, file_path):
            _escalate(db, event_id, f"Circuit breaker active for {file_path}")
            return

        if file_path:
            pr_count = file_pr_count_today(db, file_path)
            if pr_count >= 2:
                trip_file_loop_breaker(db, file_path)
                _escalate(db, event_id, f"File loop protection: {file_path} had {pr_count} PRs today")
                return

        # Dispatch to appropriate fixer
        _dispatch_fixer(event_id, category, payload)

    finally:
        db.close()


def _escalate(db, event_id: int, reason: str) -> None:
    db.execute(text("""
        UPDATE agent_events SET state = 'escalated' WHERE id = :id
    """), {"id": event_id})
    db.commit()

    escalator_cls = _get_escalator()
    escalator = escalator_cls()
    try:
        escalator.handle(event_id, reason)
    except Exception as e:
        logger.error("[orchestrator] Escalator failed for event #%d: %s", event_id, e, exc_info=True)


def _dispatch_fixer(event_id: int, category: str, payload: dict) -> None:
    frontend_cats = {
        "typescript_missing_property", "missing_npm_dependency",
        "syntax_error_simple", "broken_image_url", "css_class_typo",
        "eslint_warning", "import_path_wrong", "dead_link",
    }
    backend_cats = {
        "missing_python_dependency", "import_path_error",
        "typing_annotation_error", "missing_return_statement",
    }

    if category in frontend_cats:
        try:
            fixer_cls = _get_frontend_fixer()
            fixer_cls().handle(event_id, payload)
        except Exception as e:
            logger.error("[orchestrator] Frontend fixer failed for event #%d: %s", event_id, e, exc_info=True)
            db = SessionLocal()
            try:
                _escalate(db, event_id, f"Frontend fixer error: {e}")
            finally:
                db.close()
    elif category in backend_cats:
        try:
            fixer_cls = _get_backend_fixer()
            fixer_cls().handle(event_id, payload)
        except Exception as e:
            logger.error("[orchestrator] Backend fixer failed for event #%d: %s", event_id, e, exc_info=True)
            db = SessionLocal()
            try:
                _escalate(db, event_id, f"Backend fixer error: {e}")
            finally:
                db.close()
    else:
        db = SessionLocal()
        try:
            _escalate(db, event_id, f"No fixer for category '{category}'")
        finally:
            db.close()


def mark_resolved(fingerprint: str) -> None:
    db = SessionLocal()
    try:
        db.execute(text("""
            UPDATE agent_events
            SET state = 'resolved', resolved_at = NOW()
            WHERE fingerprint = :fp AND state = 'open'
        """), {"fp": fingerprint})
        db.commit()
    finally:
        db.close()


class SentinelOrchestrator:
    def __init__(self):
        self.scheduler = BackgroundScheduler(timezone="UTC")
        self._setup_jobs()

    def _setup_jobs(self):
        from sentinel.agents.railway_watcher import RailwayWatcher
        from sentinel.agents.discord_health import DiscordHealthAgent
        from sentinel.agents.app_scanner import AppScannerAgent

        rw = RailwayWatcher()
        dh = DiscordHealthAgent()
        sc = AppScannerAgent()

        self.scheduler.add_job(rw.run, "interval", seconds=30, id="railway_watcher",
                               max_instances=1, coalesce=True)
        self.scheduler.add_job(dh.run, "interval", seconds=60, id="discord_health",
                               max_instances=1, coalesce=True)
        self.scheduler.add_job(sc.run, "interval", seconds=300, id="app_scanner",
                               max_instances=1, coalesce=True)

    def start(self):
        logger.info("[orchestrator] Starting Sentinel scheduler")
        self.scheduler.start()

    def stop(self):
        logger.info("[orchestrator] Stopping Sentinel scheduler")
        self.scheduler.shutdown(wait=False)

    def status(self) -> dict:
        db = SessionLocal()
        try:
            from sentinel.cost_tracker import get_today_cost, get_today_pr_count
            open_events = db.execute(text(
                "SELECT COUNT(*) FROM agent_events WHERE state = 'open'"
            )).scalar() or 0
            today_prs = get_today_pr_count(db)
            today_cost = get_today_cost(db)
            pending_escalations = db.execute(text(
                "SELECT COUNT(*) FROM agent_escalations WHERE sent_to_discord = true AND user_action IS NULL"
            )).scalar() or 0
            return {
                "enabled": settings.sentinel_enabled,
                "open_events": open_events,
                "today_prs": today_prs,
                "today_cost_usd": round(today_cost, 4),
                "pending_escalations": pending_escalations,
                "daily_cost_cap_usd": settings.daily_cost_cap_usd,
                "max_daily_prs": settings.max_daily_prs,
            }
        finally:
            db.close()
