"""m093 — Create smart_money_13f_holdings + cusip_symbol_cache tables.

The smart_money_13f PR factor (m092) reads from a `smart_money_13f_holdings`
table populated by the app.services.edgar_13f ingest job (shipped
alongside this migration). This migration creates the tables.

Two tables:
  smart_money_13f_holdings — one row per (fund, quarter, cusip). Aggregate
    shares_held across all filings from a given fund for that quarter.
    Symbol is denormalized in via cusip lookup so the factor's ranking
    query is simple.
  cusip_symbol_cache — CUSIP → ticker mapping cache. Populated on-demand
    from openfigi.com API (free, no key, 100 req/min). Rows never expire
    (CUSIPs are effectively immutable after listing).

Idempotent via CREATE TABLE IF NOT EXISTS + _gate.record().
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.db.migrations._gate import already_ran, record

logger = logging.getLogger(__name__)

_MIGRATION_NAME = "m093_smart_money_13f_tables_2026_07_12"


def run(conn) -> dict:
    if already_ran(conn, _MIGRATION_NAME):
        return {"skipped_reason": "already_applied", "executed": False}

    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS smart_money_13f_holdings (
            id SERIAL PRIMARY KEY,
            fund_cik TEXT NOT NULL,
            fund_name TEXT,
            quarter DATE NOT NULL,
            cusip TEXT,
            symbol TEXT,
            shares_held BIGINT NOT NULL DEFAULT 0,
            market_value_cents BIGINT,
            filed_at TIMESTAMPTZ,
            ingested_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (fund_cik, quarter, cusip)
        )
    """))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_13f_symbol_quarter "
        "ON smart_money_13f_holdings (symbol, quarter)"
    ))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_13f_fund_quarter "
        "ON smart_money_13f_holdings (fund_cik, quarter)"
    ))

    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS cusip_symbol_cache (
            cusip TEXT PRIMARY KEY,
            symbol TEXT,
            name TEXT,
            resolved_at TIMESTAMPTZ DEFAULT NOW(),
            source TEXT  -- 'openfigi' | 'static' | 'edgar'
        )
    """))

    if hasattr(conn, "commit"):
        conn.commit()

    logger.warning("[m093] tables created (smart_money_13f_holdings + cusip_symbol_cache)")
    record(conn, _MIGRATION_NAME)
    return {"executed": True}
