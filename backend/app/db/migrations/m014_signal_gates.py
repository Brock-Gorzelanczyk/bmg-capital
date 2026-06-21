"""m014 — Create signal_gates table for discipline filter trace.

Idempotent: if table exists, no-op. Schema mirrors SignalGate ORM model.
"""
from __future__ import annotations

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)


def run(conn) -> dict:
    rows = conn.execute(text("PRAGMA table_info(signal_gates)")).fetchall() or []
    if rows:
        logger.info("[m014] signal_gates already exists — skipping")
        return {"skipped": True}

    conn.execute(text("""
        CREATE TABLE signal_gates (
            id                         INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id                  INTEGER,
            bot_name                   VARCHAR(100) NOT NULL,
            strategy                   VARCHAR(100),
            symbol                     VARCHAR(40) NOT NULL,
            side                       VARCHAR(10),
            regime_gate_passed         BOOLEAN NOT NULL DEFAULT 1,
            regime_current             VARCHAR(40),
            regime_required            VARCHAR(40),
            composite_score            INTEGER NOT NULL DEFAULT 0,
            composite_threshold        INTEGER NOT NULL DEFAULT 60,
            score_gate_passed          BOOLEAN NOT NULL DEFAULT 1,
            confluence_factors_passed  INTEGER NOT NULL DEFAULT 0,
            confluence_required        INTEGER NOT NULL DEFAULT 3,
            confluence_gate_passed     BOOLEAN NOT NULL DEFAULT 1,
            final_decision             VARCHAR(20) NOT NULL DEFAULT 'executed',
            filter_reason              VARCHAR(40),
            created_at                 DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
            FOREIGN KEY (signal_id) REFERENCES bot_signals(id)
        )
    """))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_signal_gates_bot_created "
        "ON signal_gates (bot_name, created_at)"
    ))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_signal_gates_decision_created "
        "ON signal_gates (final_decision, created_at)"
    ))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_signal_gates_signal_id "
        "ON signal_gates (signal_id)"
    ))
    conn.commit()
    logger.info("[m014] signal_gates created")
    return {"created": True}
