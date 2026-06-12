from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

_TABLE_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "users": [
        ("is_admin",          "BOOLEAN NOT NULL DEFAULT 0"),
        ("role",              "VARCHAR NOT NULL DEFAULT 'viewer'"),
        ("is_test_account",   "BOOLEAN NOT NULL DEFAULT 0"),
    ],
    "user_tiers": [
        ("billing_interval",       "VARCHAR"),
        ("trial_ends_at",          "DATETIME"),
        ("current_period_end",     "DATETIME"),
        ("stripe_customer_id",     "VARCHAR"),
        ("stripe_subscription_id", "VARCHAR"),
        ("stripe_sub_id",          "VARCHAR"),
        ("aum_override",           "VARCHAR"),
        ("aum_override_until",     "DATETIME"),
        ("cancel_at_period_end",   "BOOLEAN"),
        ("updated_at",             "DATETIME"),
        ("status",                 "VARCHAR NOT NULL DEFAULT 'active'"),
    ],
    "paper_accounts": [
        ("starting_balance", "FLOAT NOT NULL DEFAULT 100000.0"),
    ],
    "paper_transactions": [
        ("notes",       "VARCHAR"),
        ("asset_class", "VARCHAR"),
    ],
    "paper_orders": [
        ("asset_class",        "VARCHAR"),
        ("notional",           "FLOAT"),
        ("stop_price",         "FLOAT"),
        ("take_profit_price",  "FLOAT"),
        ("stop_loss_price",    "FLOAT"),
        ("trailing_amount",    "FLOAT"),
        ("trailing_type",      "VARCHAR"),
        ("tif",                "VARCHAR NOT NULL DEFAULT 'day'"),
        ("extended_hours",     "BOOLEAN DEFAULT 0"),
        ("fill_qty",           "FLOAT"),
        ("slippage",           "FLOAT"),
        ("reject_reason",      "VARCHAR"),
        ("parent_order_id",    "INTEGER"),
        ("cancelled_at",       "DATETIME"),
    ],
    "paper_positions": [
        ("asset_class", "VARCHAR"),
        ("prev_close",  "FLOAT"),
    ],
    "strategy_trades": [
        ("candidate_since",       "DATETIME"),
        ("entry_trigger",         "VARCHAR"),
        ("entry_notes",           "VARCHAR"),
        ("atr",                   "FLOAT"),
        ("risk_dollars",          "FLOAT"),
        ("user_id",               "INTEGER"),
        ("last_known_price",      "FLOAT"),
        ("prev_close",            "FLOAT"),
        ("paper_order_placed",    "BOOLEAN"),
        ("paper_sell_placed",     "BOOLEAN"),
        ("asset_class",           "VARCHAR DEFAULT 'equity'"),
        ("exchange",              "VARCHAR"),
        ("funding_cost_accrued",  "FLOAT DEFAULT 0.0"),
        ("direction",             "VARCHAR DEFAULT 'long'"),
    ],
    "watchlists": [
        ("user_id", "INTEGER"),
    ],
    "portfolios": [
        ("user_id", "INTEGER"),
    ],
    "alert_configs": [
        ("user_id", "INTEGER"),
    ],
    "saved_screens": [
        ("user_id", "INTEGER"),
    ],
    "strategy_daily_log": [
        ("user_id", "INTEGER"),
    ],
    "strategy_equity_snapshots": [
        ("user_id",     "INTEGER"),
        ("asset_class", "VARCHAR DEFAULT 'equity'"),
    ],
    "market_challenge_attempts": [
        ("time_ms", "INTEGER"),
    ],
    "league_cohorts": [
        ("finalized", "BOOLEAN"),
    ],
    "league_points": [
        ("breakdown", "TEXT"),
    ],
    "learn_progress": [
        ("market_challenge_streak",   "INTEGER"),
        ("market_challenges_total",   "INTEGER"),
        ("market_challenges_correct", "INTEGER"),
        ("category_strengths",        "TEXT"),
        ("league_tier",               "VARCHAR"),
        ("freeze_month",              "INTEGER"),
    ],
    "robo_risk_profiles": [
        ("income_bracket",      "VARCHAR"),
        ("savings_rate",        "FLOAT"),
        ("has_emergency_fund",  "BOOLEAN"),
    ],
    "robo_goals": [
        ("notes",           "TEXT"),
        ("probability_pct", "FLOAT"),
    ],
    "robo_core_portfolios": [
        ("direct_index_min_value",  "FLOAT"),
        ("drift_pct",               "FLOAT"),
    ],
    "robo_direct_index": [
        ("estimated_tax_savings", "FLOAT"),
    ],
    "autonomous_actions": [
        ("outcome_value", "FLOAT"),
        ("strategy_id",   "VARCHAR"),
    ],
    "autonomous_guardrails": [
        ("paused_at", "DATETIME"),
    ],
    "autonomous_digests": [
        ("portfolio_delta", "FLOAT"),
    ],
    "autopilot_policies": [
        ("config",      "TEXT"),
        ("created_at",  "DATETIME"),
        ("updated_at",  "DATETIME"),
    ],
    "autopilot_guardrails": [
        ("cash_drain_per_week",               "FLOAT DEFAULT 500.0"),
        ("max_position_concentration_pct",    "FLOAT DEFAULT 15.0"),
        ("max_subscriptions_cancel_per_week", "INTEGER DEFAULT 3"),
        ("paused_at",                         "DATETIME"),
        ("updated_at",                        "DATETIME"),
    ],
    "autopilot_actions": [
        ("asset",          "VARCHAR"),
        ("outcome_value",  "FLOAT"),
    ],
    "playbook_phases": [
        ("phase_number",   "INTEGER"),
        ("name",           "VARCHAR"),
        ("day_start",      "INTEGER"),
        ("day_end",        "INTEGER"),
        ("outcome_target", "TEXT"),
    ],
    "playbook_weeks": [
        ("phase_id",       "INTEGER"),
        ("week_number",    "INTEGER"),
        ("title",          "VARCHAR"),
        ("day_start",      "INTEGER"),
        ("day_end",        "INTEGER"),
        ("outcome_target", "TEXT"),
        ("status",         "VARCHAR DEFAULT 'pending'"),
    ],
    "playbook_tasks": [
        ("week_id",          "INTEGER"),
        ("day_focus",        "VARCHAR"),
        ("title",            "VARCHAR"),
        ("description",      "TEXT"),
        ("effort_hours",     "FLOAT DEFAULT 4.0"),
        ("priority",         "VARCHAR DEFAULT 'P1'"),
        ("status",           "VARCHAR DEFAULT 'pending'"),
        ("completion_note",  "TEXT"),
        ("completed_at",     "DATETIME"),
        ("sort_order",       "INTEGER DEFAULT 0"),
    ],
    "playbook_start": [
        ("started_at", "DATETIME"),
    ],
    "investors": [],
    "content_posts": [],
    "waitlist_signups": [],
    "voice_sessions": [],
    "daily_briefs": [],
    "linked_brokerages": [],
    "external_holdings": [],
    "deposit_matches": [],
    "referral_codes": [],
    "referral_rewards": [],
    "learn_earn_lessons": [],
    "earn_rewards": [],
    "ipo_deals": [],
    "ipo_registrations": [],
    "cfp_bookings": [],
    "staking_positions": [],
    "staking_reward_logs": [],
    "dca_baskets": [],
    "dca_basket_assets": [],
    "bot_profiles": [],
    "bot_allocations": [
        ("paused_reason",                    "VARCHAR"),
        ("starting_capital_cents",           "INT"),
        ("card_config",                      "TEXT"),
        ("portfolio_id",                     "INTEGER"),
        ("capital_cents_within_portfolio",   "INTEGER"),
        ("tier",                             "TEXT NOT NULL DEFAULT 'T0'"),
    ],
    "bot_signals": [
        ("entry_price",          "FLOAT"),
        ("stop_price",           "FLOAT"),
        ("target_price",         "FLOAT"),
        ("discord_posted_at",    "DATETIME"),
        ("discord_message_id",   "TEXT"),
        ("is_test",              "BOOLEAN DEFAULT 0"),
        ("executed_at",          "DATETIME"),
    ],
    "bot_positions": [
        ("stop_price_usd",         "FLOAT"),
        ("target_price_usd",       "FLOAT"),
        ("trailing_stop_activated","BOOLEAN DEFAULT 0"),
        ("trailing_stop_price_usd","FLOAT"),
        ("quarantined_at",         "DATETIME"),
        ("quarantine_reason",      "VARCHAR"),
        ("side",                   "VARCHAR NOT NULL DEFAULT 'long'"),
    ],
    "bot_trades": [
        ("expected_fill_cents", "INTEGER"),
        ("slippage_bps",        "FLOAT"),
        ("quarantined_at",      "DATETIME"),
        ("quarantine_reason",   "VARCHAR"),
    ],
    "bot_daily_pnl": [
        ("peak_drawdown_pct",           "FLOAT"),
        ("portfolio_value_eod_cents",   "INT"),
    ],
    "go_live_waitlist": [],
    "bot_watchlist": [],
    "bot_health": [],
    "regime_snapshots": [],
    "catalyst_events": [],
    "strategy_weights": [],
    "cross_bot_positions": [],
    "news_events": [],
    "anomaly_events": [],
    "strategy_portfolios": [
        ("paper_mode",  "BOOLEAN DEFAULT 1"),
        ("enabled",     "BOOLEAN DEFAULT 1"),
        ("emoji",       "VARCHAR"),
        ("color_hex",   "VARCHAR"),
    ],
    "portfolio_daily_pnl": [],
    "v2_shadow_runs": [],   # created via CREATE TABLE IF NOT EXISTS in _ensure_v2_tables
}


def _ensure_migration_log(conn) -> None:
    """Create the schema_migrations tracking table if it doesn't exist."""
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            migration_name VARCHAR NOT NULL UNIQUE,
            applied_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """))
    conn.commit()


def _migration_already_ran(conn, name: str) -> bool:
    """Return True if this migration has already been applied."""
    try:
        result = conn.execute(
            text("SELECT 1 FROM schema_migrations WHERE migration_name = :n"), {"n": name}
        ).fetchone()
        return result is not None
    except Exception:
        return False


def _record_migration(conn, name: str) -> None:
    """Record a migration as applied."""
    conn.execute(
        text("INSERT OR IGNORE INTO schema_migrations (migration_name) VALUES (:n)"), {"n": name}
    )
    conn.commit()


def _migrate_strategy_portfolios(conn) -> None:
    """One-time data migration: create 3 StrategyPortfolio rows per user and
    assign BotAllocations to their portfolio. Safe to re-run."""
    _DEFS = [
        {"asset_class": "stocks",  "name": "Stocks",  "emoji": "📈", "color": "#A3E635",
         "bots": {"stock_swing": 1_666_700, "stock_day": 1_666_700, "stock_lt": 1_666_600}},
        {"asset_class": "crypto",  "name": "Crypto",  "emoji": "🪙", "color": "#F59E0B",
         "bots": {"crypto_swing": 1_666_700, "crypto_day": 1_666_700, "crypto_lt": 1_666_600}},
        {"asset_class": "options", "name": "Options", "emoji": "⚡", "color": "#8B5CF6",
         "bots": {"options_income": 2_500_000, "options_directional": 2_500_000}},
    ]
    try:
        users = conn.execute(text("SELECT id FROM users")).fetchall()
        for (user_id,) in users:
            for defn in _DEFS:
                # Upsert portfolio row
                existing_portfolio = conn.execute(
                    text("SELECT id FROM strategy_portfolios WHERE user_id=:u AND asset_class=:a"),
                    {"u": user_id, "a": defn["asset_class"]}
                ).fetchone()
                if not existing_portfolio:
                    conn.execute(
                        text("""
                            INSERT INTO strategy_portfolios
                            (user_id, name, asset_class, starting_capital_cents,
                             paper_mode, enabled, emoji, color_hex, created_at)
                            VALUES (:u, :n, :a, 5000000, 1, 1, :e, :c,
                                    datetime('now'))
                        """),
                        {"u": user_id, "n": defn["name"], "a": defn["asset_class"],
                         "e": defn["emoji"], "c": defn["color"]}
                    )
                    conn.commit()
                    existing_portfolio = conn.execute(
                        text("SELECT id FROM strategy_portfolios WHERE user_id=:u AND asset_class=:a"),
                        {"u": user_id, "a": defn["asset_class"]}
                    ).fetchone()

                portfolio_id = existing_portfolio[0]

                # Assign BotAllocations to this portfolio
                for bot_name, capital_cents in defn["bots"].items():
                    conn.execute(
                        text("""
                            UPDATE bot_allocations
                            SET portfolio_id = :pid,
                                capital_cents_within_portfolio = :cap
                            WHERE user_id = :uid
                              AND profile_id = (
                                  SELECT id FROM bot_profiles WHERE name = :bname
                              )
                              AND (portfolio_id IS NULL OR portfolio_id = :pid)
                        """),
                        {"pid": portfolio_id, "cap": capital_cents,
                         "uid": user_id, "bname": bot_name}
                    )
                conn.commit()
    except Exception as exc:
        logger.warning("_migrate_strategy_portfolios: %s", exc)


def _ensure_v2_tables(conn) -> None:
    """Create tables for the v2 LEAN-style runner framework (idempotent)."""
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS v2_shadow_runs (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_id        VARCHAR NOT NULL,
            run_ts        DATETIME DEFAULT CURRENT_TIMESTAMP,
            universe_size INTEGER DEFAULT 0,
            insights_count INTEGER DEFAULT 0,
            targets_count  INTEGER DEFAULT 0,
            orders_count   INTEGER DEFAULT 0,
            shadow_mode    BOOLEAN DEFAULT 1,
            duration_ms    INTEGER DEFAULT 0,
            insights_json  TEXT,
            targets_json   TEXT,
            orders_json    TEXT,
            events_json    TEXT,
            error          TEXT
        )
    """))
    conn.commit()
    logger.info("Migration: v2_shadow_runs table ensured")


def _fix_bots_enabled(conn) -> None:
    """One-time fix: re-enable all bot_allocations that were reset to enabled=0
    by the 3-portfolio split migration, and clear any stale paused_reason so
    the page-load auto-reenable guard doesn't block them.
    Runs once, tracked in schema_migrations."""
    MIGRATION_NAME = "bot_allocations.fix_enabled_reset_2024"
    if _migration_already_ran(conn, MIGRATION_NAME):
        return
    try:
        result = conn.execute(text(
            "UPDATE bot_allocations SET enabled = 1, paused_reason = NULL WHERE enabled = 0"
        ))
        conn.commit()
        _record_migration(conn, MIGRATION_NAME)
        logger.info(f"Migration {MIGRATION_NAME}: re-enabled {result.rowcount} bot_allocation rows")
    except Exception as exc:
        logger.warning(f"Migration {MIGRATION_NAME} failed: {exc}")


def _create_scout_tables(conn) -> None:
    """Create user_scout_setups and user_scout_signals tables for Strategy Scout."""
    MIGRATION_NAME = "strategy_scout.tables_v1_2026_06"
    if _migration_already_ran(conn, MIGRATION_NAME):
        return
    try:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS user_scout_setups (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         INTEGER NOT NULL,
                ticker          TEXT NOT NULL,
                strategy_id     TEXT NOT NULL,
                status          TEXT NOT NULL DEFAULT 'active',
                created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_scanned_at DATETIME,
                last_confidence REAL,
                fired_at        DATETIME,
                UNIQUE(user_id, ticker, strategy_id)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS user_scout_signals (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                setup_id            INTEGER NOT NULL REFERENCES user_scout_setups(id) ON DELETE CASCADE,
                user_id             INTEGER NOT NULL,
                ticker              TEXT NOT NULL,
                strategy_id         TEXT NOT NULL,
                side                TEXT NOT NULL,
                confidence          REAL NOT NULL,
                entry_price         REAL,
                stop_price          REAL,
                target_price        REAL,
                reason              TEXT,
                discord_message_id  TEXT,
                created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_scout_setups_user   ON user_scout_setups(user_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_scout_setups_active ON user_scout_setups(status)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_scout_signals_user  ON user_scout_signals(user_id)"))
        conn.commit()
        _record_migration(conn, MIGRATION_NAME)
        logger.info("Migration: Strategy Scout tables created")
    except Exception as exc:
        logger.warning("_create_scout_tables failed: %s", exc)


def _create_forge_tables(conn) -> None:
    """Create user_forge_bots and user_forge_signals tables for The Forge."""
    MIGRATION_NAME = "strategy_forge.tables_v1_2026_06"
    if _migration_already_ran(conn, MIGRATION_NAME):
        return
    try:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS user_forge_bots (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         INTEGER NOT NULL,
                name            TEXT NOT NULL,
                description     TEXT,
                status          TEXT NOT NULL DEFAULT 'active',
                strategies      TEXT NOT NULL DEFAULT '[]',
                watchlist       TEXT NOT NULL DEFAULT '[]',
                capital_pct     REAL NOT NULL DEFAULT 5.0,
                created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_scanned_at DATETIME,
                last_fired_at   DATETIME
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS user_forge_signals (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                forge_bot_id        INTEGER NOT NULL REFERENCES user_forge_bots(id) ON DELETE CASCADE,
                user_id             INTEGER NOT NULL,
                ticker              TEXT NOT NULL,
                strategy_id         TEXT NOT NULL,
                side                TEXT NOT NULL,
                confidence          REAL NOT NULL,
                entry_price         REAL,
                stop_price          REAL,
                target_price        REAL,
                reason              TEXT,
                discord_message_id  TEXT,
                created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_forge_bots_user   ON user_forge_bots(user_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_forge_bots_active ON user_forge_bots(status)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_forge_signals_bot  ON user_forge_signals(forge_bot_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_forge_signals_user ON user_forge_signals(user_id)"))
        conn.commit()
        _record_migration(conn, MIGRATION_NAME)
        logger.info("Migration: The Forge tables created")
    except Exception as exc:
        logger.warning("_create_forge_tables failed: %s", exc)


def _create_signal_explanations_table(conn) -> None:
    """Create signal_explanations cache table for AI trade explanations."""
    MIGRATION_NAME = "signal_explanations.table_v1_2026_06"
    if _migration_already_ran(conn, MIGRATION_NAME):
        return
    try:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS signal_explanations (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_source   TEXT NOT NULL,
                signal_id       INTEGER NOT NULL,
                explanation     TEXT NOT NULL,
                model_used      TEXT NOT NULL DEFAULT 'claude-haiku-4-5-20251001',
                generated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(signal_source, signal_id)
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_sig_explain_source_id ON signal_explanations(signal_source, signal_id)"))
        conn.commit()
        _record_migration(conn, MIGRATION_NAME)
        logger.info("Migration: signal_explanations table created")
    except Exception as exc:
        logger.warning("_create_signal_explanations_table failed: %s", exc)


def _recreate_sentinel_tables(conn) -> None:
    """Drop and recreate sentinel tables with INTEGER primary keys (BigInteger broke SQLite autoincrement)."""
    MIGRATION_NAME = "sentinel_tables_integer_pk_v1"
    if _migration_already_ran(conn, MIGRATION_NAME):
        return

    for tbl in ("agent_escalations", "agent_fixes", "agent_circuit_breakers", "agent_events"):
        conn.execute(text(f"DROP TABLE IF EXISTS {tbl}"))

    conn.execute(text("""
        CREATE TABLE agent_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id VARCHAR NOT NULL,
            severity VARCHAR NOT NULL,
            category VARCHAR NOT NULL,
            fingerprint VARCHAR NOT NULL,
            payload TEXT NOT NULL DEFAULT '{}',
            state VARCHAR NOT NULL DEFAULT 'open',
            detected_at DATETIME NOT NULL,
            resolved_at DATETIME
        )
    """))
    conn.execute(text("""
        CREATE TABLE agent_fixes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL,
            fixer_agent VARCHAR NOT NULL,
            pr_number INTEGER,
            pr_url TEXT,
            files_changed TEXT,
            diff_summary TEXT,
            llm_model VARCHAR,
            cost_usd NUMERIC,
            status VARCHAR NOT NULL DEFAULT 'pending',
            created_at DATETIME NOT NULL
        )
    """))
    conn.execute(text("""
        CREATE TABLE agent_circuit_breakers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            breaker_type VARCHAR NOT NULL,
            key VARCHAR NOT NULL,
            tripped_at DATETIME NOT NULL,
            resets_at DATETIME NOT NULL,
            reason TEXT
        )
    """))
    conn.execute(text("""
        CREATE TABLE agent_escalations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL,
            paste_ready TEXT NOT NULL,
            sent_to_discord BOOLEAN NOT NULL DEFAULT 0,
            sent_at DATETIME,
            user_action TEXT
        )
    """))

    for idx_sql in (
        "CREATE INDEX IF NOT EXISTS ix_agent_events_agent_id ON agent_events (agent_id)",
        "CREATE INDEX IF NOT EXISTS ix_agent_events_category ON agent_events (category)",
        "CREATE INDEX IF NOT EXISTS ix_agent_events_fingerprint ON agent_events (fingerprint)",
        "CREATE INDEX IF NOT EXISTS ix_agent_events_state ON agent_events (state)",
        "CREATE INDEX IF NOT EXISTS ix_agent_fixes_event_id ON agent_fixes (event_id)",
        "CREATE INDEX IF NOT EXISTS ix_agent_circuit_breakers_breaker_type ON agent_circuit_breakers (breaker_type)",
        "CREATE INDEX IF NOT EXISTS ix_agent_circuit_breakers_key ON agent_circuit_breakers (key)",
        "CREATE INDEX IF NOT EXISTS ix_agent_escalations_event_id ON agent_escalations (event_id)",
    ):
        conn.execute(text(idx_sql))

    conn.commit()
    _record_migration(conn, MIGRATION_NAME)
    logger.info("Migration: recreated sentinel tables with INTEGER primary keys")


def _seed_initial_bot_performance_stats(conn) -> None:
    """Insert a zeroed stats row for every bot_allocation that has no stats yet.

    Runs once at startup so the allocation endpoints return real rows rather
    than empty lists. The nightly compute_bot_stats job will overwrite these
    with real numbers.
    """
    MIGRATION_NAME = "bot_performance_stats.seed_zeroed_rows_v1"
    if _migration_already_ran(conn, MIGRATION_NAME):
        return
    try:
        today = datetime.now(timezone.utc).date().isoformat()
        conn.execute(text("""
            INSERT OR IGNORE INTO bot_performance_stats
                (allocation_id, stat_date, total_return_pct, return_30d_pct, return_7d_pct,
                 win_rate, profit_factor, max_drawdown_pct, sharpe_ratio,
                 total_trades, winning_trades, losing_trades,
                 starting_capital_cents, current_value_cents, realized_pnl_cents)
            SELECT
                ba.id,
                :today,
                0.0, 0.0, 0.0,
                0.0, 0.0, 0.0, 0.0,
                0, 0, 0,
                ba.starting_capital_cents,
                ba.starting_capital_cents,
                0
            FROM bot_allocations ba
            WHERE NOT EXISTS (
                SELECT 1 FROM bot_performance_stats ps WHERE ps.allocation_id = ba.id
            )
        """), {"today": today})
        conn.commit()
        _record_migration(conn, MIGRATION_NAME)
        logger.info("_seed_initial_bot_performance_stats: zeroed rows seeded")
    except Exception as exc:
        logger.warning("_seed_initial_bot_performance_stats: %s", exc)
        conn.rollback()


def _ensure_agent_bus_table(conn) -> None:
    """Create the agent_messages inter-agent message bus table (idempotent)."""
    MIGRATION_NAME = "agent_messages.table_v1_2026_06"
    if _migration_already_ran(conn, MIGRATION_NAME):
        return
    try:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS agent_messages (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                channel      VARCHAR  NOT NULL,
                from_agent   VARCHAR  NOT NULL,
                to_agent     VARCHAR,
                msg_type     VARCHAR  NOT NULL,
                subject      VARCHAR  NOT NULL,
                payload      TEXT     NOT NULL DEFAULT '{}',
                priority     INTEGER  NOT NULL DEFAULT 5,
                reply_to_id  INTEGER,
                read_by      TEXT     NOT NULL DEFAULT '[]',
                created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_agent_msgs_channel ON agent_messages(channel)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_agent_msgs_created ON agent_messages(created_at)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_agent_msgs_to_agent ON agent_messages(to_agent)"
        ))
        conn.commit()
        _record_migration(conn, MIGRATION_NAME)
        logger.info("Migration: agent_messages bus table created")
    except Exception as exc:
        logger.warning("_ensure_agent_bus_table failed: %s", exc)


def _ensure_agent_memory_table(conn) -> None:
    """Create the agent_memory persistent key/value store (idempotent)."""
    MIGRATION_NAME = "agent_memory.table_v1_2026_06"
    if _migration_already_ran(conn, MIGRATION_NAME):
        return
    try:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS agent_memory (
                id          INTEGER  PRIMARY KEY AUTOINCREMENT,
                agent_id    VARCHAR  NOT NULL,
                memory_type VARCHAR  NOT NULL,
                key         VARCHAR  NOT NULL,
                value       TEXT     NOT NULL DEFAULT '{}',
                created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                expires_at  DATETIME
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_agent_memory_agent ON agent_memory(agent_id)"
        ))
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_memory_key "
            "ON agent_memory(agent_id, memory_type, key)"
        ))
        conn.commit()
        _record_migration(conn, MIGRATION_NAME)
        logger.info("Migration: agent_memory table created")
    except Exception as exc:
        logger.warning("_ensure_agent_memory_table failed: %s", exc)


def _ensure_sleeve_config_table(conn) -> None:
    """
    Create sleeve_config table and seed options reservation.
    sleeve_config.reserved_capital_cents holds the capital earmarked for a
    sleeve even when no bots are deployed — used by /fund and portfolio pie.
    """
    MIGRATION_NAME = "sleeve_config.table_v1_2026_06"
    if _migration_already_ran(conn, MIGRATION_NAME):
        return
    try:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS sleeve_config (
                sleeve_name            VARCHAR PRIMARY KEY,
                reserved_capital_cents BIGINT  NOT NULL DEFAULT 0,
                notes                  VARCHAR
            )
        """))
        # Seed: $200k reserved for options bots (not yet deployed)
        conn.execute(text("""
            INSERT OR IGNORE INTO sleeve_config (sleeve_name, reserved_capital_cents, notes)
            VALUES ('options', 20000000, 'Reserved for future options bots: options_short_strangle_45d, options_wheel_mechanical')
        """))
        conn.commit()
        _record_migration(conn, MIGRATION_NAME)
        logger.info("Migration: sleeve_config table created, options reserved=$200k")
    except Exception as exc:
        logger.warning("_ensure_sleeve_config_table failed: %s", exc)


def _ensure_proposal_audit_table(conn) -> None:
    """Create the proposal_audit table for Queen Tier B approval flow (idempotent)."""
    MIGRATION_NAME = "proposal_audit.table_v1_2026_06"
    if _migration_already_ran(conn, MIGRATION_NAME):
        return
    try:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS proposal_audit (
                id                        INTEGER  PRIMARY KEY AUTOINCREMENT,
                proposal_id               VARCHAR  NOT NULL UNIQUE,
                proposal_type             VARCHAR  NOT NULL DEFAULT 'allocation_change',
                generated_ts              DATETIME NOT NULL,
                posted_message_id         VARCHAR,
                posted_channel_id         VARCHAR,
                proposed_change           TEXT     NOT NULL DEFAULT '{}',
                rationale                 TEXT,
                derived_from_finding_ids  TEXT     NOT NULL DEFAULT '[]',
                decision                  VARCHAR  NOT NULL DEFAULT 'pending',
                decision_ts               DATETIME,
                decision_reason           TEXT,
                executed_ts               DATETIME,
                executor_result           TEXT
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_proposal_audit_decision "
            "ON proposal_audit(decision)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_proposal_audit_generated "
            "ON proposal_audit(generated_ts)"
        ))
        conn.commit()
        _record_migration(conn, MIGRATION_NAME)
        logger.info("Migration: proposal_audit table created")
    except Exception as exc:
        logger.warning("_ensure_proposal_audit_table failed: %s", exc)


def _ensure_daily_plan_table(db) -> None:
    """Create the daily_plan table for standup synthesized plans (idempotent)."""
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS daily_plan (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_date DATE NOT NULL UNIQUE,
            plan_json TEXT NOT NULL,
            contributions_json TEXT,
            generated_ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            posted_message_id VARCHAR(30)
        )
    """))
    db.commit()
    logger.info("Migration: daily_plan table ensured")


def run_migrations(engine: Engine) -> None:
    """Add any missing columns to existing tables (safe no-op if already present)."""
    with engine.connect() as conn:
        _ensure_migration_log(conn)

        for table_name, columns in _TABLE_MIGRATIONS.items():
            try:
                existing = {
                    row[1]
                    for row in conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
                }
            except Exception:
                continue
            for col_name, col_type in columns:
                migration_name = f"{table_name}.{col_name}"
                if col_name not in existing and not _migration_already_ran(conn, migration_name):
                    try:
                        conn.execute(
                            text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}")
                        )
                        conn.commit()
                        _record_migration(conn, migration_name)
                        logger.info(f"Migration: added {table_name}.{col_name}")
                    except Exception as e:
                        logger.warning(f"Migration skipped {table_name}.{col_name}: {e}", exc_info=True)
                elif col_name in existing and not _migration_already_ran(conn, migration_name):
                    # Column already exists but wasn't tracked — record it now
                    _record_migration(conn, migration_name)

        _migrate_strategy_portfolios(conn)
        _fix_bots_enabled(conn)
        _ensure_v2_tables(conn)
        _archive_legacy_tables(conn)
        _grant_admin(conn)
        _backfill_user_roles(conn)
        _ensure_test_account(conn)
        _ensure_perk_account(conn)
        _retrofit_debug_trade_signals(conn)
        _close_debug_test_trades(conn)
        _dedupe_bot_allocations(conn)
        _close_stale_overnight_positions(conn)
        _delete_test_pod_and_watchlist(conn)
        _reset_consecutive_loss_state(conn)
        _purge_backfill_seed_data(conn)
        _raise_guardrail_position_cap(conn)
        _quarantine_options_seed_trades(conn)
        _quarantine_all_seed_trades(conn)
        _quarantine_universal_fake_trades(conn)
        _seed_quant_watchlists(conn)
        _add_trade_provenance_trigger(conn)
        _reenable_options_bots(conn)
        _backfill_onchain_starting_capital(conn)
        _fix_quant_bot_capitals(conn)
        _delete_zombie_signals(conn)
        _scrub_ghost_pnl(conn)
        _quarantine_cooldown_dupe_positions(conn)
        _assign_quant_bots_to_crypto_portfolio(conn)
        _seed_all_watchlists_from_yaml(conn)
        _add_bot_signals_cooldown_index(conn)
        try:
            _ensure_bot_config_tables(conn)
        except Exception as _e:
            logger.warning("_ensure_bot_config_tables failed (non-fatal): %s", _e)
        try:
            _create_scout_tables(conn)
        except Exception as _e:
            logger.warning("_create_scout_tables failed (non-fatal): %s", _e)
        try:
            _create_forge_tables(conn)
        except Exception as _e:
            logger.warning("_create_forge_tables failed (non-fatal): %s", _e)
        try:
            _create_signal_explanations_table(conn)
        except Exception as _e:
            logger.warning("_create_signal_explanations_table failed (non-fatal): %s", _e)
        try:
            _recreate_sentinel_tables(conn)
        except Exception as _e:
            logger.warning("_recreate_sentinel_tables failed (non-fatal): %s", _e)
        try:
            _create_allocation_tier_tables(conn)
        except Exception as _e:
            logger.warning("_create_allocation_tier_tables failed (non-fatal): %s", _e)
        try:
            _create_safety_layer_tables(conn)
        except Exception as _e:
            logger.warning("_create_safety_layer_tables failed (non-fatal): %s", _e)
        try:
            _seed_initial_bot_performance_stats(conn)
        except Exception as _e:
            logger.warning("_seed_initial_bot_performance_stats failed (non-fatal): %s", _e)
        try:
            _backfill_admin_lock_paused_reason(conn)
        except Exception as _e:
            logger.warning("_backfill_admin_lock_paused_reason failed (non-fatal): %s", _e)
        try:
            _ensure_candidate_pipeline_tables(conn)
        except Exception as _e:
            logger.warning("_ensure_candidate_pipeline_tables failed (non-fatal): %s", _e)
        try:
            _ensure_regime_history_table(conn)
        except Exception as _e:
            logger.warning("_ensure_regime_history_table failed (non-fatal): %s", _e)
        try:
            _ensure_agent_bus_table(conn)
        except Exception as _e:
            logger.warning("_ensure_agent_bus_table failed (non-fatal): %s", _e)
        try:
            _ensure_agent_memory_table(conn)
        except Exception as _e:
            logger.warning("_ensure_agent_memory_table failed (non-fatal): %s", _e)
        try:
            _ensure_sleeve_config_table(conn)
        except Exception as _e:
            logger.warning("_ensure_sleeve_config_table failed (non-fatal): %s", _e)
        try:
            _ensure_proposal_audit_table(conn)
        except Exception as _e:
            logger.warning("_ensure_proposal_audit_table failed (non-fatal): %s", _e)
        try:
            _ensure_daily_plan_table(conn)
        except Exception as _e:
            logger.warning("_ensure_daily_plan_table failed (non-fatal): %s", _e)
        try:
            _ensure_bot_profiles_halt_columns(conn)
        except Exception as _e:
            logger.warning("_ensure_bot_profiles_halt_columns failed (non-fatal): %s", _e)


def _ensure_bot_profiles_halt_columns(conn) -> None:
    """Add status + reason_paused to bot_profiles for defensive halt executor."""
    for col, typedef in [("status", "VARCHAR(20) DEFAULT 'ACTIVE'"), ("reason_paused", "TEXT")]:
        try:
            conn.execute(text(f"ALTER TABLE bot_profiles ADD COLUMN {col} {typedef}"))
            conn.commit()
        except Exception:
            pass  # column already exists


def _create_safety_layer_tables(conn) -> None:
    """Create trading gate, blackout, and equity snapshot tables."""
    MIGRATION_NAME = "safety_layer_v1"
    if _migration_already_ran(conn, MIGRATION_NAME):
        return
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS trading_gate_state (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            is_open INTEGER NOT NULL DEFAULT 1,
            halt_reason TEXT,
            halted_at TIMESTAMP,
            halted_by TEXT,
            reopened_at TIMESTAMP,
            reopened_by TEXT
        )
    """))
    conn.execute(text(
        "INSERT OR IGNORE INTO trading_gate_state (id, is_open, halt_reason) VALUES (1, 1, NULL)"
    ))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS trading_gate_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event TEXT NOT NULL,
            reason TEXT,
            symbol TEXT,
            bot_id TEXT,
            metadata TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS trading_blackouts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            blackout_type TEXT NOT NULL,
            event_date DATE NOT NULL,
            blackout_start TIMESTAMP NOT NULL,
            blackout_end TIMESTAMP NOT NULL,
            source TEXT,
            notes TEXT,
            UNIQUE(symbol, blackout_type, event_date)
        )
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_blackouts_symbol_dates
            ON trading_blackouts(symbol, blackout_start, blackout_end)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_blackouts_dates
            ON trading_blackouts(blackout_start, blackout_end)
    """))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS portfolio_equity_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            equity_usd REAL NOT NULL,
            cash_usd REAL,
            positions_value_usd REAL
        )
    """))
    conn.commit()
    _record_migration(conn, MIGRATION_NAME)
    logger.info("_create_safety_layer_tables: tables created")


def _create_allocation_tier_tables(conn) -> None:
    """Create bot_performance_stats and bot_tier_history tables if absent."""
    MIGRATION_NAME = "allocation_tier_tables_v1"
    if _migration_already_ran(conn, MIGRATION_NAME):
        return
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS bot_performance_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            allocation_id INTEGER NOT NULL REFERENCES bot_allocations(id) ON DELETE CASCADE,
            stat_date DATE NOT NULL,
            total_return_pct REAL,
            return_30d_pct REAL,
            return_7d_pct REAL,
            win_rate REAL,
            profit_factor REAL,
            max_drawdown_pct REAL,
            sharpe_ratio REAL,
            total_trades INTEGER NOT NULL DEFAULT 0,
            winning_trades INTEGER NOT NULL DEFAULT 0,
            losing_trades INTEGER NOT NULL DEFAULT 0,
            starting_capital_cents INTEGER NOT NULL DEFAULT 0,
            current_value_cents INTEGER NOT NULL DEFAULT 0,
            realized_pnl_cents INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_bot_perf_stats_alloc_date
            ON bot_performance_stats(allocation_id, stat_date)
    """))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS bot_tier_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            allocation_id INTEGER NOT NULL REFERENCES bot_allocations(id) ON DELETE CASCADE,
            changed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            previous_tier TEXT,
            new_tier TEXT NOT NULL,
            reason TEXT,
            triggered_by TEXT NOT NULL DEFAULT 'daily_job',
            return_30d_pct_at_change REAL,
            win_rate_at_change REAL,
            max_drawdown_at_change REAL,
            trade_count_at_change INTEGER NOT NULL DEFAULT 0
        )
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_bot_tier_history_alloc
            ON bot_tier_history(allocation_id, changed_at)
    """))
    conn.commit()
    _record_migration(conn, MIGRATION_NAME)
    logger.info("_create_allocation_tier_tables: tables created")


def _add_bot_signals_cooldown_index(conn) -> None:
    """Add a unique-per-minute index on bot_signals to prevent concurrent-scan duplicates.

    Prevents two simultaneous scan cycles from inserting the same (allocation, symbol, side)
    within the same UTC minute — a last-resort DB-level guard even if the application-level
    cooldown check has a race window.
    """
    MIGRATION_NAME = "bot_signals.cooldown_index_2026"
    if _migration_already_ran(conn, MIGRATION_NAME):
        return
    try:
        # Try Postgres syntax first (date_trunc), fall back to SQLite strftime
        try:
            conn.execute(text("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_bot_signals_cooldown_minute
                ON bot_signals (allocation_id, symbol, side, date_trunc('minute', ts))
            """))
        except Exception:
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_bot_signals_cooldown_minute
                ON bot_signals (allocation_id, symbol, side, ts)
            """))
        conn.commit()
        _record_migration(conn, MIGRATION_NAME)
        logger.info("_add_bot_signals_cooldown_index: index created")
    except Exception as exc:
        logger.warning("_add_bot_signals_cooldown_index failed (non-fatal): %s", exc)


def _ensure_bot_config_tables(conn) -> None:
    """Create bot_config_overrides and bot_config_audit tables if they don't exist."""
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS bot_config_overrides (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_id     TEXT NOT NULL,
            key        TEXT NOT NULL,
            value      TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_by TEXT NOT NULL,
            CONSTRAINT uq_bot_config_overrides_bot_key UNIQUE (bot_id, key)
        )
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_bot_config_overrides_bot
        ON bot_config_overrides (bot_id)
    """))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS bot_config_audit (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_id     TEXT NOT NULL,
            key        TEXT NOT NULL,
            old_value  TEXT,
            new_value  TEXT NOT NULL,
            changed_at TEXT NOT NULL DEFAULT (datetime('now')),
            changed_by TEXT NOT NULL
        )
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_bot_config_audit_bot
        ON bot_config_audit (bot_id)
    """))
    conn.commit()


def _assign_quant_bots_to_crypto_portfolio(conn) -> None:
    """Assign quant bot allocations to each user's Crypto portfolio.

    crypto_quant_* bots were created after _migrate_strategy_portfolios ran and
    have portfolio_id = NULL, so they don't appear on the /portfolio per-bot rows.
    """
    MIGRATION_NAME = "bot_allocations.assign_quant_to_crypto_portfolio_2026"
    if _migration_already_ran(conn, MIGRATION_NAME):
        return
    try:
        crypto_ports = conn.execute(text("""
            SELECT user_id, id FROM strategy_portfolios WHERE asset_class = 'crypto'
        """)).fetchall()

        quant_names = (
            "'crypto_quant_aggressive'",
            "'crypto_quant_scalper'",
            "'crypto_quant_mean_reversion'",
        )
        quant_profiles = conn.execute(text(
            f"SELECT id FROM bot_profiles WHERE name IN ({', '.join(quant_names)})"
        )).fetchall()
        quant_profile_ids = [r[0] for r in quant_profiles]

        updated = 0
        for user_id, portfolio_id in crypto_ports:
            for profile_id in quant_profile_ids:
                r = conn.execute(text("""
                    UPDATE bot_allocations
                       SET portfolio_id = :pid,
                           capital_cents_within_portfolio = COALESCE(starting_capital_cents, 3000000)
                     WHERE user_id = :uid
                       AND profile_id = :prid
                       AND (portfolio_id IS NULL OR portfolio_id != :pid)
                """), {"pid": portfolio_id, "uid": user_id, "prid": profile_id})
                updated += r.rowcount

        conn.commit()
        _record_migration(conn, MIGRATION_NAME)
        logger.info("_assign_quant_bots_to_crypto_portfolio: updated %d rows", updated)
    except Exception as exc:
        logger.warning("_assign_quant_bots_to_crypto_portfolio failed: %s", exc)


def _seed_all_watchlists_from_yaml(conn) -> None:
    """Idempotent: seed bot_watchlist from each YAML profile's universe.symbols.

    Runs every startup — no migration lock. Only seeds profiles that have zero
    watchlist rows so existing watchlists are never overwritten.
    """
    import os
    import glob

    try:
        import yaml as _yaml
    except ImportError:
        logger.warning("_seed_all_watchlists_from_yaml: PyYAML not available")
        return

    profiles_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "strategy_lab", "profiles")
    )
    if not os.path.isdir(profiles_dir):
        logger.warning("_seed_all_watchlists_from_yaml: profiles dir not found: %s", profiles_dir)
        return

    yaml_files = sorted(
        glob.glob(os.path.join(profiles_dir, "*.yaml"))
        + glob.glob(os.path.join(profiles_dir, "*.yml"))
    )

    now_str = datetime.now(timezone.utc).isoformat()
    total_added = 0

    for yaml_path in yaml_files:
        try:
            with open(yaml_path) as fh:
                profile = _yaml.safe_load(fh)
            if not profile:
                continue

            bot_name = profile.get("name")
            if not bot_name:
                continue

            universe = profile.get("universe", {})
            symbols: list = (
                universe.get("symbols", [])
                if isinstance(universe, dict)
                else list(universe or [])
            )
            if not symbols:
                continue

            profile_row = conn.execute(
                text("SELECT id FROM bot_profiles WHERE name = :n"), {"n": bot_name}
            ).fetchone()
            if not profile_row:
                continue

            profile_id = profile_row[0]

            existing = conn.execute(
                text("SELECT COUNT(*) FROM bot_watchlist WHERE profile_id = :pid"),
                {"pid": profile_id},
            ).scalar() or 0
            if existing > 0:
                continue

            for rank, sym in enumerate(symbols, 1):
                score = float(len(symbols) - rank + 1)
                conn.execute(text("""
                    INSERT OR IGNORE INTO bot_watchlist
                        (profile_id, symbol, score, rank, reasons, status,
                         added_at, last_evaluated_at)
                    VALUES
                        (:pid, :sym, :score, :rank,
                         '{"seeded": 1.0}', 'active',
                         :now, :now)
                """), {"pid": profile_id, "sym": sym, "score": score,
                       "rank": rank, "now": now_str})
                total_added += 1

            logger.info(
                "_seed_all_watchlists_from_yaml: seeded %d symbols for %s",
                len(symbols), bot_name,
            )
        except Exception as exc:
            logger.warning(
                "_seed_all_watchlists_from_yaml: error processing %s: %s", yaml_path, exc
            )

    if total_added > 0:
        conn.commit()
        logger.info("_seed_all_watchlists_from_yaml: total %d rows inserted", total_added)


def _archive_legacy_tables(conn) -> None:
    """Rename legacy personal-portfolio and paper-trading tables to *_archived.

    Idempotent — skips tables that don't exist or are already renamed.
    2026-06-06: consolidated to single bot-aggregate portfolio.
    """
    renames = [
        ("portfolios",            "portfolios_archived"),
        ("positions",             "positions_archived"),
        ("paper_accounts",        "paper_accounts_archived"),
        ("paper_positions",       "paper_positions_archived"),
        ("paper_orders",          "paper_orders_archived"),
        ("paper_transactions",    "paper_transactions_archived"),
        ("paper_daily_snapshots", "paper_daily_snapshots_archived"),
    ]
    for src, dst in renames:
        try:
            exists = conn.execute(
                text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:n"),
                {"n": src},
            ).fetchone()
            if not exists:
                continue
            conn.execute(text(f'ALTER TABLE "{src}" RENAME TO "{dst}"'))
            conn.commit()
            logger.info("Archived legacy table: %s → %s", src, dst)
        except Exception as exc:
            logger.warning("archive_legacy_tables: %s → %s failed: %s", src, dst, exc)


def _close_debug_test_trades(conn) -> None:
    """One-time: close the open BotPosition rows from the two forced BTC test trades
    (ids 18 and 19) at the current BTC price so they don't pollute the live baseline.
    Inserts matching sell rows. Sends a Discord note if possible.
    """
    MIGRATION_NAME = "bot_positions.close_debug_btc_test_trades_2026"
    if _migration_already_ran(conn, MIGRATION_NAME):
        return
    try:
        # Find open positions linked to trades 18/19
        rows = conn.execute(
            text("""
                SELECT bp.id, bp.avg_cost_cents, bp.qty, bp.allocation_id
                FROM bot_positions bp
                JOIN bot_trades bt ON bt.position_id = bp.id
                WHERE bt.id IN (18, 19)
                  AND bp.closed_at IS NULL
            """)
        ).fetchall()

        if not rows:
            _record_migration(conn, MIGRATION_NAME)
            return

        # Fetch BTC price from Kraken
        btc_price = 0.0
        try:
            import urllib.request, json as _json
            with urllib.request.urlopen(
                "https://api.kraken.com/0/public/Ticker?pair=XBTUSD", timeout=8
            ) as resp:
                data = _json.loads(resp.read())
                btc_price = float(data["result"]["XXBTZUSD"]["c"][0])
        except Exception as exc:
            logger.warning("_close_debug_test_trades: kraken price failed: %s", exc)
            btc_price = 60_000.0  # last-known fallback

        fill_cents = int(btc_price * 100)
        now_str = "datetime('now')"

        for pos_id, avg_cost_cents, qty, allocation_id in rows:
            realized_cents = int((btc_price - avg_cost_cents / 100.0) * qty * 100)

            # Close position
            conn.execute(
                text(f"""
                    UPDATE bot_positions
                    SET closed_at = {now_str},
                        exit_reason = 'manual_cleanup_test_data'
                    WHERE id = :pid
                """),
                {"pid": pos_id},
            )

            # Insert sell trade
            conn.execute(
                text("""
                    INSERT INTO bot_trades
                    (allocation_id, symbol, side, qty, fill_price_cents,
                     fees_cents, ts, position_id, is_paper, expected_fill_cents, slippage_bps)
                    VALUES
                    (:alloc, 'BTC/USD', 'sell', :qty, :fp,
                     0, datetime('now'), :pid, 1, :fp, 0.0)
                """),
                {"alloc": allocation_id, "qty": qty, "fp": fill_cents, "pid": pos_id},
            )

            # Update daily P&L
            conn.execute(
                text("""
                    INSERT INTO bot_daily_pnl (allocation_id, date, realized_cents, unrealized_cents, fees_cents)
                    VALUES (:alloc, date('now'), :pnl, 0, 0)
                    ON CONFLICT(allocation_id, date)
                    DO UPDATE SET realized_cents = realized_cents + :pnl
                """),
                {"alloc": allocation_id, "pnl": realized_cents},
            )

        conn.commit()
        _record_migration(conn, MIGRATION_NAME)
        logger.info(
            "_close_debug_test_trades: closed %d position(s) @ BTC=%.2f",
            len(rows), btc_price,
        )

        # Notify Discord
        try:
            import urllib.request as _req
            import json as _json, os as _os
            webhook = _os.getenv("DISCORD_SIGNAL_WEBHOOK_URL", "")
            if webhook:
                msg = {
                    "content": (
                        f"🧹 **TEST TRADES CLOSED** — clearing baseline before live signals start\n"
                        f"Closed {len(rows)} BTC/USD test position(s) @ ${btc_price:,.2f}\n"
                        f"Real crypto bot signals take over from here."
                    )
                }
                data = _json.dumps(msg).encode()
                _req.urlopen(
                    _req.Request(webhook, data=data, headers={"Content-Type": "application/json"}),
                    timeout=5,
                )
        except Exception:
            pass

    except Exception as exc:
        logger.warning("_close_debug_test_trades failed: %s", exc)


def _retrofit_debug_trade_signals(conn) -> None:
    """One-time: set stop_price/target_price on bot_signals matched to the 2 BTC
    test trades (id 18 and 19) using crypto_swing profile rules (-15% / +30%).
    Also backfills stop_price_usd/target_price_usd on their bot_positions.
    Safe to re-run (idempotent via schema_migrations)."""
    MIGRATION_NAME = "bot_signals.retrofit_debug_btc_stop_target"
    if _migration_already_ran(conn, MIGRATION_NAME):
        return
    try:
        for trade_id in (18, 19):
            row = conn.execute(
                text("SELECT fill_price_cents, position_id, ts FROM bot_trades WHERE id = :tid"),
                {"tid": trade_id},
            ).fetchone()
            if not row:
                continue
            fill_cents, position_id, trade_ts = row
            entry = fill_cents / 100.0
            stop = round(entry * 0.85, 4)
            target = round(entry * 1.30, 4)

            # Update matching signal (within ±10 min)
            conn.execute(
                text("""
                    UPDATE bot_signals
                    SET stop_price = :stop, target_price = :target, entry_price = :entry
                    WHERE symbol = 'BTC/USD'
                      AND stop_price IS NULL
                      AND ts BETWEEN datetime(:ts, '-10 minutes')
                                 AND datetime(:ts, '+10 minutes')
                """),
                {"stop": stop, "target": target, "entry": entry,
                 "ts": trade_ts.isoformat() if hasattr(trade_ts, "isoformat") else str(trade_ts)},
            )

            # Backfill position stop/target
            if position_id:
                conn.execute(
                    text("""
                        UPDATE bot_positions
                        SET stop_price_usd = :stop, target_price_usd = :target
                        WHERE id = :pid AND stop_price_usd IS NULL
                    """),
                    {"stop": stop, "target": target, "pid": position_id},
                )
        conn.commit()
        _record_migration(conn, MIGRATION_NAME)
        logger.info("Migration %s: retrofitted BTC test trade stop/target levels", MIGRATION_NAME)
    except Exception as exc:
        logger.warning("_retrofit_debug_trade_signals failed: %s", exc)


def _dedupe_bot_allocations(conn) -> None:
    """One-time: delete duplicate bot_allocations rows where (user_id, profile_id) appears
    more than once. Keeps the row with the lowest id (oldest), reassigns its portfolio_id
    to the first portfolio that matches the allocation's profile's asset_class if needed,
    then drops the extras. Also adds a UNIQUE index to prevent recurrence.
    """
    MIGRATION_NAME = "bot_allocations.dedupe_user_profile_2026"
    if _migration_already_ran(conn, MIGRATION_NAME):
        return
    try:
        # Find duplicates: (user_id, profile_id) groups with more than one row
        dupes = conn.execute(text("""
            SELECT user_id, profile_id, COUNT(*) as cnt, MIN(id) as keep_id
            FROM bot_allocations
            GROUP BY user_id, profile_id
            HAVING cnt > 1
        """)).fetchall()

        deleted = 0
        for row in dupes:
            user_id, profile_id, cnt, keep_id = row
            # Delete all rows for this pair EXCEPT the one to keep
            result = conn.execute(
                text("""
                    DELETE FROM bot_allocations
                    WHERE user_id = :uid AND profile_id = :pid AND id != :keep
                """),
                {"uid": user_id, "pid": profile_id, "keep": keep_id},
            )
            deleted += result.rowcount
            logger.info(
                "dedupe_bot_allocations: kept id=%d, deleted %d duplicate(s) for user=%d profile=%d",
                keep_id, result.rowcount, user_id, profile_id,
            )

        # Add UNIQUE index to prevent future duplicates (CREATE UNIQUE INDEX IF NOT EXISTS)
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS
            idx_bot_allocations_user_profile
            ON bot_allocations(user_id, profile_id)
        """))
        conn.commit()
        _record_migration(conn, MIGRATION_NAME)
        logger.info("dedupe_bot_allocations: removed %d duplicate rows, UNIQUE index ensured", deleted)
    except Exception as exc:
        logger.warning("_dedupe_bot_allocations failed: %s", exc)


_ADMIN_EMAIL = "32bgorzelanczyk@gmail.com"


def _grant_admin(conn) -> None:
    """Idempotent: ensure the designated admin email has is_admin=1."""
    try:
        row = conn.execute(
            text("SELECT id, email, is_admin FROM users WHERE email = :email"),
            {"email": _ADMIN_EMAIL},
        ).fetchone()
        if row is None:
            logger.info("grant_admin: user %s not found yet — will set on first login", _ADMIN_EMAIL)
            return
        if row[2]:  # already admin
            return
        conn.execute(
            text("UPDATE users SET is_admin = 1 WHERE email = :email"),
            {"email": _ADMIN_EMAIL},
        )
        conn.commit()
        logger.info("grant_admin: %s (id=%s) promoted to admin", _ADMIN_EMAIL, row[0])
    except Exception as exc:
        logger.warning("grant_admin failed: %s", exc)


def _backfill_user_roles(conn) -> None:
    """One-shot: set role='admin' for is_admin users, role='viewer' for everyone else."""
    MIGRATION_NAME = "users.role_backfill_2026"
    if _migration_already_ran(conn, MIGRATION_NAME):
        return
    try:
        conn.execute(text("UPDATE users SET role = 'admin' WHERE is_admin = 1"))
        conn.execute(text("UPDATE users SET role = 'viewer' WHERE is_admin = 0 OR is_admin IS NULL"))
        conn.commit()
        _record_migration(conn, MIGRATION_NAME)
        logger.info("_backfill_user_roles: roles assigned")
    except Exception as exc:
        logger.warning("_backfill_user_roles failed: %s", exc)


_TEST_EMAIL = "test@bmgcapital.app"
_TEST_USERNAME = "test"


def _ensure_test_account(conn) -> None:
    """Idempotent: create the hardcoded test/test viewer account for demos.

    Password validation (length, complexity) is only enforced on the signup
    endpoint — not here and not at login. The bcrypt hash is computed once
    and stored directly. The account is flagged is_test_account=1 so it can
    be excluded from analytics / multi-tenancy migrations later.
    """
    MIGRATION_NAME = "users.test_account_2026"
    if _migration_already_ran(conn, MIGRATION_NAME):
        return
    try:
        import bcrypt as _bcrypt
        hashed = _bcrypt.hashpw(b"test", _bcrypt.gensalt()).decode()

        existing = conn.execute(
            text("SELECT id FROM users WHERE email = :email OR username = :uname"),
            {"email": _TEST_EMAIL, "uname": _TEST_USERNAME},
        ).fetchone()

        if existing:
            # Account already exists (e.g. created manually) — just flag it
            conn.execute(
                text("""
                    UPDATE users
                    SET is_test_account = 1, role = 'viewer', is_admin = 0
                    WHERE email = :email OR username = :uname
                """),
                {"email": _TEST_EMAIL, "uname": _TEST_USERNAME},
            )
        else:
            conn.execute(
                text("""
                    INSERT INTO users
                        (email, username, hashed_password, role, is_admin,
                         is_active, is_test_account, created_at)
                    VALUES
                        (:email, :uname, :pw, 'viewer', 0, 1, 1, :now)
                """),
                {
                    "email": _TEST_EMAIL,
                    "uname": _TEST_USERNAME,
                    "pw": hashed,
                    "now": datetime.now(timezone.utc).isoformat(),
                },
            )

        conn.commit()
        _record_migration(conn, MIGRATION_NAME)
        logger.info("_ensure_test_account: test/test viewer account ready")
    except Exception as exc:
        logger.warning("_ensure_test_account failed: %s", exc)


def _ensure_perk_account(conn) -> None:
    """Idempotent: create the perk/perk viewer account for easy demo access."""
    MIGRATION_NAME = "users.perk_account_2026"
    if _migration_already_ran(conn, MIGRATION_NAME):
        return
    try:
        import bcrypt as _bcrypt
        hashed = _bcrypt.hashpw(b"perk", _bcrypt.gensalt()).decode()

        existing = conn.execute(
            text("SELECT id FROM users WHERE email = :email OR username = :uname"),
            {"email": "perk@bmgcapital.app", "uname": "perk"},
        ).fetchone()

        if existing:
            conn.execute(
                text("""
                    UPDATE users
                    SET is_test_account = 1, role = 'viewer', is_admin = 0,
                        hashed_password = :pw
                    WHERE email = :email OR username = :uname
                """),
                {"email": "perk@bmgcapital.app", "uname": "perk", "pw": hashed},
            )
        else:
            conn.execute(
                text("""
                    INSERT INTO users
                        (email, username, hashed_password, role, is_admin,
                         is_active, is_test_account, created_at)
                    VALUES
                        (:email, :uname, :pw, 'viewer', 0, 1, 1, :now)
                """),
                {
                    "email": "perk@bmgcapital.app",
                    "uname": "perk",
                    "pw": hashed,
                    "now": datetime.now(timezone.utc).isoformat(),
                },
            )

        conn.commit()
        _record_migration(conn, MIGRATION_NAME)
        logger.info("_ensure_perk_account: perk/perk viewer account ready")
    except Exception as exc:
        logger.warning("_ensure_perk_account failed: %s", exc)


def _close_stale_overnight_positions(conn) -> None:
    """Close any bot_position rows open longer than hold_max_hours for their profile.

    Targets crypto_day (hold_max_hours=8) positions older than 24h.
    Uses yfinance for current price fallback.
    One-shot tracked; safe to re-run (position already closed = no-op).
    """
    MIGRATION_NAME = "close_stale_overnight_positions_2026_06"
    if _migration_already_ran(conn, MIGRATION_NAME):
        return
    try:
        now = datetime.now(timezone.utc)
        cutoff_24h_ago = now.replace(tzinfo=None) - __import__("datetime").timedelta(hours=24)

        stale_rows = conn.execute(text("""
            SELECT bp.id, bp.symbol, bp.qty, bp.avg_cost_cents, bp.opened_at, bp.allocation_id
            FROM bot_positions bp
            JOIN bot_allocations ba ON bp.allocation_id = ba.id
            JOIN bot_profiles bpr ON ba.profile_id = bpr.id
            WHERE bpr.name = 'crypto_day'
              AND bp.closed_at IS NULL
              AND bp.opened_at < :cutoff
        """), {"cutoff": cutoff_24h_ago.isoformat()}).fetchall()

        if not stale_rows:
            _record_migration(conn, MIGRATION_NAME)
            return

        # Fetch current prices via Kraken (crypto) — intentionally not yfinance,
        # which returned stale $1,596 for ETH when the real price was ~$2,500.
        current_prices: dict = {}
        try:
            from app.services.live_prices import fetch_live_prices
            symbols_needed = list({r[1] for r in stale_rows})
            current_prices = fetch_live_prices(symbols_needed)
        except Exception as exc:
            logger.warning("_close_stale_overnight_positions: live_prices failed: %s", exc)

        for pos_id, symbol, qty, avg_cost_cents, opened_at, alloc_id in stale_rows:
            price = current_prices.get(symbol, avg_cost_cents / 100.0)
            fill_cents = int(price * 100)
            close_ts = now.isoformat()

            # Create exit trade
            conn.execute(text("""
                INSERT INTO bot_trades
                    (allocation_id, symbol, side, qty, fill_price_cents, fees_cents,
                     ts, position_id, is_paper, expected_fill_cents, slippage_bps)
                VALUES
                    (:alloc, :sym, 'sell', :qty, :fill, 0,
                     :ts, :pos_id, 1, :fill, 0.0)
            """), {
                "alloc": alloc_id, "sym": symbol, "qty": qty, "fill": fill_cents,
                "ts": close_ts, "pos_id": pos_id,
            })

            # Close the position
            conn.execute(text("""
                UPDATE bot_positions
                SET closed_at = :ts, exit_reason = 'manual_cleanup_stale_overnight'
                WHERE id = :pos_id
            """), {"ts": close_ts, "pos_id": pos_id})

            pnl = (price - avg_cost_cents / 100.0) * qty
            logger.info(
                "_close_stale_overnight_positions: closed pos %d %s qty=%.4f @ %.4f pnl=%.2f",
                pos_id, symbol, qty, price, pnl,
            )

        conn.commit()
        _record_migration(conn, MIGRATION_NAME)
        logger.info("_close_stale_overnight_positions: closed %d stale position(s)", len(stale_rows))
    except Exception as exc:
        logger.warning("_close_stale_overnight_positions failed: %s", exc)


def _delete_test_pod_and_watchlist(conn) -> None:
    """Remove the 'Test' pod and 'Test' watchlist created during dev testing."""
    MIGRATION_NAME = "delete_test_pod_and_watchlist_2026_06"
    if _migration_already_ran(conn, MIGRATION_NAME):
        return
    try:
        # Delete watchlist items first (FK), then the watchlist
        conn.execute(text("""
            DELETE FROM watchlist_items
            WHERE watchlist_id IN (
                SELECT id FROM watchlists WHERE LOWER(name) = 'test'
            )
        """))
        conn.execute(text("DELETE FROM watchlists WHERE LOWER(name) = 'test'"))

        # Pods: first check table exists
        try:
            conn.execute(text("""
                DELETE FROM pods WHERE LOWER(name) = 'test'
            """))
        except Exception:
            pass  # pods table may not exist in all envs

        conn.commit()
        _record_migration(conn, MIGRATION_NAME)
        logger.info("_delete_test_pod_and_watchlist: test data cleaned up")
    except Exception as exc:
        logger.warning("_delete_test_pod_and_watchlist failed: %s", exc)


def _reset_consecutive_loss_state(conn) -> None:
    """Clear stale consecutive_loss_count from autopilot guardrails (pre-reset data)."""
    MIGRATION_NAME = "reset_consecutive_loss_state_2026_06"
    if _migration_already_ran(conn, MIGRATION_NAME):
        return
    try:
        # Reset consecutive loss counter in autopilot guardrails if the table exists
        try:
            conn.execute(text("""
                UPDATE autopilot_guardrails
                SET consecutive_losses = 0
                WHERE consecutive_losses > 0
            """))
        except Exception:
            pass

        # Also clear bot_health entries with consecutive_loss alerts
        try:
            conn.execute(text("""
                UPDATE bot_health
                SET consecutive_losses = 0
                WHERE consecutive_losses > 0
            """))
        except Exception:
            pass

        conn.commit()
        _record_migration(conn, MIGRATION_NAME)
        logger.info("_reset_consecutive_loss_state: reset stale loss counters")
    except Exception as exc:
        logger.warning("_reset_consecutive_loss_state failed: %s", exc)


def _purge_backfill_seed_data(conn) -> None:
    """One-time: delete all backfill-seeded bot history before today so we start
    fresh with only real live data.

    Deletes:
      - bot_trades with ts < today (seeded by scripts/backfill_bot_data.py)
      - bot_positions with opened_at < today (seeded fake open positions)
      - bot_signals with ts < today (seeded fake signals)
      - bot_daily_pnl rows with date < today (seeded fake P&L history)

    Today's rows (ts >= date('now')) are kept so any real scan-cycle data
    from earlier today is preserved.
    """
    MIGRATION_NAME = "purge_backfill_seed_data_2026_06_06"
    if _migration_already_ran(conn, MIGRATION_NAME):
        return
    try:
        # Count before
        trades_before = conn.execute(
            text("SELECT COUNT(*) FROM bot_trades WHERE ts < date('now')")
        ).scalar() or 0
        positions_before = conn.execute(
            text("SELECT COUNT(*) FROM bot_positions WHERE opened_at < date('now')")
        ).scalar() or 0
        signals_before = conn.execute(
            text("SELECT COUNT(*) FROM bot_signals WHERE ts < date('now')")
        ).scalar() or 0
        pnl_before = conn.execute(
            text("SELECT COUNT(*) FROM bot_daily_pnl WHERE date < date('now')")
        ).scalar() or 0

        # Purge
        conn.execute(text("DELETE FROM bot_trades WHERE ts < date('now')"))
        conn.execute(text("DELETE FROM bot_positions WHERE opened_at < date('now')"))
        conn.execute(text("DELETE FROM bot_signals WHERE ts < date('now')"))
        conn.execute(text("DELETE FROM bot_daily_pnl WHERE date < date('now')"))

        # Reset any allocations where capital_cents_within_portfolio drifted
        # from starting_capital_cents due to fake P&L accumulation
        try:
            conn.execute(text("""
                UPDATE bot_allocations
                SET capital_cents_within_portfolio = starting_capital_cents
                WHERE starting_capital_cents IS NOT NULL
                  AND capital_cents_within_portfolio IS NOT NULL
                  AND capital_cents_within_portfolio != starting_capital_cents
            """))
        except Exception:
            pass  # column may not exist in all envs

        conn.commit()
        _record_migration(conn, MIGRATION_NAME)
        logger.info(
            "_purge_backfill_seed_data: deleted trades=%d positions=%d signals=%d pnl_rows=%d",
            trades_before, positions_before, signals_before, pnl_before,
        )
    except Exception as exc:
        logger.warning("_purge_backfill_seed_data failed: %s", exc)


def _quarantine_options_seed_trades(conn) -> None:
    """Quarantine the seeded options bot trades and mark both options allocations as coming_soon.

    These trades were inserted manually (not via the signal path):
      - microsecond-identical timestamps
      - null alpaca_order_id
      - stale prices (NVDA $884 pre-split, GOOGL $162 from 2024)
    They pollute portfolio totals and should not be visible until real
    options strategies are implemented.
    """
    MIGRATION_NAME = "quarantine_options_seed_trades_2026_06"
    if _migration_already_ran(conn, MIGRATION_NAME):
        return
    try:
        now = datetime.now(timezone.utc).isoformat()

        # Quarantine trades: options bots only, alpaca_order_id IS NULL
        conn.execute(text("""
            UPDATE bot_trades
            SET quarantined_at = :now,
                quarantine_reason = 'seed_data_no_signal_no_scheduler'
            WHERE allocation_id IN (
                SELECT ba.id
                FROM bot_allocations ba
                JOIN bot_profiles bp ON ba.profile_id = bp.id
                WHERE bp.name IN ('options_income', 'options_directional')
            )
            AND alpaca_order_id IS NULL
        """), {"now": now})

        # Quarantine any lingering open positions for these bots
        conn.execute(text("""
            UPDATE bot_positions
            SET quarantined_at = :now
            WHERE allocation_id IN (
                SELECT ba.id
                FROM bot_allocations ba
                JOIN bot_profiles bp ON ba.profile_id = bp.id
                WHERE bp.name IN ('options_income', 'options_directional')
            )
            AND closed_at IS NULL
        """), {"now": now})

        # Mark both options allocations as coming_soon
        conn.execute(text("""
            UPDATE bot_allocations
            SET enabled = 0,
                paused_reason = 'coming_soon',
                updated_at = :now
            WHERE profile_id IN (
                SELECT id FROM bot_profiles
                WHERE name IN ('options_income', 'options_directional')
            )
        """), {"now": now})

        conn.commit()
        _record_migration(conn, MIGRATION_NAME)
        logger.info("_quarantine_options_seed_trades: quarantined seed trades + marked options bots coming_soon")
    except Exception as exc:
        logger.warning("_quarantine_options_seed_trades failed: %s", exc)


def _quarantine_all_seed_trades(conn) -> None:
    """Quarantine ALL seeded positions/trades with the microsecond batch fingerprint.

    The seed script created positions across multiple bots at exactly
    2026-06-08 14:00:00.001484 UTC. _quarantine_options_seed_trades handled
    the options bots, but a META position slipped through on stock_day.
    This catches any remaining rows across ALL bots using the timestamp fingerprint.

    Condition: opened/ts matches '2026-06-08*14:00:00.*' (sub-second precision
    at exactly 14:00:00 on that date) + not already quarantined.
    For bot_trades: also requires alpaca_order_id IS NULL (can't be a real fill).
    """
    MIGRATION_NAME = "quarantine_all_seed_trades_microsecond_2026_06_08"
    if _migration_already_ran(conn, MIGRATION_NAME):
        return
    try:
        now = datetime.now(timezone.utc).isoformat()

        r_pos = conn.execute(text("""
            UPDATE bot_positions
            SET quarantined_at = :now,
                quarantine_reason = 'seed_data_microsecond_batch_2026_06_08'
            WHERE CAST(opened_at AS TEXT) LIKE '%2026-06-08%14:00:00.%'
              AND closed_at IS NULL
              AND quarantined_at IS NULL
        """), {"now": now})

        r_tr = conn.execute(text("""
            UPDATE bot_trades
            SET quarantined_at = :now,
                quarantine_reason = 'seed_data_microsecond_batch_2026_06_08'
            WHERE CAST(ts AS TEXT) LIKE '%2026-06-08%14:00:00.%'
              AND alpaca_order_id IS NULL
              AND quarantined_at IS NULL
        """), {"now": now})

        conn.commit()
        _record_migration(conn, MIGRATION_NAME)
        logger.info(
            "_quarantine_all_seed_trades: quarantined %d positions, %d trades",
            r_pos.rowcount, r_tr.rowcount,
        )
    except Exception as exc:
        logger.warning("_quarantine_all_seed_trades failed: %s", exc)


def _quarantine_universal_fake_trades(conn) -> None:
    """Quarantine ALL trades that never went through Alpaca and ALL open positions
    that have no real Alpaca-backed entry trade.

    Rationale: every real scanner entry trade sets alpaca_order_id (from the Alpaca
    paper-trading API response). Rows without it are either:
      (a) backfill/seed data inserted by scripts, or
      (b) position_monitor exit trades (which do have position_id set).
    Since (b) can only exist if (a) real entry trades exist first, and since the
    user has confirmed zero real Alpaca-order trades exist in the DB today, this
    migration safely wipes all synthetic data in one pass.

    This migration runs ONCE (tracked). Future position_monitor exit trades
    inserted after this date are clean and will not be touched.
    """
    MIGRATION_NAME = "quarantine_universal_fake_trades_2026_06_08"
    if _migration_already_ran(conn, MIGRATION_NAME):
        return
    try:
        now = datetime.now(timezone.utc).isoformat()

        # Quarantine ALL trades with no Alpaca order (catches every backfill batch)
        r_tr = conn.execute(text("""
            UPDATE bot_trades
            SET quarantined_at = :now,
                quarantine_reason = 'synthetic_no_alpaca_order'
            WHERE alpaca_order_id IS NULL
              AND quarantined_at IS NULL
        """), {"now": now})

        # Quarantine ALL open positions that have no real (Alpaca-order) entry trade
        r_pos = conn.execute(text("""
            UPDATE bot_positions
            SET quarantined_at = :now,
                quarantine_reason = 'synthetic_no_alpaca_entry_trade'
            WHERE closed_at IS NULL
              AND quarantined_at IS NULL
              AND id NOT IN (
                SELECT DISTINCT position_id FROM bot_trades
                WHERE alpaca_order_id IS NOT NULL AND position_id IS NOT NULL
              )
        """), {"now": now})

        conn.commit()
        _record_migration(conn, MIGRATION_NAME)
        logger.info(
            "_quarantine_universal_fake_trades: quarantined %d trades, %d positions",
            r_tr.rowcount, r_pos.rowcount,
        )
    except Exception as exc:
        logger.warning("_quarantine_universal_fake_trades failed: %s", exc)


def _add_trade_provenance_trigger(conn) -> None:
    """Add a SQLite trigger that rejects bot_trade inserts with no provenance.

    A valid insert must have at least one of:
      - alpaca_order_id  (real Alpaca fill — scanner entry trades)
      - position_id      (exit trade from position_monitor)
      - quarantined_at   (explicitly marked synthetic before insert — allowed for
                          migrations that need to backfill quarantined rows)

    This blocks accidental seed-script inserts that provide none of these.
    Idempotent — CREATE TRIGGER IF NOT EXISTS.
    """
    MIGRATION_NAME = "bot_trades_provenance_trigger_2026_06"
    if _migration_already_ran(conn, MIGRATION_NAME):
        return
    try:
        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS bot_trades_require_provenance
            BEFORE INSERT ON bot_trades
            FOR EACH ROW
            WHEN NEW.alpaca_order_id IS NULL
              AND NEW.position_id    IS NULL
              AND NEW.quarantined_at IS NULL
            BEGIN
              SELECT RAISE(ABORT,
                'bot_trades: insert rejected — alpaca_order_id or position_id required');
            END
        """))
        conn.commit()
        _record_migration(conn, MIGRATION_NAME)
        logger.info("_add_trade_provenance_trigger: trigger created")
    except Exception as exc:
        logger.warning("_add_trade_provenance_trigger failed: %s", exc)


def _seed_quant_watchlists(conn) -> None:
    """Seed bot_watchlist entries for crypto_quant_aggressive and crypto_onchain
    for all profiles where zero rows exist.

    These bots were added after the initial watchlist seeding round; existing
    deployments have empty watchlists which causes the 502 crash and blocks trading.
    Idempotent — skips profiles that already have rows.
    """
    MIGRATION_NAME = "bot_watchlist.seed_quant_onchain_2026_06"
    if _migration_already_ran(conn, MIGRATION_NAME):
        return
    try:
        _UNIVERSES = {
            "crypto_quant_aggressive": [
                "BTC/USD", "ETH/USD", "SOL/USD", "BNB/USD", "XRP/USD",
                "ADA/USD", "AVAX/USD", "POL/USD", "DOT/USD", "LINK/USD",
                "ATOM/USD", "NEAR/USD", "ARB/USD", "OP/USD", "INJ/USD",
                "SUI/USD", "APT/USD", "TIA/USD", "DOGE/USD", "SHIB/USD",
            ],
            "crypto_onchain": [
                "BTC/USD", "ETH/USD", "SOL/USD", "MATIC/USD", "LINK/USD",
                "DOT/USD", "ATOM/USD", "AVAX/USD",
            ],
        }

        now_str = datetime.now(timezone.utc).isoformat()
        total_added = 0

        for bot_name, symbols in _UNIVERSES.items():
            profile_row = conn.execute(
                text("SELECT id FROM bot_profiles WHERE name = :n"), {"n": bot_name}
            ).fetchone()
            if not profile_row:
                logger.warning("_seed_quant_watchlists: profile %s not found", bot_name)
                continue
            profile_id = profile_row[0]

            existing_count = conn.execute(
                text("SELECT COUNT(*) FROM bot_watchlist WHERE profile_id = :pid"),
                {"pid": profile_id},
            ).scalar() or 0
            if existing_count > 0:
                continue  # already seeded

            for rank, sym in enumerate(symbols, 1):
                score = float(len(symbols) - rank + 1)
                conn.execute(text("""
                    INSERT OR IGNORE INTO bot_watchlist
                        (profile_id, symbol, score, rank, reasons, status,
                         added_at, last_evaluated_at)
                    VALUES
                        (:pid, :sym, :score, :rank,
                         '{"seeded": 1.0}', 'active',
                         :now, :now)
                """), {
                    "pid": profile_id, "sym": sym,
                    "score": score, "rank": rank, "now": now_str,
                })
                total_added += 1

        conn.commit()
        _record_migration(conn, MIGRATION_NAME)
        logger.info("_seed_quant_watchlists: inserted %d rows", total_added)
    except Exception as exc:
        logger.warning("_seed_quant_watchlists failed: %s", exc)


def _raise_guardrail_position_cap(conn) -> None:
    """Bump max_open_positions to 50 for any existing guardrail rows still at the old default (20).

    This unblocks bot signal generation for users who hit the cap due to
    paper-trading positions being counted by mistake in the previous version
    of guardrail_checker.py.
    """
    MIGRATION_NAME = "raise_guardrail_position_cap_50"
    if _migration_already_ran(conn, MIGRATION_NAME):
        return
    try:
        conn.execute(text(
            "UPDATE autonomous_guardrails SET max_open_positions = 50 "
            "WHERE max_open_positions <= 20"
        ))
        conn.commit()
        _record_migration(conn, MIGRATION_NAME)
        logger.info("_raise_guardrail_position_cap: bumped existing rows to 50")
    except Exception as exc:
        logger.warning("_raise_guardrail_position_cap failed: %s", exc)


def _reenable_options_bots(conn) -> None:
    """Re-enable options_directional and options_income allocations that were
    incorrectly disabled with paused_reason='coming_soon'.

    All options strategy files exist and the runner handles them — they were
    only paused due to an overly cautious gate added on 2026-06-08.
    """
    MIGRATION_NAME = "reenable_options_bots_coming_soon"
    if _migration_already_ran(conn, MIGRATION_NAME):
        return
    try:
        result = conn.execute(text(
            """
            UPDATE bot_allocations
               SET enabled = 1,
                   paused_reason = NULL
             WHERE paused_reason = 'coming_soon'
               AND profile_id IN (
                 SELECT id FROM bot_profiles
                  WHERE name IN ('options_income', 'options_directional')
               )
            """
        ))
        conn.commit()
        _record_migration(conn, MIGRATION_NAME)
        logger.info("_reenable_options_bots: updated %d rows", result.rowcount)
    except Exception as exc:
        logger.warning("_reenable_options_bots failed: %s", exc)


def _backfill_onchain_starting_capital(conn) -> None:
    """Set starting_capital_cents = 10_000_000 for any enabled allocation where it is NULL.

    crypto_onchain was seeded without a starting_capital_cents value, causing
    portfolio_value_cents = 0 on every card render.
    """
    MIGRATION_NAME = "backfill_null_starting_capital_10k"
    if _migration_already_ran(conn, MIGRATION_NAME):
        return
    try:
        result = conn.execute(text(
            """
            UPDATE bot_allocations
               SET starting_capital_cents = 10000000
             WHERE starting_capital_cents IS NULL
               AND profile_id IN (SELECT id FROM bot_profiles WHERE enabled = 1)
            """
        ))
        conn.commit()
        _record_migration(conn, MIGRATION_NAME)
        logger.info("_backfill_onchain_starting_capital: updated %d rows", result.rowcount)
    except Exception as exc:
        logger.warning("_backfill_onchain_starting_capital failed: %s", exc)


def _fix_quant_bot_capitals(conn) -> None:
    """Set correct starting_capital_cents for the three quant bots (40/30/30 split = $100k).

    Phase 2 deploy created crypto_quant_scalper and crypto_quant_mean_reversion with
    NULL starting_capital_cents (seeded after _backfill_onchain_starting_capital ran).
    crypto_quant_aggressive was also still at $100k instead of the spec's $40k.
    Also seeds bot_health rows so /health endpoints don't 500 before first scan.
    """
    MIGRATION_NAME = "fix_quant_bot_capitals_40_30_30_split"
    if _migration_already_ran(conn, MIGRATION_NAME):
        return
    try:
        # 1. crypto_quant_scalper → $30k
        # 2. crypto_quant_mean_reversion → $30k
        conn.execute(text(
            """
            UPDATE bot_allocations
               SET starting_capital_cents = 3000000
             WHERE profile_id IN (
               SELECT id FROM bot_profiles
                WHERE name IN ('crypto_quant_scalper', 'crypto_quant_mean_reversion')
             )
            """
        ))

        # 3. crypto_quant_aggressive → $40k (was $100k default)
        conn.execute(text(
            """
            UPDATE bot_allocations
               SET starting_capital_cents = 4000000
             WHERE profile_id IN (
               SELECT id FROM bot_profiles
                WHERE name = 'crypto_quant_aggressive'
             )
            """
        ))

        # 4. Seed bot_health rows for new bots so /health doesn't 500 before first scan
        conn.execute(text(
            """
            INSERT INTO bot_health (allocation_id, date, heartbeat_ok, paused_by_health)
            SELECT a.id, CURRENT_TIMESTAMP, 1, 0
              FROM bot_allocations a
              JOIN bot_profiles p ON p.id = a.profile_id
             WHERE p.name IN ('crypto_quant_scalper', 'crypto_quant_mean_reversion')
               AND NOT EXISTS (
                 SELECT 1 FROM bot_health bh WHERE bh.allocation_id = a.id
               )
            """
        ))

        conn.commit()
        _record_migration(conn, MIGRATION_NAME)
        logger.info("_fix_quant_bot_capitals: 40/30/30 split applied, bot_health rows seeded")
    except Exception as exc:
        logger.warning("_fix_quant_bot_capitals failed: %s", exc)


def _delete_zombie_signals(conn) -> None:
    """Delete bot_signals that have no entry_price — these were synthetic seed signals
    that never represented a real scanner trigger and cannot be executed.
    """
    MIGRATION_NAME = "delete_zombie_signals_no_entry_price"
    if _migration_already_ran(conn, MIGRATION_NAME):
        return
    try:
        result = conn.execute(text(
            "DELETE FROM bot_signals WHERE entry_price IS NULL"
        ))
        conn.commit()
        _record_migration(conn, MIGRATION_NAME)
        logger.info("_delete_zombie_signals: deleted %d rows", result.rowcount)
    except Exception as exc:
        logger.warning("_delete_zombie_signals failed: %s", exc)


def _scrub_ghost_pnl(conn) -> None:
    """Scrub any P&L residue from trades that escaped the universal quarantine.

    The -$2.70 crypto ghost comes from exit/close trades whose position_id points
    to a quarantined position — canonical.py still sums them because the trade
    row itself was not quarantined (position_monitor exits have position_id set,
    which exempted them from _quarantine_universal_fake_trades).

    Also clears bot_daily_pnl rows from before the quarantine date so the
    daily P&L history starts clean.
    """
    MIGRATION_NAME = "scrub_ghost_pnl_quarantined_position_exits_2026_06"
    if _migration_already_ran(conn, MIGRATION_NAME):
        return
    try:
        now = datetime.now(timezone.utc).isoformat()

        # Quarantine any exit trade whose position was itself quarantined
        r_exits = conn.execute(text("""
            UPDATE bot_trades
               SET quarantined_at   = :now,
                   quarantine_reason = 'exit_of_quarantined_position'
             WHERE quarantined_at IS NULL
               AND position_id IS NOT NULL
               AND position_id IN (
                 SELECT id FROM bot_positions WHERE quarantined_at IS NOT NULL
               )
        """), {"now": now})

        # Quarantine any remaining sell/close trade with no alpaca_order_id
        # (catches position_monitor exits that fired on synthetic positions)
        r_synth = conn.execute(text("""
            UPDATE bot_trades
               SET quarantined_at   = :now,
                   quarantine_reason = 'synthetic_exit_no_alpaca_order'
             WHERE quarantined_at IS NULL
               AND alpaca_order_id IS NULL
               AND LOWER(side) IN ('sell', 'close', 'short')
        """), {"now": now})

        # Clear stale daily P&L rows from before quarantine date
        r_dpnl = conn.execute(text(
            "DELETE FROM bot_daily_pnl WHERE date < '2026-06-08'"
        ))

        conn.commit()
        _record_migration(conn, MIGRATION_NAME)
        logger.info(
            "_scrub_ghost_pnl: quarantined %d exit trades, %d synthetic sells, "
            "deleted %d stale daily_pnl rows",
            r_exits.rowcount, r_synth.rowcount, r_dpnl.rowcount,
        )
    except Exception as exc:
        logger.warning("_scrub_ghost_pnl failed: %s", exc)


def _quarantine_cooldown_dupe_positions(conn) -> None:
    """Quarantine duplicate open positions opened within 60 s of each other.

    The cooldown bug (pre-2026-06-09) allowed multiple strategies in a single
    scan to each open the same (symbol, avg_cost, qty) position. Keep the
    lowest id in each dupe cluster; quarantine the rest.
    """
    MIGRATION_NAME = "bot_positions.quarantine_cooldown_dupes_2026_06"
    if _migration_already_ran(conn, MIGRATION_NAME):
        return
    try:
        rows = conn.execute(text("""
            SELECT id, allocation_id, symbol, avg_cost_cents, qty, opened_at
            FROM bot_positions
            WHERE closed_at IS NULL
              AND quarantined_at IS NULL
            ORDER BY allocation_id, symbol, id
        """)).fetchall()

        from collections import defaultdict
        groups: dict = defaultdict(list)
        for row in rows:
            key = (row[1], row[2])  # allocation_id, symbol
            groups[key].append({
                "id": row[0],
                "avg_cost_cents": row[3] or 0,
                "qty": row[4] or 0,
                "opened_at": row[5],
            })

        def _ts(s) -> int:
            if not s:
                return 0
            try:
                from datetime import datetime as _dt
                if isinstance(s, _dt):
                    return int(s.timestamp())
                return int(_dt.fromisoformat(str(s).replace("Z", "+00:00")).timestamp())
            except Exception:
                return 0

        to_quarantine: list[int] = []
        for positions in groups.values():
            if len(positions) < 2:
                continue
            # Sort by id — earliest is the keeper
            sorted_pos = sorted(positions, key=lambda x: x["id"])
            keeper = sorted_pos[0]
            keeper_ts = _ts(keeper["opened_at"])
            for pos in sorted_pos[1:]:
                same_cost = abs(pos["avg_cost_cents"] - keeper["avg_cost_cents"]) <= 1
                same_qty = abs(pos["qty"] - keeper["qty"]) < 0.0001
                within_60s = abs(_ts(pos["opened_at"]) - keeper_ts) <= 60
                if same_cost and same_qty and within_60s:
                    to_quarantine.append(pos["id"])

        now = datetime.now(timezone.utc).isoformat()
        for pos_id in to_quarantine:
            conn.execute(text("""
                UPDATE bot_positions
                SET quarantined_at = :now,
                    quarantine_reason = 'cooldown_dupe_merged'
                WHERE id = :id
            """), {"now": now, "id": pos_id})

        if to_quarantine:
            conn.commit()
            logger.warning(
                "_quarantine_cooldown_dupe_positions: quarantined %d duplicate positions",
                len(to_quarantine),
            )
        else:
            logger.info("_quarantine_cooldown_dupe_positions: no duplicates found")

        _record_migration(conn, MIGRATION_NAME)
    except Exception as exc:
        logger.warning("_quarantine_cooldown_dupe_positions failed: %s", exc)


def _backfill_admin_lock_paused_reason(conn) -> None:
    """Set paused_reason='admin_lock' on allocations disabled before the paused_reason
    sync was added. Without this, _ensure_portfolios_for_user's auto-re-enable guard
    (which skips rows where paused_reason IN {'health_halt','admin_lock'}) would keep
    re-enabling admin-disabled bots on every portfolio load.
    """
    MIGRATION_NAME = "backfill_admin_lock_paused_reason_2026_06"
    if _migration_already_ran(conn, MIGRATION_NAME):
        return
    try:
        result = conn.execute(text("""
            UPDATE bot_allocations
            SET paused_reason = 'admin_lock'
            WHERE enabled = 0
              AND (paused_reason IS NULL OR paused_reason = '')
        """))
        conn.commit()
        _record_migration(conn, MIGRATION_NAME)
        logger.info("_backfill_admin_lock_paused_reason: updated %d rows", result.rowcount)
    except Exception as exc:
        logger.warning("_backfill_admin_lock_paused_reason failed: %s", exc)


def _ensure_candidate_pipeline_tables(conn) -> None:
    """Create shadow_trades table for candidate paper-trading in SHADOW_PAPER state."""
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS shadow_trades (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_name   TEXT NOT NULL,
            symbol           TEXT NOT NULL,
            side             TEXT NOT NULL,
            confidence       REAL,
            entry_price      REAL,
            exit_price       REAL,
            size_hint        REAL,
            pnl_pct          REAL,
            reason           TEXT,
            strategy         TEXT,
            regime_at_entry  TEXT,
            opened_at        TIMESTAMP NOT NULL DEFAULT (datetime('now')),
            closed_at        TIMESTAMP
        )
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_shadow_trades_candidate
        ON shadow_trades (candidate_name)
    """))
    conn.commit()


def _ensure_regime_history_table(conn) -> None:
    """Create regime_snapshots table for daily regime persistence."""
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS regime_snapshots (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_date    DATE NOT NULL UNIQUE,
            regime           TEXT NOT NULL,
            raw_regime       TEXT,
            confidence       REAL,
            vix_level        REAL,
            spx_vs_200ma     REAL,
            hy_spread_proxy  REAL,
            vix_ts_slope     REAL,
            signals_json     TEXT,
            created_at       TIMESTAMP NOT NULL DEFAULT (datetime('now'))
        )
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_regime_snapshots_date
        ON regime_snapshots (snapshot_date)
    """))
    conn.commit()
