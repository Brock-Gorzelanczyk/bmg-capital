"""
Migration m003 — Quant Research Extensions

Idempotent migration that:
1. Adds t_stat, evidence_tier, haircut_pct (default 30), oos_verified columns
   to strategy_meta table.
2. Creates signal_outcomes table if not exists.
3. Seeds evidence_tier for known strategies.
"""
from __future__ import annotations

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)


_EVIDENCE_SEEDS: list[tuple[str, str, int]] = [
    ("small_cap_value",               "weak",        50),
    ("social_sentiment_extreme_fade", "weak",        60),
    ("short_term_reversal_weekly",    "weak",        50),
    ("time_series_momentum_etf",      "very_strong", 30),
    ("quality_score",                 "very_strong", 30),
    ("quality_minus_junk_lite",       "very_strong", 30),
    ("value_momentum_quality_blend",  "very_strong", 30),
]


def run(conn) -> None:
    """Idempotent migration — safe to run multiple times."""

    def _exec(sql: str, params: dict | None = None) -> None:
        if params:
            conn.execute(text(sql), params)
        else:
            conn.execute(text(sql))

    logger.info("[m003] Starting quant research migration")

    # ── 0. Check if strategy_meta table exists (ORM creates it via create_all) ─
    try:
        result = conn.execute(text(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='strategy_meta'"
        ))
        strategy_meta_exists = result.fetchone() is not None
    except Exception:
        # PostgreSQL fallback
        try:
            result = conn.execute(text(
                "SELECT 1 FROM information_schema.tables WHERE table_name='strategy_meta'"
            ))
            strategy_meta_exists = result.fetchone() is not None
        except Exception:
            strategy_meta_exists = False

    if not strategy_meta_exists:
        logger.info("[m003] strategy_meta table not yet created — skipping ALTER/seed steps (ORM will create it fresh)")
        # Still create signal_outcomes and finish
    else:
        logger.info("[m003] strategy_meta table found — running ALTER + seed steps")

    # ── 1. Add columns to strategy_meta (skip if table doesn't exist yet) ──────
    if strategy_meta_exists:
        _alter_ddls = [
            "ALTER TABLE strategy_meta ADD COLUMN t_stat FLOAT",
            "ALTER TABLE strategy_meta ADD COLUMN evidence_tier VARCHAR(20)",
            "ALTER TABLE strategy_meta ADD COLUMN haircut_pct INTEGER NOT NULL DEFAULT 30",
            "ALTER TABLE strategy_meta ADD COLUMN oos_verified INTEGER NOT NULL DEFAULT 0",
        ]
        for ddl in _alter_ddls:
            try:
                _exec(ddl)
                logger.info("[m003] DDL OK: %s", ddl[:60])
            except Exception as exc:
                logger.debug("[m003] DDL skipped (already exists): %s — %s", ddl[:40], exc)
                try:
                    conn.rollback()
                except Exception:
                    pass

    # ── 2. Create signal_outcomes table (split statements for SQLite compat) ──
    _create_stmts = [
        """
        CREATE TABLE IF NOT EXISTS signal_outcomes (
            id              INTEGER PRIMARY KEY,
            signal_id       INTEGER NOT NULL,
            allocation_id   INTEGER NOT NULL,
            symbol          VARCHAR(30) NOT NULL,
            entry_price     FLOAT,
            exit_price      FLOAT,
            entry_ts        TIMESTAMP,
            exit_ts         TIMESTAMP,
            hold_bars       INTEGER,
            pnl_cents       INTEGER,
            pnl_pct         FLOAT,
            regime_at_entry TEXT,
            exit_reason     VARCHAR(50),
            created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_signal_outcomes_signal_id ON signal_outcomes(signal_id)",
        "CREATE INDEX IF NOT EXISTS ix_signal_outcomes_allocation_id ON signal_outcomes(allocation_id)",
        "CREATE INDEX IF NOT EXISTS ix_signal_outcomes_symbol ON signal_outcomes(symbol)",
    ]
    for stmt in _create_stmts:
        try:
            _exec(stmt)
        except Exception as exc:
            logger.warning("[m003] signal_outcomes DDL skipped: %s", exc)
    logger.info("[m003] signal_outcomes table ensured")

    # ── 3. Seed evidence_tier for known strategies (skip if table not ready) ────
    if not strategy_meta_exists:
        logger.info("[m003] Skipping evidence_tier seeds — strategy_meta not created yet")
        logger.info("[m003] Migration complete (partial — re-runs on next boot once ORM creates strategy_meta)")
        return

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
        except Exception as exc:
            logger.warning("[m003] Could not seed evidence_tier for %s: %s", module_name, exc)

    logger.info("[m003] Migration complete")


if __name__ == "__main__":
    import os
    import sys

    logging.basicConfig(level=logging.INFO)
    database_url = os.getenv("DATABASE_URL", f"sqlite:///bmg_capital.db")

    from sqlalchemy import create_engine
    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    with engine.begin() as c:
        run(c)
    print("[m003] Migration applied successfully.")
