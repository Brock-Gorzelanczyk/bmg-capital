"""m015 — Create hypotheses, system_events, lessons tables.

Idempotent: skip any table that already exists.
"""
from __future__ import annotations

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)


def _table_exists(conn, name: str) -> bool:
    rows = conn.execute(text(f"PRAGMA table_info({name})")).fetchall() or []
    return bool(rows)


def run(conn) -> dict:
    created: list[str] = []

    if not _table_exists(conn, "hypotheses"):
        conn.execute(text("""
            CREATE TABLE hypotheses (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                name              VARCHAR(200) NOT NULL,
                strategy_id       VARCHAR(100) NOT NULL UNIQUE,
                direction         VARCHAR(10) NOT NULL DEFAULT 'both',
                status            VARCHAR(20) NOT NULL DEFAULT 'testing',
                regime_preference VARCHAR(40),
                factor_exposures  JSON NOT NULL DEFAULT '{}',
                notes             TEXT,
                created_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_hyp_status_strategy ON hypotheses (status, strategy_id)"))
        created.append("hypotheses")

    if not _table_exists(conn, "system_events"):
        conn.execute(text("""
            CREATE TABLE system_events (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type VARCHAR(60) NOT NULL,
                message    TEXT NOT NULL,
                payload    JSON,
                ts         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_sysev_type ON system_events (event_type)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_sysev_ts ON system_events (ts)"))
        created.append("system_events")

    if not _table_exists(conn, "lessons"):
        conn.execute(text("""
            CREATE TABLE lessons (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                hypothesis_id INTEGER,
                context       TEXT,
                lesson_text   TEXT NOT NULL,
                recorded_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_lesson_hyp ON lessons (hypothesis_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_lesson_ts ON lessons (recorded_at)"))
        created.append("lessons")

    if created:
        conn.commit()
        logger.info("[m015] created tables: %s", ", ".join(created))
    else:
        logger.info("[m015] all hypothesis tables already exist — no-op")
    return {"created": created}
