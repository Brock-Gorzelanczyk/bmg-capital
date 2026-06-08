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
    ],
    "bot_signals": [
        ("entry_price",          "FLOAT"),
        ("stop_price",           "FLOAT"),
        ("target_price",         "FLOAT"),
        ("discord_posted_at",    "DATETIME"),
        ("discord_message_id",   "TEXT"),
    ],
    "bot_positions": [
        ("stop_price_usd",         "FLOAT"),
        ("target_price_usd",       "FLOAT"),
        ("trailing_stop_activated","BOOLEAN DEFAULT 0"),
        ("trailing_stop_price_usd","FLOAT"),
        ("quarantined_at",         "DATETIME"),
        ("quarantine_reason",      "VARCHAR"),
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
        _retrofit_debug_trade_signals(conn)
        _close_debug_test_trades(conn)
        _dedupe_bot_allocations(conn)
        _close_stale_overnight_positions(conn)
        _delete_test_pod_and_watchlist(conn)
        _reset_consecutive_loss_state(conn)
        _purge_backfill_seed_data(conn)
        _raise_guardrail_position_cap(conn)
        _quarantine_options_seed_trades(conn)
        _seed_quant_watchlists(conn)


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
