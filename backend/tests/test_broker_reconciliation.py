"""Tests for app.ops.broker_reconciliation.reconcile_positions.

Strategy:
  - Inject a fake `broker_fetcher` callable so no live Alpaca call is made.
  - Monkeypatch `_fetch_db_positions` to return canned DB rows so we don't
    need a real SQLAlchemy session for the bucket-classification tests
    (conftest mocks the bot model classes anyway).

Covers:
  - matched: symbol present on both sides with same qty
  - broker_only: symbol at broker, not in DB
  - db_only: symbol in DB, not at broker
  - qty_mismatched: same symbol, different qty
  - severity: ok / warn / alert / error
  - error path: broker fetch raises
"""
from __future__ import annotations

import importlib.util
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _load_broker_reconciliation():
    """Load app/ops/broker_reconciliation.py by file path.

    conftest.py installs a non-package mock for `app`, which makes
    `import app.ops.broker_reconciliation` fail with ModuleNotFoundError.
    Loading via importlib bypasses that registry.
    """
    path = os.path.join(
        os.path.dirname(__file__), "..", "app", "ops", "broker_reconciliation.py"
    )
    spec = importlib.util.spec_from_file_location("broker_reconciliation_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


br = _load_broker_reconciliation()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _broker(symbol, qty, market_value, side="long"):
    return {"symbol": symbol, "qty": qty, "market_value": market_value, "side": side}


def _db(symbol, qty, avg_cost_dollars, allocation_id=1, position_id=1):
    """Helper that mirrors what _fetch_db_positions returns. avg_cost_dollars
    is dollars; converted to cents internally."""
    return {
        "position_id": position_id,
        "allocation_id": allocation_id,
        "symbol": symbol,
        "qty": qty,
        "side": "long",
        "avg_cost_cents": float(avg_cost_dollars) * 100.0,
        "notional_db": float(qty) * float(avg_cost_dollars),
    }


@pytest.fixture
def patch_db(monkeypatch):
    """Returns a setter that replaces _fetch_db_positions with a function
    returning the supplied list."""
    def _set(rows):
        monkeypatch.setattr(br, "_fetch_db_positions", lambda db, user_id: list(rows))
    return _set


# ─── Bucket-classification tests ──────────────────────────────────────────────

class TestBuckets:

    def test_all_matched_is_ok(self, patch_db):
        patch_db([
            _db("AAPL", 100, 150.0),
            _db("MSFT", 50, 300.0),
        ])
        report = br.reconcile_positions(
            db=None, user_id=1,
            broker_fetcher=lambda: [
                _broker("AAPL", 100, 15500.0),  # market value differs from cost — that's fine
                _broker("MSFT", 50, 14800.0),
            ],
        )
        assert report["divergence_severity"] == "ok"
        assert len(report["matched"]) == 2
        assert report["broker_only"] == []
        assert report["db_only"] == []
        assert report["qty_mismatched"] == []
        assert report["broker_positions_count"] == 2
        assert report["db_positions_count"] == 2

    def test_broker_only_bucket(self, patch_db):
        patch_db([
            _db("AAPL", 100, 150.0),
        ])
        report = br.reconcile_positions(
            db=None, user_id=1,
            broker_fetcher=lambda: [
                _broker("AAPL", 100, 15500.0),
                _broker("TSLA", 25, 5500.0),  # not in DB — broker_only
            ],
        )
        symbols = [r["symbol"] for r in report["broker_only"]]
        assert symbols == ["TSLA"]
        assert report["broker_only"][0]["qty_broker"] == 25
        assert report["broker_only"][0]["notional_broker"] == 5500.0

    def test_db_only_bucket(self, patch_db):
        patch_db([
            _db("AAPL", 100, 150.0),
            _db("GOOGL", 10, 2800.0),  # not at broker — db_only
        ])
        report = br.reconcile_positions(
            db=None, user_id=1,
            broker_fetcher=lambda: [
                _broker("AAPL", 100, 15500.0),
            ],
        )
        symbols = [r["symbol"] for r in report["db_only"]]
        assert symbols == ["GOOGL"]
        assert report["db_only"][0]["qty_db"] == 10
        assert report["db_only"][0]["notional_db"] == 28000.0

    def test_qty_mismatched_bucket(self, patch_db):
        patch_db([
            _db("AAPL", 100, 150.0),
        ])
        report = br.reconcile_positions(
            db=None, user_id=1,
            broker_fetcher=lambda: [
                _broker("AAPL", 95, 14725.0),  # partial fill drift: 95 vs 100
            ],
        )
        assert len(report["qty_mismatched"]) == 1
        m = report["qty_mismatched"][0]
        assert m["symbol"] == "AAPL"
        assert m["qty_broker"] == 95
        assert m["qty_db"] == 100
        # No matched rows for qty-mismatched symbols
        assert report["matched"] == []

    def test_multiple_lots_same_symbol_aggregates(self, patch_db):
        """Bots holding 2 lots of AAPL on the same symbol must sum qty before diff."""
        patch_db([
            _db("AAPL", 60, 150.0, position_id=1, allocation_id=1),
            _db("AAPL", 40, 152.0, position_id=2, allocation_id=2),
        ])
        report = br.reconcile_positions(
            db=None, user_id=1,
            broker_fetcher=lambda: [
                _broker("AAPL", 100, 15500.0),
            ],
        )
        # 60 + 40 = 100 — matches broker's 100. Should be in matched.
        assert len(report["matched"]) == 1
        assert report["matched"][0]["qty_db"] == 100
        assert report["matched"][0]["qty_broker"] == 100
        assert report["qty_mismatched"] == []


# ─── Severity classification ──────────────────────────────────────────────────

class TestSeverity:

    def test_ok_when_zero_diffs(self, patch_db):
        patch_db([_db("AAPL", 10, 100.0)])
        report = br.reconcile_positions(
            db=None, user_id=1,
            broker_fetcher=lambda: [_broker("AAPL", 10, 1100.0)],
        )
        assert report["divergence_severity"] == "ok"

    def test_warn_when_small_divergence(self, patch_db):
        # db_only with $50 notional → < $100 → warn
        patch_db([_db("AAPL", 1, 50.0)])
        report = br.reconcile_positions(
            db=None, user_id=1,
            broker_fetcher=lambda: [],
        )
        assert report["divergence_severity"] == "warn"

    def test_alert_when_large_divergence(self, patch_db):
        # db_only with $5000 notional → >> $100 → alert
        patch_db([_db("AAPL", 50, 100.0)])
        report = br.reconcile_positions(
            db=None, user_id=1,
            broker_fetcher=lambda: [],
        )
        assert report["divergence_severity"] == "alert"

    def test_alert_with_qty_mismatch_large(self, patch_db):
        patch_db([_db("AAPL", 100, 150.0)])  # notional_db = $15K
        report = br.reconcile_positions(
            db=None, user_id=1,
            broker_fetcher=lambda: [_broker("AAPL", 50, 7500.0)],  # diff = $7500
        )
        assert report["divergence_severity"] == "alert"


# ─── Error path ───────────────────────────────────────────────────────────────

class TestErrorPath:

    def test_broker_fetch_failure_returns_error_severity(self, patch_db):
        patch_db([])
        def failing_fetcher():
            raise RuntimeError("alpaca down: 503 service unavailable")
        report = br.reconcile_positions(
            db=None, user_id=1,
            broker_fetcher=failing_fetcher,
        )
        assert report["divergence_severity"] == "error"
        assert "alpaca down" in report["error"]
        # Buckets should be empty when broker fetch fails
        assert report["matched"] == []
        assert report["broker_only"] == []
        assert report["db_only"] == []
        assert report["qty_mismatched"] == []

    def test_error_path_does_not_call_db(self, monkeypatch):
        """When broker fetch fails, we should NOT touch the DB at all
        (defensive: avoids spurious queries during incident-debug runs)."""
        calls = []
        def spy(db, user_id):
            calls.append((db, user_id))
            return []
        monkeypatch.setattr(br, "_fetch_db_positions", spy)
        def failing_fetcher():
            raise RuntimeError("boom")
        report = br.reconcile_positions(
            db="SENTINEL_DB", user_id=1,
            broker_fetcher=failing_fetcher,
        )
        assert report["divergence_severity"] == "error"
        assert calls == [], "_fetch_db_positions must NOT be called on broker failure"


# ─── Report shape contract ────────────────────────────────────────────────────

class TestReportShape:

    def test_report_has_all_required_keys(self, patch_db):
        patch_db([_db("AAPL", 1, 100.0)])
        report = br.reconcile_positions(
            db=None, user_id=1,
            broker_fetcher=lambda: [_broker("AAPL", 1, 100.0)],
        )
        required = {
            "as_of",
            "user_id",
            "broker_positions_count",
            "db_positions_count",
            "matched",
            "broker_only",
            "db_only",
            "qty_mismatched",
            "divergence_severity",
        }
        assert required.issubset(set(report.keys()))

    def test_as_of_is_iso_string(self, patch_db):
        patch_db([])
        report = br.reconcile_positions(
            db=None, user_id=1,
            broker_fetcher=lambda: [],
        )
        # Just verify it parses as ISO 8601
        from datetime import datetime
        datetime.fromisoformat(report["as_of"])

    def test_user_id_echoed(self, patch_db):
        patch_db([])
        report = br.reconcile_positions(
            db=None, user_id=7,
            broker_fetcher=lambda: [],
        )
        assert report["user_id"] == 7


# ─── Read-only invariant ──────────────────────────────────────────────────────

class TestReadOnly:
    """Guard against accidental DB mutation. The reconciler must never call
    db.add, db.commit, db.delete, or db.flush. This test passes a sentinel
    object that records any attribute access."""

    def test_no_db_mutation_methods_called(self, monkeypatch):
        # Use the canned-data path so we don't hit _fetch_db_positions either
        monkeypatch.setattr(br, "_fetch_db_positions", lambda db, user_id: [])
        accessed = []
        class Spy:
            def __getattr__(self, name):
                accessed.append(name)
                raise AttributeError(f"db.{name} should not be called")
        report = br.reconcile_positions(
            db=Spy(), user_id=1,
            broker_fetcher=lambda: [],
        )
        assert report["divergence_severity"] == "ok"
        # _fetch_db_positions is patched, so no attrs should have been accessed
        # on the Spy object at all.
        for forbidden in ("add", "commit", "delete", "flush", "merge"):
            assert forbidden not in accessed, f"reconciler touched db.{forbidden}"


# ─── Discord formatter ────────────────────────────────────────────────────────

class TestFormatter:

    def test_format_ok_report(self):
        report = {
            "divergence_severity": "ok",
            "broker_positions_count": 5,
            "db_positions_count": 5,
            "matched": [{"symbol": "AAPL"}] * 5,
            "broker_only": [],
            "db_only": [],
            "qty_mismatched": [],
        }
        txt = br.format_report_for_discord(report)
        assert "OK" in txt
        assert "Broker positions: 5" in txt

    def test_format_error_report(self):
        report = {"divergence_severity": "error", "error": "boom"}
        txt = br.format_report_for_discord(report)
        assert "FAILED" in txt
        assert "boom" in txt
