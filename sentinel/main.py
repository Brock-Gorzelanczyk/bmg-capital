"""
BMG Sentinel — entry point.
Starts the orchestrator scheduler and FastAPI admin API.
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from sqlalchemy import text

from sentinel.observability import configure_logging, metrics, get_sentinel_stats
from sentinel.settings import settings
from sentinel.db.session import SessionLocal, engine
from sentinel.db.migrations import run_migrations
from sentinel.orchestrator import SentinelOrchestrator

configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="BMG Sentinel", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

_orchestrator: SentinelOrchestrator | None = None


@app.on_event("startup")
async def startup() -> None:
    global _orchestrator
    logger.info("sentinel starting", extra={"sentinel_enabled": settings.sentinel_enabled})

    try:
        run_migrations(engine)
        logger.info("db migrations complete")
    except Exception as e:
        logger.error("db migration failed", extra={"error": str(e)})

    _orchestrator = SentinelOrchestrator()
    if settings.sentinel_enabled:
        _orchestrator.start()
        logger.info("orchestrator started")
    else:
        logger.warning("SENTINEL_ENABLED=false — agents paused")


@app.on_event("shutdown")
async def shutdown() -> None:
    if _orchestrator:
        _orchestrator.stop()


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict:
    metrics.inc("health_checks")
    agent_info: dict = {}
    if _orchestrator:
        for name, a in _orchestrator.agent_status().items():
            agent_info[name] = {
                "running": a.get("running", False),
                "last_run": a.get("last_run"),
            }
    return {
        "status": "ok",
        "sentinel_enabled": settings.sentinel_enabled,
        "agents": agent_info,
    }


# ── Stats (KPIs for dashboard) ────────────────────────────────────────────────

@app.get("/api/sentinel/stats")
async def sentinel_stats() -> dict:
    db = SessionLocal()
    try:
        return get_sentinel_stats(db, settings.daily_cost_cap_usd, settings.max_daily_prs)
    finally:
        db.close()


# ── Events ────────────────────────────────────────────────────────────────────

@app.get("/api/sentinel/events")
async def sentinel_events(limit: int = 50, status: str = "open") -> list:
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT id, agent_id, severity, category, title,
                   affected_file, status, created_at, resolved_at
            FROM agent_events
            WHERE (:status = 'all' OR status = :status)
            ORDER BY created_at DESC
            LIMIT :limit
        """), {"status": status, "limit": limit}).fetchall()
        return [dict(r._mapping) for r in rows]
    finally:
        db.close()


# ── Fixes / PRs ───────────────────────────────────────────────────────────────

@app.get("/api/sentinel/fixes")
async def sentinel_fixes(limit: int = 50) -> list:
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT id, event_id, agent_id, category, file_path,
                   pr_url, pr_number, outcome, llm_cost_usd, created_at
            FROM agent_fixes
            ORDER BY created_at DESC
            LIMIT :limit
        """), {"limit": limit}).fetchall()
        return [dict(r._mapping) for r in rows]
    finally:
        db.close()


# ── Circuit breakers ──────────────────────────────────────────────────────────

@app.get("/api/sentinel/circuit-breakers")
async def circuit_breakers() -> list:
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT id, file_path, pr_count_today, tripped,
                   tripped_at, cooldown_until
            FROM agent_circuit_breakers
            ORDER BY tripped DESC, tripped_at DESC
        """)).fetchall()
        return [dict(r._mapping) for r in rows]
    finally:
        db.close()


# ── Escalations ───────────────────────────────────────────────────────────────

@app.get("/api/sentinel/escalations")
async def sentinel_escalations(limit: int = 50) -> list:
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT id, event_id, channel_id, message_preview,
                   resolved, created_at
            FROM agent_escalations
            ORDER BY created_at DESC
            LIMIT :limit
        """), {"limit": limit}).fetchall()
        return [dict(r._mapping) for r in rows]
    finally:
        db.close()


@app.post("/api/sentinel/escalations/{esc_id}/action")
async def set_user_action(esc_id: int, action: str) -> dict:
    if action not in ("fixed", "ignored", "snoozed"):
        raise HTTPException(status_code=400, detail="action must be fixed|ignored|snoozed")
    db = SessionLocal()
    try:
        db.execute(text("""
            UPDATE agent_escalations SET resolved = true WHERE id = :id
        """), {"id": esc_id})
        db.commit()
        metrics.inc("escalations_actioned", action=action)
        return {"ok": True}
    finally:
        db.close()


# ── Prometheus metrics ────────────────────────────────────────────────────────

@app.get("/metrics", response_class=PlainTextResponse)
async def prometheus_metrics() -> str:
    return metrics.prometheus_text()


# ── Entry ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8001))
    uvicorn.run("sentinel.main:app", host="0.0.0.0", port=port, reload=False)
