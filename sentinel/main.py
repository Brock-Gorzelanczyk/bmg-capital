"""
BMG Sentinel — entry point.
Starts the orchestrator scheduler and FastAPI admin API.
"""
from __future__ import annotations

import logging
import os
import sys

import uvicorn
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from sentinel.settings import settings
from sentinel.db.session import SessionLocal, engine
from sentinel.db.migrations import run_migrations
from sentinel.orchestrator import SentinelOrchestrator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

app = FastAPI(title="BMG Sentinel", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

_orchestrator: SentinelOrchestrator | None = None


@app.on_event("startup")
async def startup() -> None:
    global _orchestrator
    logger.info("[sentinel] Starting up — SENTINEL_ENABLED=%s", settings.sentinel_enabled)

    # Run DB migrations
    try:
        run_migrations(engine)
        logger.info("[sentinel] DB migrations complete")
    except Exception as e:
        logger.error("[sentinel] DB migration failed: %s", e)

    # Start orchestrator
    _orchestrator = SentinelOrchestrator()
    if settings.sentinel_enabled:
        _orchestrator.start()
        logger.info("[sentinel] Orchestrator started")
    else:
        logger.warning("[sentinel] SENTINEL_ENABLED=false — agents are paused")


@app.on_event("shutdown")
async def shutdown() -> None:
    if _orchestrator:
        _orchestrator.stop()


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "enabled": settings.sentinel_enabled}


@app.get("/api/sentinel/status")
async def sentinel_status() -> dict:
    if not _orchestrator:
        return {"error": "not initialized"}
    return _orchestrator.status()


@app.get("/api/sentinel/events")
async def sentinel_events(limit: int = 50, state: str = "open") -> dict:
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT id, agent_id, severity, category, state, detected_at, payload
            FROM agent_events
            WHERE state = :state
            ORDER BY detected_at DESC
            LIMIT :limit
        """), {"state": state, "limit": limit}).fetchall()
        return {"events": [dict(r._mapping) for r in rows]}
    finally:
        db.close()


@app.get("/api/sentinel/escalations")
async def sentinel_escalations() -> dict:
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT ae.id, ae.event_id, ae.paste_ready, ae.sent_at, ae.user_action,
                   ev.category, ev.severity
            FROM agent_escalations ae
            JOIN agent_events ev ON ev.id = ae.event_id
            WHERE ae.user_action IS NULL
            ORDER BY ae.sent_at DESC
            LIMIT 20
        """)).fetchall()
        return {"escalations": [dict(r._mapping) for r in rows]}
    finally:
        db.close()


@app.get("/api/sentinel/escalations/{esc_id}/paste")
async def get_paste_ready(esc_id: int) -> dict:
    db = SessionLocal()
    try:
        row = db.execute(text("""
            SELECT paste_ready FROM agent_escalations WHERE id = :id
        """), {"id": esc_id}).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Escalation not found")
        return {"paste_ready": row[0]}
    finally:
        db.close()


@app.post("/api/sentinel/escalations/{esc_id}/action")
async def set_user_action(esc_id: int, action: str) -> dict:
    if action not in ("fixed", "ignored", "snoozed"):
        raise HTTPException(status_code=400, detail="action must be fixed|ignored|snoozed")
    db = SessionLocal()
    try:
        db.execute(text("""
            UPDATE agent_escalations SET user_action = :action WHERE id = :id
        """), {"action": action, "id": esc_id})
        db.commit()
        return {"ok": True}
    finally:
        db.close()


@app.get("/api/sentinel/circuit-breakers")
async def circuit_breakers() -> dict:
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT id, breaker_type, key, tripped_at, resets_at, reason
            FROM agent_circuit_breakers
            WHERE resets_at > NOW()
            ORDER BY tripped_at DESC
        """)).fetchall()
        return {"breakers": [dict(r._mapping) for r in rows]}
    finally:
        db.close()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8001))
    uvicorn.run("sentinel.main:app", host="0.0.0.0", port=port, reload=False)
