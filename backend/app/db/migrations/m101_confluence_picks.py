"""m101 — confluence_picks table (Brock 2026-08-20).

Structural component of the confluence stock-selection framework
(research note: research/2026-08-20-confluence-selection-framework.md).

**Purpose:** every time the framework surfaces a pick, log it here with
the specific signals that fired, entry price, target, invalidation,
horizon, and starting SPY price. A weekly cron marks each open pick vs
SPY. After 12 months we have an unfakeable track record of whether the
framework works, rather than a story about whether it works.

**Design constraints (from framework note §Anti-goodhart):**
  1. Signal fields are BOOLEAN or discrete integer — not re-tunable
     later. If we change the framework we log the change separately.
  2. `hit_win_criterion` is fixed at pick time (excess >= +3% vs SPY
     over horizon). Not changeable per-pick.
  3. Every field that affects success measurement locked at entry.
  4. `close_reason` enumerated: 'target', 'invalidation',
     'horizon_reached', 'thesis_broken', 'manual'.
  5. Excess-vs-SPY is the KPI, not absolute return.

**Anti-lookahead:** entry_price + spy_price_cents_at_entry are captured
at pick time via a real quote (not a backfill). close_price + close SPY
similarly captured at close time. No backfilling of "what if I'd bought
at yesterday's close" — the framework must live in real time.

Idempotent (guard by presence of `confluence_picks` table).
"""
from __future__ import annotations

import logging
from sqlalchemy import text

logger = logging.getLogger(__name__)


_MIGRATION_NAME = "m101_confluence_picks_2026_08_20"


def _table_exists(conn, table: str) -> bool:
    row = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:t"),
        {"t": table},
    ).fetchone()
    return row is not None


def _already_ran(conn) -> bool:
    try:
        row = conn.execute(
            text("SELECT 1 FROM schema_migrations WHERE name = :n"),
            {"n": _MIGRATION_NAME},
        ).fetchone()
        return row is not None
    except Exception:
        # schema_migrations table may not exist yet on very fresh DBs
        return False


def run(conn) -> dict:
    """Apply the migration. Returns a status dict for the startup log."""
    if _already_ran(conn):
        return {"status": "skip", "reason": "already_ran"}

    if _table_exists(conn, "confluence_picks"):
        # Table exists (probably from a manual create); record + skip.
        try:
            conn.execute(
                text("INSERT OR IGNORE INTO schema_migrations (name) VALUES (:n)"),
                {"n": _MIGRATION_NAME},
            )
        except Exception:
            pass
        return {"status": "skip", "reason": "table_exists"}

    conn.execute(text("""
        CREATE TABLE confluence_picks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            entry_date TEXT NOT NULL,
            entry_price_cents INTEGER NOT NULL,
            spy_price_cents_at_entry INTEGER NOT NULL,

            -- Signals that fired (locked at entry, never modified)
            insider_cluster INTEGER NOT NULL,      -- REQUIRED = 1
            short_surprise_dir INTEGER,            -- -1, 0, or +1
            analyst_revisions_dir INTEGER,         -- -1, 0, or +1
            fundamental_momentum INTEGER,          -- 0 or 1
            inst_13f_net_add INTEGER,              -- 0 or 1
            signals_fired_count INTEGER NOT NULL,  -- 3, 4, or 5

            -- Thesis (locked at entry)
            thesis_text TEXT NOT NULL,
            target_price_cents INTEGER,
            invalidation_price_cents INTEGER,
            horizon_months INTEGER NOT NULL,

            -- Tracking (updated at close)
            closed_date TEXT,
            closed_price_cents INTEGER,
            spy_price_cents_at_close INTEGER,
            close_reason TEXT,

            -- Computed on close (denormalized for query simplicity)
            absolute_return_pct REAL,
            excess_vs_spy_pct REAL,
            hit_win_criterion INTEGER,

            -- Metadata
            created_by TEXT DEFAULT 'confluence_framework_v1',
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """))

    conn.execute(text(
        "CREATE INDEX idx_confluence_open ON confluence_picks(closed_date) "
        "WHERE closed_date IS NULL"
    ))
    conn.execute(text(
        "CREATE INDEX idx_confluence_entry ON confluence_picks(entry_date)"
    ))
    conn.execute(text(
        "CREATE INDEX idx_confluence_ticker ON confluence_picks(ticker)"
    ))

    # Record migration
    try:
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(name TEXT PRIMARY KEY, applied_at TEXT DEFAULT CURRENT_TIMESTAMP)"
        ))
        conn.execute(
            text("INSERT OR IGNORE INTO schema_migrations (name) VALUES (:n)"),
            {"n": _MIGRATION_NAME},
        )
    except Exception as e:
        logger.warning("[m101] schema_migrations write failed: %s", e)

    return {"status": "ok", "created": "confluence_picks"}
