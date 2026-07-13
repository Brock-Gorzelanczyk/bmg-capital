"""Shared idempotency gate for one-shot migrations.

Use at the top of any migration's run() function:

    from app.db.migrations._gate import already_ran, record
    _NAME = "mNNN_short_description_YYYY_MM"

    def run(conn):
        if already_ran(conn, _NAME):
            return {"skipped_reason": "already_applied", "executed": False}
        ...do work...
        record(conn, _NAME)
        return {"executed": True, ...}

Why: the 2026-06-28 capital regression (sum drifted from $1M to $2.6M on
deploy) was caused by m021 running on every boot — it had no gate and
re-overwrote m027's spec amounts to flat $200K. Same bomb can hide in any
ungated migration that UPDATEs canonical state.
"""
from __future__ import annotations

import logging
from sqlalchemy import text

logger = logging.getLogger(__name__)


def already_ran(conn, name: str) -> bool:
    try:
        return conn.execute(
            text("SELECT 1 FROM schema_migrations WHERE migration_name = :n"),
            {"n": name},
        ).fetchone() is not None
    except Exception:
        return False


def record(conn, name: str) -> None:
    """Mark a migration as applied. Commits, then verifies the row landed.

    2026-07-12 hardening for known-issue #12 (m084/m085 landed data
    changes but never recorded in schema_migrations, causing them to
    re-run every boot):

      1. Same-transaction verify SELECT after the INSERT — catches the
         case where the INSERT was silently rolled back by an outer
         context (SQLAlchemy 2.0 auto-begin nuance under engine.begin()).
      2. On verify failure, retry via a brand-new connection from the
         underlying engine. This isolates the write from whatever
         transactional weirdness caused the first attempt to drop.
      3. Loud logging so a silent failure can't hide again.

    Commit remains inside record() to preserve the invariant tested by
    test_m033_* — callers should still be able to expect the row is
    visible from other sessions once record() returns.
    """
    try:
        conn.execute(
            text(
                "INSERT INTO schema_migrations (migration_name) VALUES (:n)"
                " ON CONFLICT (migration_name) DO NOTHING"
            ),
            {"n": name},
        )
        conn.commit()
    except Exception as exc:
        logger.warning("[gate] record(%s) primary INSERT/commit failed: %s", name, exc)

    # Verify the row is actually visible. If not, retry through a new
    # engine connection so a rolled-back tx cannot silently drop the row.
    try:
        verify = conn.execute(
            text("SELECT 1 FROM schema_migrations WHERE migration_name = :n"),
            {"n": name},
        ).fetchone()
    except Exception as exc:
        logger.warning("[gate] record(%s) verify SELECT failed: %s", name, exc)
        verify = None

    if verify is not None:
        return

    # Primary path lost the write. Try a fresh engine connection.
    try:
        engine = conn.engine  # SQLAlchemy 2.0 Connection.engine
    except Exception:
        engine = None
    if engine is None:
        logger.error(
            "[gate] record(%s) did not persist and no engine available for retry — "
            "migration WILL re-run next boot",
            name,
        )
        return

    try:
        with engine.begin() as retry_conn:
            retry_conn.execute(
                text(
                    "INSERT INTO schema_migrations (migration_name) VALUES (:n)"
                    " ON CONFLICT (migration_name) DO NOTHING"
                ),
                {"n": name},
            )
        logger.warning(
            "[gate] record(%s) recovered via retry_conn — primary path had rolled back",
            name,
        )
    except Exception as exc:
        logger.error(
            "[gate] record(%s) retry_conn ALSO failed: %s — migration WILL re-run next boot",
            name, exc,
        )


def verify_count(
    conn,
    *,
    name: str,
    sql: str,
    params: dict | None = None,
    expected: int = 0,
    on_mismatch: str = "raise",
) -> int:
    """Run *sql* and assert the row count equals *expected*.

    Args:
        conn:        SQLAlchemy connection.
        name:        Migration name used in log/error messages (e.g. "m045").
        sql:         SQL query whose row count is asserted.
        params:      Optional bind parameters for the query.
        expected:    Expected row count (default 0 — use to assert zero leftovers).
        on_mismatch: "raise" (default) → log CRITICAL then raise RuntimeError.
                     "log_critical" → log CRITICAL only, do not raise.

    Returns:
        The actual row count returned by the query.

    Logs INFO when the count matches; CRITICAL when it does not.
    """
    rows = conn.execute(text(sql), params or {}).fetchall()
    actual = len(rows)

    if actual == expected:
        logger.info(
            "[gate] verify_count %s OK — expected=%d actual=%d",
            name,
            expected,
            actual,
        )
        return actual

    logger.critical(
        "[gate] verify_count %s FAILED — expected=%d actual=%d rows=%s",
        name,
        expected,
        actual,
        [(list(r)) for r in rows[:10]],
    )

    if on_mismatch != "log_critical":
        raise RuntimeError(
            f"verify_count {name}: expected {expected} rows, got {actual}"
        )

    return actual
