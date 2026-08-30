"""m103 — confluence_picks.rule_compliance JSON column (Brock 2026-08-30).

Adds the field needed for the research → decision pipeline.

Every armed pick gets a rule-compliance record attached at entry, per
`vault:research/decision-rules.md`. The record stores per-rule verdicts
(SATISFIED | VIOLATED | UNTESTABLE | APPLIED | N/A) BEFORE the outcome is
known, so the scorecard can compute discrimination without lookback bias.

The column is TEXT (SQLite JSON) to keep migration simple; consumers
`json.loads()` it on read.

Idempotent (checks column existence before ALTER).
"""
from __future__ import annotations

import logging
from sqlalchemy import text

logger = logging.getLogger(__name__)

_MIGRATION_NAME = "m103_confluence_rule_compliance_2026_08_30"


def _already_ran(conn) -> bool:
    try:
        row = conn.execute(
            text("SELECT 1 FROM schema_migrations WHERE name = :n"),
            {"n": _MIGRATION_NAME},
        ).fetchone()
        return row is not None
    except Exception:
        return False


def _column_exists(conn, table: str, col: str) -> bool:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return any(r[1] == col for r in rows)


def run(conn) -> dict:
    if _already_ran(conn):
        return {"status": "skip", "reason": "already_ran"}

    tbl = "confluence_picks"

    if not _column_exists(conn, tbl, "rule_compliance"):
        conn.execute(text(f"ALTER TABLE {tbl} ADD COLUMN rule_compliance TEXT"))
        added = 1
    else:
        added = 0

    if not _column_exists(conn, tbl, "rule_compliance_evaluated_at"):
        conn.execute(text(f"ALTER TABLE {tbl} ADD COLUMN rule_compliance_evaluated_at TEXT"))
        added += 1

    try:
        conn.execute(
            text("INSERT OR IGNORE INTO schema_migrations (name) VALUES (:n)"),
            {"n": _MIGRATION_NAME},
        )
    except Exception as e:
        logger.warning("[m103] schema_migrations write failed: %s", e)

    return {"status": "ok", "added": added, "table": tbl}
