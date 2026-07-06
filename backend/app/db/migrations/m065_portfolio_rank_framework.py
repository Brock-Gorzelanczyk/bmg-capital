"""m065 — Portfolio-Rank Bot Framework (Phase 1).

Introduces a second bot type to the fleet: portfolio-rank bots. These
rank a universe of stocks by a factor score, hold the top decile long
(and optionally short the bottom decile), and rebalance on a fixed
schedule. This is the operational shape used by classical academic
anomalies (momentum, value, quality, size, low-vol, etc.).

This migration ships the schema plus one hand-seeded dummy bot
(`dummy_alpha_rank`) so we can verify the framework end to end. The
dummy ranks a small S&P 500 subset alphabetically and holds top 10 —
zero economic content; it exists only to validate the plumbing.

Real anomaly bots (momentum_umd, quality_gross_profitability, etc.)
ship in Phase 2 after Phase 1 is green.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.db.migrations._gate import already_ran, record

logger = logging.getLogger(__name__)

_MIGRATION_NAME = "m065_portfolio_rank_framework_2026_07"


_DUMMY_BOT = {
    "name": "dummy_alpha_rank",
    "description": "Framework verification bot. Ranks a hardcoded S&P 500 subset "
                   "alphabetically, holds top 10 equal-weight. No economic content.",
    "factor_definition": {"type": "alphabetical"},
    "universe": {"type": "sp500_partial"},
    "rebalance_schedule": "weekly",
    "long_decile": 10,
    "short_decile": 0,
    "position_sizing": "equal_weight",
    "starting_capital_cents": 0,   # dummy — no real capital allocated
    "enabled": 1,
    "paper_citation": None,
    "ssrn_id": None,
}


def run(conn) -> dict:
    if already_ran(conn, _MIGRATION_NAME):
        return {"skipped_reason": "already_applied", "executed": False}

    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS portfolio_rank_bots (
            id                     INTEGER PRIMARY KEY AUTOINCREMENT,
            name                   VARCHAR(80) UNIQUE NOT NULL,
            description            TEXT,
            factor_definition      TEXT NOT NULL,
            universe               TEXT NOT NULL,
            rebalance_schedule     VARCHAR(20) NOT NULL,
            long_decile            INTEGER NOT NULL DEFAULT 10,
            short_decile           INTEGER NOT NULL DEFAULT 0,
            position_sizing        VARCHAR(20) NOT NULL DEFAULT 'equal_weight',
            starting_capital_cents INTEGER NOT NULL DEFAULT 0,
            enabled                BOOLEAN NOT NULL DEFAULT 0,
            paper_citation         TEXT,
            ssrn_id                VARCHAR(40),
            last_rebalanced_at     TIMESTAMP,
            next_rebalance_at      TIMESTAMP,
            created_at             TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))

    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS portfolio_rank_holdings (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_id             INTEGER NOT NULL,
            symbol             VARCHAR(20) NOT NULL,
            target_weight      FLOAT NOT NULL,
            actual_weight      FLOAT NOT NULL DEFAULT 0.0,
            side               VARCHAR(8) NOT NULL DEFAULT 'long',
            entry_price_cents  INTEGER,
            current_price_cents INTEGER,
            entry_ts           TIMESTAMP,
            last_marked_at     TIMESTAMP,
            current_pnl_cents  INTEGER DEFAULT 0,
            FOREIGN KEY(bot_id) REFERENCES portfolio_rank_bots(id)
        )
    """))
    conn.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_prh_bot_symbol_side "
        "ON portfolio_rank_holdings(bot_id, symbol, side)"
    ))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_prh_bot_id "
        "ON portfolio_rank_holdings(bot_id)"
    ))

    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS portfolio_rank_rebalance_log (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_id             INTEGER NOT NULL,
            triggered_by       VARCHAR(20) NOT NULL,
            ranking_output     TEXT NOT NULL,
            target_basket      TEXT NOT NULL,
            adds               TEXT,
            removes            TEXT,
            latency_ms         INTEGER,
            error              TEXT,
            created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(bot_id) REFERENCES portfolio_rank_bots(id)
        )
    """))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_prrl_bot_id_created "
        "ON portfolio_rank_rebalance_log(bot_id, created_at)"
    ))

    # Seed the dummy bot only if it does not exist.
    existing = conn.execute(text(
        "SELECT id FROM portfolio_rank_bots WHERE name = :n"
    ), {"n": _DUMMY_BOT["name"]}).fetchone()
    if not existing:
        conn.execute(text("""
            INSERT INTO portfolio_rank_bots
              (name, description, factor_definition, universe,
               rebalance_schedule, long_decile, short_decile,
               position_sizing, starting_capital_cents, enabled,
               paper_citation, ssrn_id, created_at)
            VALUES
              (:name, :desc, :fdef, :uni, :sched, :ld, :sd,
               :ps, :cap, :en, :cite, :ssrn, :ts)
        """), {
            "name": _DUMMY_BOT["name"],
            "desc": _DUMMY_BOT["description"],
            "fdef": json.dumps(_DUMMY_BOT["factor_definition"]),
            "uni":  json.dumps(_DUMMY_BOT["universe"]),
            "sched": _DUMMY_BOT["rebalance_schedule"],
            "ld":   _DUMMY_BOT["long_decile"],
            "sd":   _DUMMY_BOT["short_decile"],
            "ps":   _DUMMY_BOT["position_sizing"],
            "cap":  _DUMMY_BOT["starting_capital_cents"],
            "en":   _DUMMY_BOT["enabled"],
            "cite": _DUMMY_BOT["paper_citation"],
            "ssrn": _DUMMY_BOT["ssrn_id"],
            "ts":   datetime.now(timezone.utc).isoformat(),
        })

    record(conn, _MIGRATION_NAME)
    return {
        "executed": True,
        "tables": [
            "portfolio_rank_bots",
            "portfolio_rank_holdings",
            "portfolio_rank_rebalance_log",
        ],
        "dummy_bot_seeded": not bool(existing),
    }
