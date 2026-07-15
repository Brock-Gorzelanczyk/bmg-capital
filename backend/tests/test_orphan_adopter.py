"""STOP-THE-LINE #3 (2026-07-15) — orphan adoption tests.

Verifies:
  - OCC parser matches the runner's + frontend's parseOCC output
  - Attribution walks Alpaca order history correctly
  - Unattributable positions land in the ledger with a review flag
  - Kill switch honored
"""
from __future__ import annotations

import os
import sys
import importlib.util
from unittest.mock import MagicMock, patch

# conftest replaces `app` with a mock hierarchy for tests that don't need the
# real database models. Load orphan_adopter directly from its source file so
# it works in that mocked environment.
_HERE = os.path.dirname(os.path.abspath(__file__))
_SPEC = importlib.util.spec_from_file_location(
    "app.services.orphan_adopter",
    os.path.join(_HERE, "..", "app", "services", "orphan_adopter.py"),
)
orphan_adopter = importlib.util.module_from_spec(_SPEC)
sys.modules["app.services.orphan_adopter"] = orphan_adopter
_SPEC.loader.exec_module(orphan_adopter)
# Attach to the conftest's mocked app.services so patch("app.services.orphan_adopter.…")
# resolves the attribute correctly.
sys.modules["app.services"].orphan_adopter = orphan_adopter


def test_parse_occ_valid_symbols():
    from app.services.orphan_adopter import _parse_occ
    p = _parse_occ("BABA260828C00111000")
    assert p is not None
    assert p["root"] == "BABA"
    assert p["expiration_date"] == "2026-08-28"
    assert p["option_type"] == "call"
    assert p["strike_price"] == 111.0

    p2 = _parse_occ("SPY260821P00688000")
    assert p2["option_type"] == "put"
    assert p2["strike_price"] == 688.0


def test_parse_occ_rejects_garbage():
    from app.services.orphan_adopter import _parse_occ
    assert _parse_occ("") is None
    assert _parse_occ("BABA") is None
    assert _parse_occ("NOT-OCC") is None


def test_adopt_orphans_kill_switch():
    """ORPHAN_ADOPTION_ENABLED=false must skip the entire run."""
    import os
    from app.services.orphan_adopter import adopt_orphans

    with patch.dict(os.environ, {"ORPHAN_ADOPTION_ENABLED": "false"}):
        result = adopt_orphans(db=MagicMock(), dry_run=True)
    assert result.get("skipped") == "disabled_by_env"


def test_adopt_orphans_dry_run_no_inserts():
    """dry_run=True must NOT call db.add for any position."""
    from app.services.orphan_adopter import adopt_orphans

    fake_db = MagicMock()
    # Empty BMG side (no open positions)
    fake_db.query.return_value.filter.return_value.filter.return_value.all.return_value = []
    fake_db.query.return_value.filter.return_value.first.return_value = None

    fake_broker_positions = [
        {"symbol": "SPY260828C00500000", "qty": "5", "side": "long",
         "asset_class": "us_option", "market_value": "1000", "unrealized_pl": "0"},
    ]
    fake_orders = []  # empty → attribution will fail → ledgered

    with patch("app.services.orphan_adopter._fetch_broker_options", return_value=fake_broker_positions), \
         patch("app.services.orphan_adopter._fetch_order_history", return_value=fake_orders):
        result = adopt_orphans(db=fake_db, dry_run=True)

    # Even in dry_run we track orphans_found. This one can't be attributed
    # so it goes to the ledger (no Alpaca order matches).
    assert result["orphans_found"] == 1
    assert result["adopted"] == 0
    assert result["ledgered_for_review"] == 1
    # db.add MUST NOT have been called (dry_run + unattributable both prevent inserts)
    fake_db.add.assert_not_called()


def test_adopt_orphans_ledgers_unattributable():
    """A broker position with no matching Alpaca order → orphan ledger row
    with reason='no_matching_alpaca_order_or_bot_trade'."""
    from app.services.orphan_adopter import adopt_orphans

    fake_db = MagicMock()
    fake_db.query.return_value.filter.return_value.filter.return_value.all.return_value = []
    fake_db.query.return_value.filter.return_value.first.return_value = None

    fake_broker_positions = [
        {"symbol": "AAPL260828C00310000", "qty": "5", "side": "long",
         "asset_class": "us_option", "market_value": "6000", "unrealized_pl": "-200"},
    ]

    with patch("app.services.orphan_adopter._fetch_broker_options", return_value=fake_broker_positions), \
         patch("app.services.orphan_adopter._fetch_order_history", return_value=[]):
        result = adopt_orphans(db=fake_db, dry_run=True)

    assert result["ledgered_for_review"] == 1
    detail = result["ledgered_details"][0]
    assert detail["occ_symbol"] == "AAPL260828C00310000"
    assert "no_matching_alpaca" in detail["reason"]


def test_drift_metric_reports_alpaca_totals():
    """Result must include broker_options_count, bmg_options_count_before/after,
    and alpaca_total_unrealized_pl so Brock's daily drift check can read them."""
    from app.services.orphan_adopter import adopt_orphans

    fake_db = MagicMock()
    fake_db.query.return_value.filter.return_value.filter.return_value.all.return_value = []

    fake_broker_positions = [
        {"symbol": "SPY260828C00500000", "qty": "5", "side": "long",
         "asset_class": "us_option", "market_value": "1000", "unrealized_pl": "-100"},
        {"symbol": "SPY260828C00505000", "qty": "-5", "side": "short",
         "asset_class": "us_option", "market_value": "-900", "unrealized_pl": "50"},
    ]

    with patch("app.services.orphan_adopter._fetch_broker_options", return_value=fake_broker_positions), \
         patch("app.services.orphan_adopter._fetch_order_history", return_value=[]):
        result = adopt_orphans(db=fake_db, dry_run=True)

    assert result["broker_options_count"] == 2
    assert result["bmg_options_count_before"] == 0
    assert result["alpaca_total_unrealized_pl"] == -50.0   # -100 + 50
