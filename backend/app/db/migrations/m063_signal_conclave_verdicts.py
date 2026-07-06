"""m063 — signal_conclave_verdicts table.

Feature: Agent Conclave. A 4-agent LLM filter (Analyst, Oracle, Quant,
Master) sits between signal creation and Discord promotion. Only
approved signals post to Discord. All raw signals still persist to
bot_signals so nothing is lost.

This migration creates the verdict table. The feature itself is env-
gated (CONCLAVE_ENABLED=false by default) so shipping this migration
does nothing to production behavior.
"""
from __future__ import annotations

import logging

from sqlalchemy import text

from app.db.migrations._gate import already_ran, record

logger = logging.getLogger(__name__)

_MIGRATION_NAME = "m063_signal_conclave_verdicts_2026_07"


def run(conn) -> dict:
    if already_ran(conn, _MIGRATION_NAME):
        return {"skipped_reason": "already_applied", "executed": False}

    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS signal_conclave_verdicts (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id           INTEGER NOT NULL,
            bot_name            VARCHAR(80),
            analyst_score       INTEGER,
            analyst_reasoning   TEXT,
            oracle_prediction   TEXT,
            oracle_confidence   INTEGER,
            quant_win_rate      FLOAT,
            quant_sample_size   INTEGER,
            quant_verdict       VARCHAR(8),
            master_final        VARCHAR(8) NOT NULL,
            master_reasoning    TEXT,
            chart_path          TEXT,
            latency_ms          INTEGER,
            fail_open           BOOLEAN DEFAULT 0,
            created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(signal_id) REFERENCES bot_signals(id)
        )
    """))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_conclave_signal_id "
        "ON signal_conclave_verdicts(signal_id)"
    ))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_conclave_created_at "
        "ON signal_conclave_verdicts(created_at)"
    ))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_conclave_bot_name "
        "ON signal_conclave_verdicts(bot_name)"
    ))

    record(conn, _MIGRATION_NAME)
    return {"executed": True, "table": "signal_conclave_verdicts"}
