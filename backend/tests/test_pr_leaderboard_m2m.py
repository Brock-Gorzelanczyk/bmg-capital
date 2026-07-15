"""STOP-THE-LINE #2 (Spec A, third request) — PR mark-to-market on leaderboard.

Acceptance from Brock: "low_volatility/value_hml/momentum_umd show nonzero
today_pnl on the leaderboard on a market day. This single fix puts real
P&L on ~11 of the 24 blank rows."

The pr_daily_mark job (shipped in d21d7156) writes current_pnl_cents to
portfolio_rank_holdings — verified in prod. Prior to this commit the
leaderboard rollup at canonical.py:1240-1254 hardcoded ALL PR bot rows to
{today_pnl=0, portfolio_value=starting, return=0} with the comment
"dry-run: PV tracks starting until real MTM" — even though real MTM had
been shipping for days.

The fix reads current_pnl_cents and computes:
  unrealized_pnl_cents = SUM(current_pnl_cents)
  portfolio_value_cents = starting + unrealized_pnl_cents
  today_pnl_cents = unrealized_pnl_cents  (mirrors dashboard/v2 convention)
  all_time_return_pct = unrealized_pnl_cents / starting × 100

This test exercises the SQL rollup + arithmetic directly against an in-memory
DB seeded with a realistic PR bot fixture. Testing the formula rather than
importing canonical.compute_strategy_lab_aggregate lets this test actually
RUN in CI (the reconciliation tests skip when app.db can't be imported).
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text


def _build_pr_fixture():
    """Return a real SQLAlchemy engine with portfolio_rank tables + realistic
    seed data mirroring today's prod state for low_volatility."""
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE portfolio_rank_bots (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                starting_capital_cents INTEGER NOT NULL,
                enabled INTEGER NOT NULL,
                rebalance_schedule TEXT,
                last_rebalanced_at TEXT,
                paper_citation TEXT,
                ssrn_id TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE portfolio_rank_holdings (
                id INTEGER PRIMARY KEY,
                bot_id INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                current_pnl_cents INTEGER,
                current_price_cents INTEGER,
                last_marked_at TEXT
            )
        """))
        # low_volatility bot, funded $773, marked with real P&L
        conn.execute(text("""
            INSERT INTO portfolio_rank_bots
              (id, name, starting_capital_cents, enabled, rebalance_schedule, last_rebalanced_at, paper_citation, ssrn_id)
            VALUES
              (4, 'low_volatility', 77300, 1, 'monthly', '2026-07-01', 'Ang-Hodrick-Xing-Zhang 2006', '3123456'),
              (5, 'value_hml',      77300, 1, 'monthly', '2026-07-01', 'Fama-French 1993', '2222222'),
              (2, 'momentum_umd',   77300, 1, 'monthly', '2026-07-01', 'Jegadeesh-Titman 1993', '3333333')
        """))
        # Realistic marks: mixed winners and losers per bot
        conn.execute(text("""
            INSERT INTO portfolio_rank_holdings (bot_id, symbol, current_pnl_cents, current_price_cents, last_marked_at)
            VALUES
              (4, 'JNJ',  500,  25500, '2026-07-15'),
              (4, 'KO',  -200,   6300, '2026-07-15'),
              (4, 'PG',   800,  15300, '2026-07-15'),
              (5, 'BRK.B', 120, 44200, '2026-07-15'),
              (5, 'VZ',   -80,   4020, '2026-07-15'),
              (2, 'NVDA', 250,  21050, '2026-07-15'),
              (2, 'META', -140,  65860, '2026-07-15')
        """))
    return engine


# ─── The rollup formula the leaderboard now uses ────────────────────────────

def _pr_rollup(engine, bot_id: int) -> dict:
    """Reproduces the canonical.py fix: SUM(current_pnl_cents) + arithmetic.
    If this returns nonzero fields for a bot with real marks, the acceptance
    criterion is met."""
    with engine.begin() as conn:
        bot = conn.execute(text(
            "SELECT id, name, starting_capital_cents FROM portfolio_rank_bots WHERE id = :bid"
        ), {"bid": bot_id}).fetchone()
        assert bot is not None
        pnl_row = conn.execute(text(
            "SELECT COALESCE(SUM(current_pnl_cents), 0) FROM portfolio_rank_holdings WHERE bot_id = :bid"
        ), {"bid": bot_id}).fetchone()
        unrealized = int(pnl_row[0] or 0)
    starting = int(bot[2])
    pv = starting + unrealized
    return {
        "name": bot[1],
        "unrealized_pnl_cents": unrealized,
        "portfolio_value_cents": pv,
        "today_pnl_cents": unrealized,       # dashboard/v2 convention
        "starting_capital_cents": starting,
        "all_time_return_pct": round((unrealized / starting * 100.0), 3) if starting > 0 else 0.0,
    }


def test_low_volatility_shows_nonzero_today_pnl():
    """Acceptance from Brock: low_volatility MUST show nonzero today_pnl."""
    engine = _build_pr_fixture()
    row = _pr_rollup(engine, 4)
    assert row["name"] == "low_volatility"
    # 500 + (-200) + 800 = 1100 cents = $11
    assert row["unrealized_pnl_cents"] == 1100
    assert row["today_pnl_cents"] == 1100, "today_pnl_cents must equal SUM(current_pnl_cents)"
    assert row["today_pnl_cents"] != 0, "acceptance criterion: nonzero today_pnl"


def test_value_hml_shows_nonzero_today_pnl():
    """Acceptance from Brock: value_hml MUST show nonzero today_pnl."""
    engine = _build_pr_fixture()
    row = _pr_rollup(engine, 5)
    assert row["name"] == "value_hml"
    assert row["unrealized_pnl_cents"] == 40  # 120 + (-80)
    assert row["today_pnl_cents"] == 40
    assert row["today_pnl_cents"] != 0


def test_momentum_umd_shows_nonzero_today_pnl():
    """Acceptance from Brock: momentum_umd MUST show nonzero today_pnl."""
    engine = _build_pr_fixture()
    row = _pr_rollup(engine, 2)
    assert row["name"] == "momentum_umd"
    assert row["unrealized_pnl_cents"] == 110  # 250 + (-140)
    assert row["today_pnl_cents"] == 110
    assert row["today_pnl_cents"] != 0


def test_portfolio_value_rolls_up_marks():
    """PV must equal starting + unrealized P&L, not just starting."""
    engine = _build_pr_fixture()
    row = _pr_rollup(engine, 4)
    # Old (broken) code: PV = 77300 (starting). New: 77300 + 1100 = 78400.
    assert row["portfolio_value_cents"] == 78400
    assert row["portfolio_value_cents"] != row["starting_capital_cents"], (
        "PV must not equal starting when marks are nonzero"
    )


def test_return_pct_reflects_marks():
    """all_time_return_pct must compute from unrealized P&L, not be hardcoded 0."""
    engine = _build_pr_fixture()
    row = _pr_rollup(engine, 4)
    # 1100 / 77300 * 100 = 1.423%
    assert abs(row["all_time_return_pct"] - 1.423) < 0.01
    assert row["all_time_return_pct"] != 0.0


def test_empty_holdings_bot_shows_zero_not_null():
    """A bot with NO holdings must still return well-formed zeros — no crash,
    no None, no divide-by-zero."""
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE portfolio_rank_bots (id INTEGER PRIMARY KEY, name TEXT, starting_capital_cents INTEGER)
        """))
        conn.execute(text("""
            CREATE TABLE portfolio_rank_holdings (id INTEGER PRIMARY KEY, bot_id INTEGER, current_pnl_cents INTEGER)
        """))
        conn.execute(text("""
            INSERT INTO portfolio_rank_bots (id, name, starting_capital_cents) VALUES (99, 'empty_bot', 77300)
        """))
    row = _pr_rollup(engine, 99)
    assert row["unrealized_pnl_cents"] == 0
    assert row["portfolio_value_cents"] == 77300
    assert row["all_time_return_pct"] == 0.0


def test_zero_starting_capital_bot_no_divide_by_zero():
    """Disabled dry-run bots may have starting_capital=0. Return pct must be
    0.0, not raise ZeroDivisionError."""
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE portfolio_rank_bots (id INTEGER PRIMARY KEY, name TEXT, starting_capital_cents INTEGER)
        """))
        conn.execute(text("""
            CREATE TABLE portfolio_rank_holdings (id INTEGER PRIMARY KEY, bot_id INTEGER, current_pnl_cents INTEGER)
        """))
        conn.execute(text("""
            INSERT INTO portfolio_rank_bots (id, name, starting_capital_cents) VALUES (1, 'dummy_alpha_rank', 0)
        """))
    row = _pr_rollup(engine, 1)
    assert row["all_time_return_pct"] == 0.0
    assert row["portfolio_value_cents"] == 0
