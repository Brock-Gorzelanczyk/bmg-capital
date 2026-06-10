"""Idempotent CREATE TABLE IF NOT EXISTS migrations for sentinel tables."""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


def run_migrations(engine: Engine) -> None:
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS agent_events (
                id BIGSERIAL PRIMARY KEY,
                agent_id TEXT NOT NULL,
                severity TEXT NOT NULL,
                category TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                payload JSONB NOT NULL,
                state TEXT NOT NULL DEFAULT 'open',
                detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                resolved_at TIMESTAMPTZ
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_agent_events_open
                ON agent_events(state) WHERE state = 'open'
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_agent_events_fingerprint
                ON agent_events(fingerprint)
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS agent_fixes (
                id BIGSERIAL PRIMARY KEY,
                event_id BIGINT NOT NULL REFERENCES agent_events(id),
                fixer_agent TEXT NOT NULL,
                pr_number INT,
                pr_url TEXT,
                files_changed TEXT[],
                diff_summary TEXT,
                llm_model TEXT,
                cost_usd NUMERIC(10,6),
                status TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS agent_circuit_breakers (
                id BIGSERIAL PRIMARY KEY,
                breaker_type TEXT NOT NULL,
                key TEXT NOT NULL,
                tripped_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                resets_at TIMESTAMPTZ NOT NULL,
                reason TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS agent_escalations (
                id BIGSERIAL PRIMARY KEY,
                event_id BIGINT NOT NULL REFERENCES agent_events(id),
                paste_ready TEXT NOT NULL,
                sent_to_discord BOOLEAN DEFAULT false,
                sent_at TIMESTAMPTZ,
                user_action TEXT
            )
        """))
        conn.commit()
        logger.info("[sentinel-migrations] All sentinel tables ready.")
