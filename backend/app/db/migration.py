from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

_TABLE_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
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
    ],
    "paper_transactions": [
        ("notes",       "VARCHAR"),
        ("asset_class", "VARCHAR"),
    ],
    "paper_orders": [
        ("asset_class", "VARCHAR"),
    ],
    "paper_positions": [
        ("asset_class", "VARCHAR"),
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
        ("paused_reason", "VARCHAR"),
    ],
    "bot_signals": [],
    "bot_positions": [],
    "bot_trades": [
        ("expected_fill_cents", "INTEGER"),
        ("slippage_bps",        "FLOAT"),
    ],
    "bot_daily_pnl": [
        ("peak_drawdown_pct", "FLOAT"),
    ],
    "go_live_waitlist": [],
    "bot_watchlist": [],
    "bot_health": [],
    "regime_snapshots": [],
    "catalyst_events": [],
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
