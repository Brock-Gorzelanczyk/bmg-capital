"""Shared SQLite handle + schema init for BMG Capital research track-record layer.

Per BMG's new mandate (2026-09-10): the platform is a research operation.
The product is published research calls with documented reasoning and honest
outcomes. This module owns the storage for that product.

Design rules non-negotiable — see `README.md` in this directory. Summary:
  1. Every outcome is benchmark-relative.
  2. Thesis attribution is a separate field from outcome.
  3. Kill-criteria compliance is tracked separately from performance.

Anti-pattern: NEVER compute Sharpe / t-stat / information ratio / any
significance test on this data. With small N those numbers mislead.
Report counts and honest descriptions. "3 of 5" not "60%".
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "track_record.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS research_calls (
    call_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    note_id TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('BUY', 'SELL', 'HOLD')),
    published_at TEXT NOT NULL,
    price_at_pub REAL NOT NULL,
    price_target REAL,
    horizon_months INTEGER NOT NULL,
    thesis TEXT NOT NULL,
    benchmark TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN (
        'OPEN', 'CLOSED_TARGET', 'CLOSED_KILL',
        'CLOSED_HORIZON', 'CLOSED_MANUAL'
    )) DEFAULT 'OPEN',
    closed_at TEXT,
    closed_price REAL,
    closed_reason TEXT,
    thesis_attribution TEXT CHECK (
        thesis_attribution IS NULL OR
        thesis_attribution IN ('THESIS_CORRECT', 'RIGHT_WRONG_REASON', 'WRONG', 'UNRESOLVED')
    ),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_calls_status ON research_calls(status);
CREATE INDEX IF NOT EXISTS idx_calls_ticker ON research_calls(ticker);

CREATE TABLE IF NOT EXISTS kill_criteria (
    criterion_id INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id INTEGER NOT NULL REFERENCES research_calls(call_id) ON DELETE CASCADE,
    description TEXT NOT NULL,
    metric TEXT,
    threshold TEXT,
    action TEXT NOT NULL CHECK (action IN ('TRIM_HALF', 'EXIT', 'REASSESS')),
    status TEXT NOT NULL CHECK (status IN ('ARMED', 'FIRED', 'EXPIRED')) DEFAULT 'ARMED',
    fired_at TEXT,
    obeyed INTEGER
);
CREATE INDEX IF NOT EXISTS idx_kill_call ON kill_criteria(call_id);
CREATE INDEX IF NOT EXISTS idx_kill_status ON kill_criteria(status);

-- Daily price snapshot for every OPEN call and every benchmark it references.
-- The daily job populates this. call_outcomes is a computed view over it.
CREATE TABLE IF NOT EXISTS daily_prices (
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    close_price REAL NOT NULL,
    source TEXT NOT NULL,
    PRIMARY KEY (ticker, date)
);

-- Computed outcomes are a VIEW, not a table. Do not persist derived data
-- that can drift from source. Recomputed on every query.
CREATE VIEW IF NOT EXISTS call_outcomes AS
WITH latest AS (
    SELECT ticker, MAX(date) AS d FROM daily_prices GROUP BY ticker
),
current_prices AS (
    SELECT dp.ticker, dp.close_price
    FROM daily_prices dp
    JOIN latest l ON dp.ticker = l.ticker AND dp.date = l.d
),
bench_start AS (
    SELECT c.call_id, dp.close_price AS bench_at_pub
    FROM research_calls c
    LEFT JOIN daily_prices dp
        ON dp.ticker = c.benchmark AND dp.date = c.published_at
),
bench_current AS (
    SELECT c.call_id, dp.close_price AS bench_now
    FROM research_calls c
    LEFT JOIN current_prices dp ON dp.ticker = c.benchmark
),
ticker_current AS (
    SELECT c.call_id, dp.close_price AS px_now
    FROM research_calls c
    LEFT JOIN current_prices dp ON dp.ticker = c.ticker
)
SELECT
    c.call_id,
    c.ticker,
    c.direction,
    c.status,
    c.published_at,
    c.price_at_pub,
    COALESCE(c.closed_price, tc.px_now) AS price_now,
    (COALESCE(c.closed_price, tc.px_now) - c.price_at_pub) / c.price_at_pub * 100.0 AS return_since_pub_pct,
    bs.bench_at_pub,
    bc.bench_now,
    CASE
        WHEN bs.bench_at_pub IS NULL OR bc.bench_now IS NULL THEN NULL
        ELSE (bc.bench_now - bs.bench_at_pub) / bs.bench_at_pub * 100.0
    END AS benchmark_return_pct,
    CASE
        WHEN bs.bench_at_pub IS NULL OR bc.bench_now IS NULL OR tc.px_now IS NULL THEN NULL
        ELSE ((COALESCE(c.closed_price, tc.px_now) - c.price_at_pub) / c.price_at_pub -
              (bc.bench_now - bs.bench_at_pub) / bs.bench_at_pub) * 100.0
    END AS excess_return_pct,
    CAST(julianday(COALESCE(c.closed_at, date('now'))) - julianday(c.published_at) AS INTEGER) AS days_held,
    CASE
        WHEN c.price_target IS NOT NULL AND c.direction = 'BUY'
             AND COALESCE(c.closed_price, tc.px_now) >= c.price_target THEN 1
        WHEN c.price_target IS NOT NULL AND c.direction = 'SELL'
             AND COALESCE(c.closed_price, tc.px_now) <= c.price_target THEN 1
        ELSE 0
    END AS target_hit
FROM research_calls c
LEFT JOIN ticker_current tc ON tc.call_id = c.call_id
LEFT JOIN bench_start bs ON bs.call_id = c.call_id
LEFT JOIN bench_current bc ON bc.call_id = c.call_id;
"""


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


if __name__ == "__main__":
    conn = get_conn()
    tables = conn.execute(
        "SELECT type, name FROM sqlite_master WHERE type IN ('table','view') "
        "AND name NOT LIKE 'sqlite_%' ORDER BY type, name"
    ).fetchall()
    print(f"DB at {DB_PATH}")
    for t, n in tables:
        print(f"  {t}: {n}")
    conn.close()
