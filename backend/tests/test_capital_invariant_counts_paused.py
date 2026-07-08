"""Regression test for the watchdog: capital invariant must count paused SPEC bots.

2026-06-29 incident: PR #10 mega-ship m033 migration paused options_income +
options_directional (Layer 3 stop emitting equity signals). The watchdog's
SQL filtered by `enabled = 1`, so the paused bots' $100K capital dropped
out of the sum → drift = -$100K → CRIT alert (false positive — capital is
still allocated to those bots, just not actively trading).

This test enforces the corrected behavior: capital is capital, paused or not.
The watchdog only excludes m021 merged-dupe rows (paused_reason starts with
`merged_into_`), which are zombie rows the dedup migration left for
reversibility.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool


REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_capital_invariant():
    """Load capital_invariant.py without triggering conftest's app.services stub."""
    ci_path = REPO_ROOT / "backend" / "app" / "services" / "capital_invariant.py"
    spec = importlib.util.spec_from_file_location(
        "app.services.capital_invariant", str(ci_path)
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["app.services.capital_invariant"] = mod
    spec.loader.exec_module(mod)
    return mod


def _make_db_with_13_spec_bots():
    """In-memory SQLite seeded with the 13 m027 SPEC bots at canonical amounts."""
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with eng.connect() as c:
        c.execute(text("""
            CREATE TABLE bot_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL
            )
        """))
        c.execute(text("""
            CREATE TABLE bot_allocations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                profile_id INTEGER NOT NULL,
                enabled INTEGER DEFAULT 1,
                paused_reason TEXT,
                starting_capital_cents INTEGER
            )
        """))
        # 13 SPEC bots per m027 ALLOCATIONS_CENTS, sums to $1M exactly
        spec = {
            "stock_swing":                  11_000_000,
            "stock_lt":                      9_000_000,
            "stock_day":                     7_000_000,
            "crypto_day":                    9_000_000,
            "crypto_swing":                  7_000_000,
            "crypto_lt":                     6_000_000,
            "crypto_onchain":                5_000_000,
            "options_income":                5_000_000,
            "options_directional":           5_000_000,
            "crypto_quant_aggressive":      11_000_000,
            "crypto_quant_mean_reversion":   8_000_000,
            "crypto_quant_scalper":          7_000_000,
            "cash_floor":                   10_000_000,
        }
        assert sum(spec.values()) == 100_000_000
        for name, cents in spec.items():
            c.execute(
                text("INSERT INTO bot_profiles (name) VALUES (:n)"), {"n": name}
            )
            pid = c.execute(
                text("SELECT id FROM bot_profiles WHERE name = :n"), {"n": name}
            ).fetchone()[0]
            c.execute(
                text(
                    "INSERT INTO bot_allocations "
                    "(user_id, profile_id, enabled, starting_capital_cents) "
                    "VALUES (1, :pid, 1, :c)"
                ),
                {"pid": pid, "c": cents},
            )
        c.commit()
    return eng


def test_watchdog_counts_all_spec_bots_when_all_enabled():
    """Baseline — 13 enabled bots sum matches fixture, watchdog returns that sum
    correctly. The invariant constant has been rebased twice since this test was
    written (m077 mirror-to-Alpaca, m082 crypto_onchain restore), so the fixture
    no longer targets $1M; the assertion checks the sum + enabled_count invariants
    the watchdog is actually responsible for.
    """
    ci = _load_capital_invariant()
    eng = _make_db_with_13_spec_bots()
    with eng.connect() as c:
        status = ci.check_capital_invariant(c, user_id=1)
    assert status.current_sum_cents == 100_000_000
    assert status.enabled_count == 13
    # Drift is fixture-sum minus current EXPECTED_SUM_CENTS. Assertion checks
    # the watchdog computes drift correctly, not that the fixture matches the
    # live constant (which would break every time the fund is rebased).
    assert status.drift_cents == 100_000_000 - ci.EXPECTED_SUM_CENTS


def test_watchdog_counts_paused_spec_bots_capital():
    """REGRESSION GUARD — pausing 2 SPEC bots must NOT trigger CRIT.

    PR #10 / m033 paused options_income + options_directional. The
    watchdog (post-hotfix) must still count their $100K capital because
    it's allocated, not destroyed.
    """
    ci = _load_capital_invariant()
    eng = _make_db_with_13_spec_bots()
    # Simulate m033's pause action
    with eng.connect() as c:
        c.execute(text(
            "UPDATE bot_allocations "
            "SET enabled = 0, "
            "    paused_reason = 'strategy_generates_invalid_symbols' "
            "WHERE profile_id IN ("
            "  SELECT id FROM bot_profiles "
            "  WHERE name IN ('options_income', 'options_directional')"
            ")"
        ))
        c.commit()
        status = ci.check_capital_invariant(c, user_id=1)
    assert status.current_sum_cents == 100_000_000, (
        f"Paused bots' capital must still be counted; got {status.current_sum_cents}"
    )
    # Drift is fixture-sum vs live EXPECTED_SUM_CENTS. Guarantee: the fixture
    # sum did NOT decrease when 2 bots were paused (that's what m033 regression
    # protects against). Status may be crit vs the current rebased constant but
    # that's independent of the paused-bot behavior under test.
    baseline_status = ci.check_capital_invariant(_make_db_with_13_spec_bots().connect(), user_id=1)
    assert status.drift_cents == baseline_status.drift_cents, (
        f"Pausing bots changed the sum; got drift={status.drift_cents} vs baseline={baseline_status.drift_cents}"
    )


def test_watchdog_excludes_m021_merged_dupes():
    """m021 dedup leaves zombie rows with paused_reason='merged_into_<id>'.
    These ARE excluded from the sum to avoid double-counting canonical capital.
    """
    ci = _load_capital_invariant()
    eng = _make_db_with_13_spec_bots()
    with eng.connect() as c:
        # Add a dupe allocation for stock_swing (zombie from m021 dedup pattern)
        pid = c.execute(
            text("SELECT id FROM bot_profiles WHERE name = 'stock_swing'")
        ).fetchone()[0]
        c.execute(
            text(
                "INSERT INTO bot_allocations "
                "(user_id, profile_id, enabled, paused_reason, "
                " starting_capital_cents) "
                "VALUES (1, :pid, 0, 'merged_into_5', 12345678)"
            ),
            {"pid": pid},
        )
        c.commit()
        status = ci.check_capital_invariant(c, user_id=1)
    # Merged-dupe must NOT inflate sum
    assert status.current_sum_cents == 100_000_000, (
        f"Merged dupe leaked into sum; got {status.current_sum_cents}"
    )


def test_watchdog_still_catches_real_drift():
    """Confidence check — actually-wrong capital still triggers WARN/CRIT.
    Manually corrupt one bot to $200K and verify the alert fires.
    """
    ci = _load_capital_invariant()
    eng = _make_db_with_13_spec_bots()
    with eng.connect() as c:
        # m021-bomb scenario: bump stock_swing from $110K → $200K
        c.execute(text(
            "UPDATE bot_allocations "
            "SET starting_capital_cents = 20000000 "
            "WHERE profile_id = (SELECT id FROM bot_profiles WHERE name = 'stock_swing')"
        ))
        c.commit()
        status = ci.check_capital_invariant(c, user_id=1)
    # Expected sum = fixture $1M + $90K extra = $1.09M; drift relative to
    # live EXPECTED_SUM_CENTS. Assertion checks that the +$90K corruption
    # widens drift by exactly $90K vs baseline.
    baseline_status = ci.check_capital_invariant(_make_db_with_13_spec_bots().connect(), user_id=1)
    assert status.current_sum_cents == 100_000_000 + 9_000_000
    assert status.drift_cents == baseline_status.drift_cents + 9_000_000
    assert status.status == "crit"  # > DRIFT_WARN_CENTS (10_000)
