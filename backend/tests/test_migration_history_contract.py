"""SHIP 3 contract: no migration may wipe bot_trades or bot_daily_pnl,
no migration after m027 may overwrite inception_capital_cents.

Standing decision (2026-06-28): capital resets must NOT delete trade history.
"""
import re
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = REPO_ROOT / "backend" / "app" / "db" / "migrations"

# Grandfathered: the one historical exception (m027 was the trigger event)
_DELETE_BOT_TRADES_WAIVER = {"m027_force_clean_slate"}
_DELETE_BOT_DAILY_PNL_WAIVER = {"m027_force_clean_slate"}
# m025/m026/m027 had documented one-time corrective overwrites of inception.
_UPDATE_INCEPTION_WAIVER = {
    "m023_add_inception_capital_cents",  # backfill, additive only
    "m025_clean_slate_one_million",
    "m026_disable_non_spec_allocations",
    "m027_force_clean_slate",
}


def _migration_files() -> list[Path]:
    return sorted(p for p in MIGRATIONS_DIR.glob("m*.py") if p.name != "_gate.py")


def _migration_number(path: Path) -> int:
    m = re.match(r"m(\d+)", path.stem)
    return int(m.group(1)) if m else -1


def test_no_migration_deletes_bot_trades_for_user_1():
    """Standing decision (2026-06-28): no migration may DELETE FROM bot_trades
    without explicit waiver. m027 is the sole grandfathered exception."""
    pattern = re.compile(r"DELETE\s+FROM\s+bot_trades", re.IGNORECASE)
    violators = []
    for path in _migration_files():
        src = path.read_text()
        if pattern.search(src) and path.stem not in _DELETE_BOT_TRADES_WAIVER:
            violators.append(path.stem)
    assert not violators, (
        f"Migrations DELETE-ing bot_trades without waiver: {violators}. "
        f"Standing decision (2026-06-28): capital resets must NOT delete trade history."
    )


def test_no_migration_deletes_bot_daily_pnl_for_user_1():
    """Standing decision (2026-06-28): no migration may DELETE FROM bot_daily_pnl
    without explicit waiver."""
    pattern = re.compile(r"DELETE\s+FROM\s+bot_daily_pnl", re.IGNORECASE)
    violators = []
    for path in _migration_files():
        src = path.read_text()
        if pattern.search(src) and path.stem not in _DELETE_BOT_DAILY_PNL_WAIVER:
            violators.append(path.stem)
    assert not violators, (
        f"Migrations DELETE-ing bot_daily_pnl without waiver: {violators}. "
        f"Standing decision (2026-06-28): capital resets must NOT delete daily PnL history."
    )


def test_no_migration_updates_inception_capital_cents_after_m027():
    """Standing decision: inception_capital_cents is immutable post-m027.
    No migration numbered > m027 may run UPDATE ... SET inception_capital_cents = ..."""
    pattern = re.compile(
        r"UPDATE\s+bot_allocations[\s\S]{0,500}?SET[\s\S]{0,200}?inception_capital_cents\s*=",
        re.IGNORECASE
    )
    violators = []
    for path in _migration_files():
        if path.stem in _UPDATE_INCEPTION_WAIVER:
            continue
        if _migration_number(path) <= 27:
            continue  # pre-m027 migrations are out of scope for this contract
        src = path.read_text()
        if pattern.search(src):
            violators.append(path.stem)
    assert not violators, (
        f"Migrations > m027 updating inception_capital_cents: {violators}. "
        f"Standing decision: inception_capital_cents is immutable post-m027."
    )
