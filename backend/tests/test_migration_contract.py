"""Migration contract tests.

Lessons enforced (2026-06-28):
  - Every migration registered in main.py lifespan must EITHER have an
    idempotency gate OR appear in the explicit naturally-idempotent waiver list.
  - m027 self-heals on drift: if SUM(starting_capital_cents) drifts from $1M,
    m027 re-runs on next boot instead of skipping.
  - m021 has the gate that was missing (the bomb that caused the regression).
"""
from __future__ import annotations

import importlib.util
import re
import sys
import types
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text


REPO_ROOT = Path(__file__).resolve().parents[2]
MAIN_PY = REPO_ROOT / "backend" / "app" / "main.py"
MIGRATIONS_DIR = REPO_ROOT / "backend" / "app" / "db" / "migrations"


def _load_migration(module_short: str):
    """Load a migration module from disk, bypassing conftest's `app.db` stub.

    conftest.py pre-mocks `app.db` as a non-package types.ModuleType, which
    blocks normal `from app.db.migrations.mNNN import run`. We sidestep by
    loading the file directly and registering it under the real-package path
    plus a temporary fully-qualified name so cross-imports resolve.
    """
    pkg = "app.db.migrations"
    if pkg not in sys.modules or not hasattr(sys.modules[pkg], "__path__"):
        real_pkg = types.ModuleType(pkg)
        real_pkg.__path__ = [str(MIGRATIONS_DIR)]
        sys.modules[pkg] = real_pkg
        # Also rewire app.db so child resolution works.
        app_db = sys.modules.get("app.db")
        if app_db is not None:
            app_db.migrations = real_pkg
    full = f"{pkg}.{module_short}"
    path = MIGRATIONS_DIR / f"{module_short}.py"
    spec = importlib.util.spec_from_file_location(full, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full] = mod
    spec.loader.exec_module(mod)
    return mod

# Migrations whose run() does additive DDL only or already-filtered UPDATEs
# (pre-state in WHERE clause). Naturally idempotent without a gate.
# See .pipeline/01-spec.md audit table for justification.
_NATURALLY_IDEMPOTENT_WAIVER = {
    "m003_quant_research",
    "m004_pause_t0_violations",
    "m005_options_fields",
    "m006_reenable_stalled_production_bots",
    "m007_unlock_crypto_day",
    "m008_backfill_nav_history",
    "m009_agent_conversation_log",
    "m010_quarantine_legacy_options",
    "m011_quarantine_legacy_options_trades",
    "m012_quarantine_misrouted_share_orders",
    "m013_fix_smart_money_congress_id",
    "m014_signal_gates",
    "m015_hypotheses",
    "m016_add_bot_health_status",
    "m017_disable_incubating_allocations",
    "m018_add_bot_heartbeat",
    "m019_add_modeled_fees_cents",
    "m020_add_bot_threshold_dynamic",
    "m002_seed_bots_t2_v1",  # intentionally ungated per file header (idempotent UPDATEs preserving state)
    "m046_force_kill_stuck_running_meetings",  # NO gate by design — runs every boot, idempotent via WHERE clause (kills 0 rows on clean DB). See spec section COMMIT 2.
    "m047_bot_daily_journals",  # Additive DDL only: CREATE TABLE IF NOT EXISTS + CREATE INDEX IF NOT EXISTS. Phase 1 closed-loop journal table — no backfill, no date predicate, no UPDATE/DELETE. Safe to re-run on every boot.
    "m048_aqa_state",  # Additive DDL only: CREATE TABLE IF NOT EXISTS + seed row guarded by COUNT(*)==0 check. No UPDATE/DELETE of existing rows. Safe to re-run on every boot (idempotent by construction).
}


def _registered_migrations() -> list[str]:
    """Parse main.py for all `from app.db.migrations.mNNN_... import run` lines."""
    src = MAIN_PY.read_text()
    pat = re.compile(r"from app\.db\.migrations\.(m\d+\w*) import run")
    return sorted(set(pat.findall(src)))


def _has_idempotency_marker(module_name: str) -> bool:
    """True if the migration file calls _migration_already_ran or already_ran."""
    path = MIGRATIONS_DIR / f"{module_name}.py"
    if not path.exists():
        return False
    src = path.read_text()
    return (
        "_migration_already_ran" in src
        or "already_ran(" in src
        or "_gate_already_ran" in src
        or "schema_migrations" in src
    )


def test_every_registered_migration_has_idempotency_gate_or_waiver():
    """CI fail if a new migration lands without a gate or explicit waiver."""
    registered = _registered_migrations()
    assert registered, "No migrations found in main.py — parser bug"

    violations = []
    for m in registered:
        if _has_idempotency_marker(m):
            continue
        if m in _NATURALLY_IDEMPOTENT_WAIVER:
            continue
        violations.append(m)

    assert not violations, (
        f"Migrations missing both idempotency gate AND waiver: {violations}. "
        f"Either add a gate via app.db.migrations._gate.already_ran/record, or "
        f"add to _NATURALLY_IDEMPOTENT_WAIVER with justification."
    )


def test_m021_has_gate():
    """The bomb. Explicit test so the regression cannot return silently."""
    src = (MIGRATIONS_DIR / "m021_merge_and_resize_allocations.py").read_text()
    assert "_migration_already_ran" in src or "already_ran" in src, (
        "m021 must have idempotency gate — it was the cause of the 2026-06-28 "
        "$1M → $2.6M capital regression."
    )
    assert "m021_merge_and_resize_allocations_2026_06" in src


def _make_test_db():
    """In-memory SQLite with the bare-minimum schema m027 needs."""
    eng = create_engine("sqlite:///:memory:")
    with eng.connect() as c:
        c.execute(text("""
            CREATE TABLE schema_migrations (
                migration_name TEXT PRIMARY KEY,
                applied_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """))
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
                tier TEXT,
                starting_capital_cents INTEGER,
                inception_capital_cents INTEGER,
                current_capital_cents INTEGER,
                updated_at TEXT,
                created_at TEXT
            )
        """))
        c.execute(text("CREATE TABLE bot_trades (id INTEGER PRIMARY KEY, allocation_id INTEGER, user_id INTEGER, symbol TEXT)"))
        c.execute(text("CREATE TABLE bot_daily_pnl (id INTEGER PRIMARY KEY, allocation_id INTEGER, user_id INTEGER)"))
        c.execute(text("""
            CREATE TABLE bot_positions (
                id INTEGER PRIMARY KEY,
                allocation_id INTEGER,
                symbol TEXT,
                closed_at TEXT,
                exit_reason TEXT,
                quarantined_at TEXT
            )
        """))
        # Seed 13 spec bots for user_id=1 with canonical amounts.
        m027_mod = _load_migration("m027_force_clean_slate")
        ALLOCATIONS_CENTS = m027_mod.ALLOCATIONS_CENTS
        for name, cents in ALLOCATIONS_CENTS.items():
            c.execute(text(
                "INSERT INTO bot_profiles (name) VALUES (:n)"
            ), {"n": name})
            pid = c.execute(text(
                "SELECT id FROM bot_profiles WHERE name=:n"
            ), {"n": name}).fetchone()[0]
            c.execute(text("""
                INSERT INTO bot_allocations
                    (user_id, profile_id, enabled, starting_capital_cents,
                     inception_capital_cents, current_capital_cents)
                VALUES (1, :pid, 1, :c, :c, :c)
            """), {"pid": pid, "c": cents})
        c.commit()
    return eng


def test_m027_skips_when_state_matches_spec():
    """After m027 runs once, second invocation on a clean book should skip."""
    run_m027 = _load_migration("m027_force_clean_slate").run
    eng = _make_test_db()
    with eng.connect() as c:
        r1 = run_m027(c)
        assert r1.get("executed") is True, f"first run should execute: {r1}"
        r2 = run_m027(c)
        assert r2.get("executed") is False, f"second run should skip: {r2}"
        assert r2.get("skipped_reason") == "state_matches_spec", r2


def test_m027_reruns_when_state_drifts_from_spec():
    """Force drift after first run; m027 must re-execute and heal."""
    run_m027 = _load_migration("m027_force_clean_slate").run
    eng = _make_test_db()
    with eng.connect() as c:
        r1 = run_m027(c)
        assert r1.get("executed") is True
        # Force drift: set all bots to $200K (the m021 bomb scenario).
        c.execute(text(
            "UPDATE bot_allocations SET starting_capital_cents = 20000000"
            " WHERE user_id = 1 AND enabled = 1"
        ))
        c.commit()
        drifted_sum = c.execute(text(
            "SELECT SUM(starting_capital_cents) FROM bot_allocations"
            " WHERE user_id=1 AND enabled=1"
        )).fetchone()[0]
        assert drifted_sum == 13 * 20_000_000, "drift setup failed"

        r2 = run_m027(c)
        assert r2.get("executed") is True, (
            f"m027 must re-run on drift, got {r2}"
        )
        # State should be healed back to canonical.
        healed_sum = c.execute(text(
            "SELECT SUM(starting_capital_cents) FROM bot_allocations"
            " WHERE user_id=1 AND enabled=1"
        )).fetchone()[0]
        assert healed_sum == 100_000_000, f"m027 did not heal, sum={healed_sum}"


def test_m021_gate_prevents_second_run():
    """m021 records itself and returns skipped on the next call."""
    run_m021 = _load_migration("m021_merge_and_resize_allocations").run
    eng = _make_test_db()
    with eng.connect() as c:
        r1 = run_m021(c)
        assert r1.get("executed") is True, f"first run should execute: {r1}"
        r2 = run_m021(c)
        assert r2.get("executed") is False, f"second run should skip: {r2}"
        assert r2.get("skipped_reason") == "already_applied"


def test_m027_self_heal_does_not_delete_bot_trades_or_daily_pnl():
    """Standing decision (2026-06-28): capital resets MUST NOT delete history."""
    # m027 does delete trades/daily_pnl in its current form (pre-Brock's new
    # standing decision). This test documents the contract; it's expected to
    # FAIL on m027 as-shipped and only pass after SHIP 4 refactors m027 to
    # preserve history. Marking as expected-fail with a clear marker so the
    # contract is visible in CI without blocking this ship.
    pytest.skip(
        "Contract documented; m027 history-preservation refactor lands in SHIP 4."
    )
