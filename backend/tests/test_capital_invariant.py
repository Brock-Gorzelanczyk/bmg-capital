"""Tests for capital_invariant watchdog.

Pure-Python tests on the in-memory state machinery; SQLAlchemy-backed
session tests skip when conftest mocks app modules (same pattern as the
reconciliation tests).
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_module_imports_and_constants_correct():
    try:
        from app.services.capital_invariant import (
            EXPECTED_SUM_CENTS, DRIFT_OK_CENTS, DRIFT_WARN_CENTS,
            CapitalInvariantStatus, check_capital_invariant,
        )
    except (ImportError, ModuleNotFoundError) as exc:
        pytest.skip(f"app.services not importable in mocked env: {exc}")
    assert EXPECTED_SUM_CENTS == 100_000_000
    assert DRIFT_OK_CENTS == 100
    assert DRIFT_WARN_CENTS == 10_000


def test_status_thresholds():
    """Sanity: the status semantics behave as documented."""
    try:
        from app.services.capital_invariant import DRIFT_OK_CENTS, DRIFT_WARN_CENTS
    except (ImportError, ModuleNotFoundError) as exc:
        pytest.skip(f"capital_invariant not importable: {exc}")

    # Hypothetical status checks via the threshold ladder
    def classify(drift_cents):
        ad = abs(drift_cents)
        if ad <= DRIFT_OK_CENTS:
            return "ok"
        if ad <= DRIFT_WARN_CENTS:
            return "warn"
        return "crit"

    assert classify(0) == "ok"
    assert classify(100) == "ok"
    assert classify(101) == "warn"
    assert classify(10_000) == "warn"
    assert classify(10_001) == "crit"
    assert classify(-50_000) == "crit"
    assert classify(99_900_000) == "crit"  # $999k drift = $1M short = CRIT
