"""
Migration m003 — Quant Research Extensions

Idempotent migration that:
1. Adds t_stat, evidence_tier, haircut_pct (default 30), oos_verified columns
   to strategy_meta table.
2. Creates signal_outcomes table if not exists.
3. Seeds evidence_tier for known strategies:
   - WEAK: small_cap_value, social_sentiment_extreme_fade, short_term_reversal_weekly
   - VERY_STRONG: time_series_momentum_etf, quality_score, quality_minus_junk_lite,
                  value_momentum_quality_blend

Run: python -m app.db.migrations.m003_quant_research
or via apply script: python -c "from app.db.migrations.m003_quant_research import run; ..."
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Evidence tier seeds: (module_name, evidence_tier, haircut_pct)
_EVIDENCE_SEEDS: list[tuple[str, str, int]] = [
    # Weak evidence — high haircut
    ("small_cap_value", "weak", 50),
    ("social_sentiment_extreme_fade", "weak", 60),
    ("short_term_reversal_weekly", "weak", 50),
    # Very strong evidence — standard 30% haircut
    ("time_series_momentum_etf", "very_strong", 30),
    ("quality_score", "very_strong", 30),
    ("quality_minus_junk_lite", "very_strong", 30),
    ("value_momentum_quality_blend", "very_strong", 30),
]


def run(conn) -> None:
    """Idempotent migration — safe to run multiple times.

    Args:
        conn: psycopg2 connection OR SQLAlchemy engine/connection.
              Handles both raw psycopg2 and SQLAlchemy text() patterns.
    """
    # Detect connection type and get a cursor-like executor
    _is_sqlalchemy = hasattr(conn, "execute") and hasattr(conn, "dialect")
    _is_sa_conn = hasattr(conn, "execute") and hasattr(conn, "connection")

    def _exec(sql: str, params: dict | None = None) -> None:
        """Execute SQL — works for raw psycopg2 cursor and SQLAlchemy connections."""
        if _is_sqlalchemy or _is_sa_conn:
            from sqlalchemy import text
            if params:
                conn.execute(text(sql), params)
            else:
                conn.execute(text(sql))
        else:
            # Assume raw psycopg2 connection
            cur = conn.cursor()
            try:
                if params:
                    # Convert :name style to %(name)s for psycopg2
                    import re
                    psql = re.sub(r":(\w+)", r"%(\1)s", sql)
                    cur.execute(psql, params)
                else:
                    cur.execute(sql)
            finally:
                cur.close()

    logger.info("[m003] Starting quant research migration")

    # ── 1. Add columns to strategy_meta (idempotent via IF NOT EXISTS) ──────────
    _alter_ddls = [
        "ALTER TABLE strategy_meta ADD COLUMN IF NOT EXISTS t_stat FLOAT",
        "ALTER TABLE strategy_meta ADD COLUMN IF NOT EXISTS evidence_tier VARCHAR(20)",
        "ALTER TABLE strategy_meta ADD COLUMN IF NOT EXISTS haircut_pct INTEGER NOT NULL DEFAULT 30",
        "ALTER TABLE strategy_meta ADD COLUMN IF NOT EXISTS oos_verified BOOLEAN NOT NULL DEFAULT FALSE",
    ]
    for ddl in _alter_ddls:
        try:
            _exec(ddl)
            logger.info("[m003] DDL OK: %s", ddl[:60])
        except Exception as exc:
            # Column may already exist in non-IF-NOT-EXISTS dialects
            logger.warning("[m003] DDL skipped (likely already exists): %s — %s", ddl[:60], exc)
            try:
                conn.rollback()
            except Exception:
                pass

    # ── 2. Create signal_outcomes table ─────────────────────────────────────────
    create_signal_outcomes = """
    CREATE TABLE IF NOT EXISTS signal_outcomes (
        id                SERIAL PRIMARY KEY,
        signal_id         INTEGER NOT NULL REFERENCES bot_signals(id),
        allocation_id     INTEGER NOT NULL REFERENCES bot_allocations(id),
        symbol            VARCHAR(30) NOT NULL,
        entry_price       FLOAT,
        exit_price        FLOAT,
        entry_ts          TIMESTAMP,
        exit_ts           TIMESTAMP,
        hold_bars         INTEGER,
        pnl_cents         INTEGER,
        pnl_pct           FLOAT,
        regime_at_entry   TEXT,
        exit_reason       VARCHAR(50),
        created_at        TIMESTAMP NOT NULL DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS ix_signal_outcomes_signal_id
        ON signal_outcomes(signal_id);
    CREATE INDEX IF NOT EXISTS ix_signal_outcomes_allocation_id
        ON signal_outcomes(allocation_id);
    CREATE INDEX IF NOT EXISTS ix_signal_outcomes_symbol
        ON signal_outcomes(symbol);
    """
    try:
        _exec(create_signal_outcomes)
        logger.info("[m003] signal_outcomes table ensured")
    except Exception as exc:
        logger.error("[m003] Failed to create signal_outcomes: %s", exc)
        raise

    # ── 3. Seed evidence_tier for known strategies ───────────────────────────────
    for module_name, tier, haircut in _EVIDENCE_SEEDS:
        try:
            _exec(
                """
                UPDATE strategy_meta
                SET evidence_tier = :tier,
                    haircut_pct   = :haircut
                WHERE module_name = :module_name
                  AND (evidence_tier IS NULL OR evidence_tier != :tier)
                """,
                {"tier": tier, "haircut": haircut, "module_name": module_name},
            )
            logger.info("[m003] Seeded evidence_tier=%s for %s (haircut=%d%%)", tier, module_name, haircut)
        except Exception as exc:
            logger.warning("[m003] Could not seed evidence_tier for %s: %s", module_name, exc)

    # Commit if psycopg2 connection (SQLAlchemy callers manage their own transactions)
    if not _is_sqlalchemy and not _is_sa_conn:
        try:
            conn.commit()
        except Exception:
            pass

    logger.info("[m003] Migration complete")


if __name__ == "__main__":
    """Run directly: python -m app.db.migrations.m003_quant_research"""
    import os
    import sys

    logging.basicConfig(level=logging.INFO)
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL env var not set", file=sys.stderr)
        sys.exit(1)

    try:
        from sqlalchemy import create_engine
        engine = create_engine(database_url)
        with engine.begin() as conn:
            run(conn)
        print("[m003] Migration applied successfully.")
    except ImportError:
        import psycopg2
        conn = psycopg2.connect(database_url)
        try:
            run(conn)
            conn.commit()
        finally:
            conn.close()
        print("[m003] Migration applied successfully.")
