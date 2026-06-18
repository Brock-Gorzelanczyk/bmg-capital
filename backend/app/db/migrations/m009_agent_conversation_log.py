"""Migration m009: Create agent_conversation_log table.

Logs every Discord conversation turn (incoming + agent reply) for audit
and context-building. Idempotent — safe to run every startup.
"""
from __future__ import annotations

import logging
from sqlalchemy import text

logger = logging.getLogger(__name__)


def run(conn) -> None:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS agent_conversation_log (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            agent        VARCHAR NOT NULL,
            channel_id   VARCHAR NOT NULL,
            author_name  VARCHAR NOT NULL,
            author_id    VARCHAR NOT NULL,
            user_message TEXT NOT NULL,
            agent_reply  TEXT NOT NULL,
            created_at   DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL
        )
    """))
    conn.commit()
    logger.info("[m009] agent_conversation_log table ensured")
