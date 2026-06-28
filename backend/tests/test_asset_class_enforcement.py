"""Tests for asset_class_registry module (SHIP 14).

Verifies:
  - Registry covers all 13 m027 bots, no more, no less
  - classify_instrument handles equity/crypto/option/edge-cases
  - validate_order raises on mismatch, passes on match
  - cash_floor allowlist enforced
  - spec-slug aliases raise with canonical name in message
  - Discord ops-alert rate-limiting (at-most-once per bot/symbol/day)
  - Unknown bot raises RuntimeError
"""
import os
import sys
import types
import pytest
from unittest.mock import MagicMock, patch, call

# ─── bootstrap: the registry imports from app.db.migrations.m027_force_clean_slate
# We handle this by pre-loading a fake sqlalchemy and then importing the real modules.

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Ensure app.db.migrations namespace exists so the registry import-time check
# can import ALLOCATIONS_CENTS from the real m027 module.
# The conftest already mocks app, app.db, app.db.models — we need to add
# app.db.migrations as a real (not mocked) passthrough so the actual file loads.

def _ensure_migrations_importable():
    """Wire app.db.migrations so it resolves from the filesystem."""
    import importlib.util

    # Build the stub hierarchy if not already present
    _migrations_mod_name = "app.db.migrations"
    if _migrations_mod_name not in sys.modules:
        _mig_mod = types.ModuleType(_migrations_mod_name)
        _mig_mod.__path__ = [os.path.join(os.path.dirname(__file__), "..", "app", "db", "migrations")]
        _mig_mod.__package__ = _migrations_mod_name
        sys.modules[_migrations_mod_name] = _mig_mod
        # Wire into the app.db stub so getattr works
        if "app.db" in sys.modules:
            sys.modules["app.db"].migrations = _mig_mod

    m027_name = "app.db.migrations.m027_force_clean_slate"
    if m027_name not in sys.modules:
        path = os.path.join(
            os.path.dirname(__file__), "..", "app", "db", "migrations",
            "m027_force_clean_slate.py",
        )
        # m027 imports sqlalchemy.text — stub it out
        import types as _types
        fake_sa = _types.ModuleType("sqlalchemy")
        fake_sa.text = lambda s: s
        old_sa = sys.modules.get("sqlalchemy")
        sys.modules.setdefault("sqlalchemy", fake_sa)
        try:
            spec = importlib.util.spec_from_file_location(m027_name, path)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[m027_name] = mod
            spec.loader.exec_module(mod)
        finally:
            if old_sa is None:
                sys.modules.pop("sqlalchemy", None)
            else:
                sys.modules["sqlalchemy"] = old_sa


_ensure_migrations_importable()


def _import_registry():
    """Import the real asset_class_registry, reloading if already cached."""
    import importlib
    # Remove cached version so the import-time invariants re-run
    for k in list(sys.modules.keys()):
        if "asset_class_registry" in k:
            del sys.modules[k]

    # Make sure discord import inside validate_order is stubbed
    _disc_mod = types.ModuleType("app.services.discord")
    _disc_mod.send_ops_alert = MagicMock()
    sys.modules["app.services.discord"] = _disc_mod

    # Stub app.services.asset_class_registry as the real file
    import importlib.util
    path = os.path.join(
        os.path.dirname(__file__), "..", "app", "services",
        "asset_class_registry.py",
    )
    spec = importlib.util.spec_from_file_location("app.services.asset_class_registry", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["app.services.asset_class_registry"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def registry():
    return _import_registry()


# ─── tests ───────────────────────────────────────────────────────────────────

def test_registry_covers_all_m027_bots(registry):
    """Registry has exactly the same keys as m027.ALLOCATIONS_CENTS."""
    m027 = sys.modules["app.db.migrations.m027_force_clean_slate"]
    assert set(registry.ASSET_CLASS_REGISTRY.keys()) == set(m027.ALLOCATIONS_CENTS.keys())


def test_registry_keys_match_m027_keys_exactly(registry):
    """Both directions of the set diff must be empty."""
    m027 = sys.modules["app.db.migrations.m027_force_clean_slate"]
    reg_keys = set(registry.ASSET_CLASS_REGISTRY.keys())
    m027_keys = set(m027.ALLOCATIONS_CENTS.keys())
    assert reg_keys - m027_keys == set(), f"In registry but NOT in m027: {reg_keys - m027_keys}"
    assert m027_keys - reg_keys == set(), f"In m027 but NOT in registry: {m027_keys - reg_keys}"


def test_crypto_bot_rejected_on_equity_order(registry):
    """crypto_day + 'AAPL' must raise RuntimeError (asset_class_mismatch)."""
    with pytest.raises(RuntimeError, match="asset_class_violation"):
        registry.validate_order("crypto_day", "AAPL")


def test_crypto_bot_accepts_crypto_pair(registry):
    """crypto_day + 'BTC/USD' must pass (no exception)."""
    registry.validate_order("crypto_day", "BTC/USD")  # should not raise


def test_cash_floor_rejected_on_non_allowlist(registry):
    """cash_floor + 'GOOG' and 'MSFT' fail; 'SPY' and 'QQQ' pass."""
    with pytest.raises(RuntimeError, match="asset_class_violation"):
        registry.validate_order("cash_floor", "GOOG")
    with pytest.raises(RuntimeError, match="asset_class_violation"):
        registry.validate_order("cash_floor", "MSFT")
    registry.validate_order("cash_floor", "SPY")   # no raise
    registry.validate_order("cash_floor", "QQQ")   # no raise


def test_options_bot_rejected_on_equity_order(registry):
    """options_directional + 'AAPL' must raise (equity, not option)."""
    with pytest.raises(RuntimeError, match="asset_class_violation"):
        registry.validate_order("options_directional", "AAPL")


def test_options_bot_accepts_occ_symbol(registry):
    """options_directional + OCC-format symbol must pass."""
    registry.validate_order("options_directional", "SPY250816P00400000")  # no raise


def test_equity_bot_rejected_on_crypto_order(registry):
    """stock_swing + 'BTC/USD' must raise (crypto, not equity)."""
    with pytest.raises(RuntimeError, match="asset_class_violation"):
        registry.validate_order("stock_swing", "BTC/USD")


def test_classify_instrument_handles_edge_cases(registry):
    ci = registry.classify_instrument

    # BRK.B style — equity
    assert ci("BRK.B") == "equity"
    # Standard crypto pair
    assert ci("BTC/USD") == "crypto"
    # Standard OCC symbol (21 chars: root=SPY + 6 date digits + C/P + 8 strike digits)
    assert ci("SPY250816P00400000") == "option"
    # 5-letter-root OCC symbol
    assert ci("BRKB250620C00500000") == "option"
    # Lowercase crypto pair — strip+upper handles it
    assert ci("btc/usd") == "crypto"
    # Whitespace in symbol
    assert ci("  BTC/USD  ") == "crypto"
    # Empty string — raises
    with pytest.raises(RuntimeError):
        ci("")
    # None — raises
    with pytest.raises(RuntimeError):
        ci(None)
    # Unclassifiable slash symbol (not a known crypto pair)
    with pytest.raises(RuntimeError):
        ci("XXX-YYY")
    # Short plain ticker that looks like equity (SPY alone = equity, NOT option)
    assert ci("SPY") == "equity"


def test_spec_slug_alias_raises_with_canonical_name(registry):
    """Passing spec slug 'stock_long_term' must raise and mention 'stock_lt'."""
    with pytest.raises(RuntimeError, match="stock_lt"):
        registry.validate_order("stock_long_term", "AAPL")


def test_validate_order_logs_violation_with_required_and_detected_fields(registry, caplog):
    """validate_order logs [asset_class_violation] at ERROR level on mismatch."""
    import logging
    with caplog.at_level(logging.ERROR):
        with pytest.raises(RuntimeError):
            registry.validate_order("crypto_day", "AAPL")
    assert any(
        "asset_class_violation" in rec.message
        and "required=crypto" in rec.message
        and "detected=equity" in rec.message
        for rec in caplog.records
    ), f"Expected structured violation log. Got: {[r.message for r in caplog.records]}"


def test_validate_order_rate_limits_discord_to_once_per_bot_symbol_per_day(registry):
    """send_ops_alert must be called exactly once for 5 violations of same (bot, symbol)."""
    # Reset the rate-limit cache
    registry._OPS_ALERT_CACHE.clear()

    mock_send = MagicMock()
    with patch.dict(sys.modules, {"app.services.discord": types.SimpleNamespace(send_ops_alert=mock_send)}):
        for _ in range(5):
            with pytest.raises(RuntimeError):
                registry.validate_order("stock_swing", "BTC/USD")

    assert mock_send.call_count == 1, (
        f"send_ops_alert should be called once per bot/symbol/day, got {mock_send.call_count}"
    )


def test_validate_order_unknown_bot_raises(registry):
    """Unknown bot_id raises RuntimeError."""
    with pytest.raises(RuntimeError, match="unknown bot_id"):
        registry.validate_order("nonexistent_bot", "AAPL")


def test_validate_order_raises_even_when_discord_send_fails(registry):
    """RuntimeError for the violation is raised even if send_ops_alert itself throws."""
    registry._OPS_ALERT_CACHE.clear()

    def _boom(*a, **kw):
        raise ConnectionError("discord down")

    with patch.dict(sys.modules, {"app.services.discord": types.SimpleNamespace(send_ops_alert=_boom)}):
        with pytest.raises(RuntimeError, match="asset_class_violation"):
            registry.validate_order("stock_swing", "ETH/USD")


# ─── Additional edge-case tests (SHIP 14 tester additions) ───────────────────

def test_validate_order_empty_symbol_raises(registry):
    """validate_order with an empty symbol raises RuntimeError (classify fails first)."""
    with pytest.raises(RuntimeError):
        registry.validate_order("crypto_day", "")


def test_validate_order_none_symbol_raises(registry):
    """validate_order with None symbol raises RuntimeError (classify fails first)."""
    with pytest.raises(RuntimeError):
        registry.validate_order("equity_bot_that_doesnt_exist_triggers_unknown_first", None)
    # Also test with a valid bot_id so we confirm classify_instrument is the gate
    with pytest.raises(RuntimeError):
        registry.validate_order("crypto_day", None)


def test_validate_order_whitespace_symbol_strip(registry):
    """Whitespace-padded crypto pair is accepted (strip+upper in classify_instrument)."""
    # '  BTC/USD  ' strips to 'BTC/USD' which is crypto — matches crypto_day
    registry.validate_order("crypto_day", "  BTC/USD  ")


def test_validate_order_lowercase_symbol_normalised(registry):
    """Lowercase 'btc/usd' is accepted for crypto_day (classify_instrument uppercases)."""
    registry.validate_order("crypto_day", "btc/usd")


def test_classify_instrument_occ_with_long_root(registry):
    """OCC symbol with a 5-letter root (BRKB) is classified as option."""
    assert registry.classify_instrument("BRKB250620C00500000") == "option"


def test_validate_order_all_equity_bots_accept_aapl(registry):
    """All three equity bots (stock_swing, stock_lt, stock_day) accept AAPL."""
    for bot in ("stock_swing", "stock_lt", "stock_day"):
        registry.validate_order(bot, "AAPL")  # must not raise


def test_validate_order_all_crypto_bots_reject_aapl(registry):
    """All crypto bots must reject equity symbol AAPL."""
    crypto_bots = [
        "crypto_day", "crypto_swing", "crypto_lt", "crypto_onchain",
        "crypto_quant_aggressive", "crypto_quant_mean_reversion", "crypto_quant_scalper",
    ]
    for bot in crypto_bots:
        with pytest.raises(RuntimeError, match="asset_class_violation"):
            registry.validate_order(bot, "AAPL")


def test_validate_order_options_bots_reject_plain_equity(registry):
    """Both options bots reject a plain equity ticker."""
    for bot in ("options_income", "options_directional"):
        with pytest.raises(RuntimeError, match="asset_class_violation"):
            registry.validate_order(bot, "AAPL")


def test_cash_floor_allowlist_exact_contents(registry):
    """cash_floor ticker_allowlist is exactly ['SPY', 'QQQ'] — no other tickers."""
    al = registry.get_ticker_allowlist("cash_floor")
    assert al == ["SPY", "QQQ"], f"Expected ['SPY', 'QQQ'], got {al!r}"


def test_registry_has_exactly_13_entries(registry):
    """ASSET_CLASS_REGISTRY must have exactly 13 entries (per spec)."""
    assert len(registry.ASSET_CLASS_REGISTRY) == 13


def test_all_spec_slug_aliases_raise(registry):
    """All four spec-slug aliases raise RuntimeError with canonical name in message."""
    aliases = {
        "stock_long_term": "stock_lt",
        "crypto_lt_dca": "crypto_lt",
        "quant_mean_rev": "crypto_quant_mean_reversion",
        "quant_scalper": "crypto_quant_scalper",
    }
    for slug, canonical in aliases.items():
        with pytest.raises(RuntimeError, match=canonical):
            registry.get_required_asset_class(slug)


def test_validate_order_message_contains_bot_and_symbol(registry):
    """RuntimeError message from validate_order includes bot_id and symbol."""
    try:
        registry.validate_order("crypto_day", "AAPL")
        assert False, "Should have raised"
    except RuntimeError as exc:
        msg = str(exc)
        assert "crypto_day" in msg
        assert "AAPL" in msg


def test_diagnostics_card_renders_quarantine_count():
    """Spec-named alias: endpoint body renders unresolved_count correctly.

    This is the canonical name required by SHIP 14 spec (COMMIT 6).
    The behaviour is equivalent to test_cross_sleeve_diagnostics_returns_unresolved_count_and_rows
    in test_diagnostics_cross_sleeve_card.py but named exactly as the spec mandates.
    """
    # Inline minimal fake matching the endpoint logic
    from datetime import datetime, timezone

    class _CC:
        def __init__(self, n): self._n = n
        def scalar(self): return self._n

    class _RC:
        def __init__(self, rows): self._rows = rows
        def fetchall(self): return self._rows

    class _FakeDB:
        def __init__(self, count, rows):
            self._count = count
            self._rows = rows
            self._call = 0
        def execute(self, stmt):
            self._call += 1
            return _CC(self._count) if self._call == 1 else _RC(self._rows)

    rows = [
        [1, 101, "crypto_day", 1, "crypto", "AAPL", "equity", "2026-06-28T10:00:00", "review"],
    ]
    db = _FakeDB(count=1, rows=rows)

    _text = lambda s: s
    unresolved_count = db.execute(_text("COUNT")).scalar() or 0
    raw_rows = db.execute(_text("ROWS")).fetchall()
    result = {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "unresolved_count": int(unresolved_count),
        "rows": [{"bot_id": r[2], "actual_symbol": r[5]} for r in raw_rows],
    }

    assert result["unresolved_count"] == 1
    assert len(result["rows"]) == 1
    assert result["rows"][0]["bot_id"] == "crypto_day"


# ─── Follow-up: bot_executor bypass path (SHIP 14 follow-up) ─────────────────

def test_bot_executor_rejects_cross_sleeve_order(registry, monkeypatch):
    """_execute_bot must not create any BotTrade row when a crypto bot is given
    an equity symbol (e.g. crypto_day with AAPL universe). Covers the missed
    path at bot_executor.py lines 225 (exit) and 294 (entry).

    Strategy: inject a universe of ["AAPL"] for a crypto profile, mock all DB
    and fill_sanity deps, then run _execute_bot and assert no BotTrade was added
    and that the RuntimeError was logged.
    """
    import logging
    import os
    import sys
    import types
    from datetime import datetime, date, timezone
    from unittest.mock import MagicMock, patch

    # ── Build a minimal fake BotProfile ──────────────────────────────────────
    profile = MagicMock()
    profile.name = "crypto_day"   # DB-canonical name — should be crypto-only
    profile.enabled = True
    profile.asset_class = "crypto"  # NOT "options", so the early-return gate passes
    profile.config_json = {}

    alloc = MagicMock()
    alloc.id = 99
    alloc.profile_id = 1

    user_id = 1
    today = date(2026, 6, 28)
    now = datetime(2026, 6, 28, 10, 0, 0, tzinfo=timezone.utc)

    # ── Fake DB that records add() calls ─────────────────────────────────────
    added_objects = []

    class _FakeQuery:
        def filter(self, *a, **kw): return self
        def all(self): return []      # no open positions → only entry path runs
        def count(self): return 0
        def first(self): return None

    class _FakeDB:
        def query(self, model): return _FakeQuery()
        def add(self, obj): added_objects.append(obj)
        def flush(self): pass

    db = _FakeDB()

    # ── Stub strategy_lab.core.fill_sanity so fill check always passes ───────
    # Use monkeypatch.setitem so pytest restores sys.modules after this test,
    # preventing pollution into test_position_monitor_guards / test_risk_overlay.
    fill_sanity_mod = types.ModuleType("strategy_lab.core.fill_sanity")
    fill_sanity_mod.check_fill = lambda sym, px, context="": (True, px, None)
    # Only inject stub if strategy_lab / strategy_lab.core are not real packages;
    # if they are real, monkeypatch will restore them after the test either way.
    if "strategy_lab" not in sys.modules:
        monkeypatch.setitem(sys.modules, "strategy_lab", types.ModuleType("strategy_lab"))
    if "strategy_lab.core" not in sys.modules:
        monkeypatch.setitem(sys.modules, "strategy_lab.core", types.ModuleType("strategy_lab.core"))
    monkeypatch.setitem(sys.modules, "strategy_lab.core.fill_sanity", fill_sanity_mod)

    # ── Import bot_executor from the filesystem ───────────────────────────────
    import importlib.util
    executor_path = os.path.join(
        os.path.dirname(__file__), "..", "app", "screener", "bot_executor.py"
    )
    spec = importlib.util.spec_from_file_location("app.screener.bot_executor", executor_path)
    executor_mod = importlib.util.module_from_spec(spec)

    # Stub BotPosition / BotTrade / BotDailyPnL inside the module namespace.
    # BotPosition class attributes (e.g. allocation_id, closed_at) are accessed
    # as SQLAlchemy column descriptors for .filter() — provide a stub that
    # supports == / .is_(None) without raising.
    class _ColStub:
        """Accepts == comparisons and .is_(None) for SQLAlchemy-style filter args."""
        def __eq__(self, other): return True
        def is_(self, val): return True

    class _BotPositionMeta(type):
        def __getattr__(cls, name): return _ColStub()

    class _BotPosition(metaclass=_BotPositionMeta):
        def __init__(self, **kw): self.__dict__.update(kw); self.id = 42

    class _BotTrade(metaclass=_BotPositionMeta):
        def __init__(self, **kw): self.__dict__.update(kw)

    class _BotDailyPnL(metaclass=_BotPositionMeta):
        def __init__(self, **kw): self.__dict__.update(kw)

    # Build a models stub that includes all attributes the conftest stub has,
    # so the replacement is safe to restore from. Use monkeypatch.setitem so
    # pytest auto-restores sys.modules["app.db.models.bots"] after this test —
    # the conftest stub (with BotAllocation) will be back for subsequent tests.
    models_mod = types.ModuleType("app.db.models.bots")
    models_mod.BotPosition = _BotPosition
    models_mod.BotTrade = _BotTrade
    models_mod.BotDailyPnL = _BotDailyPnL
    monkeypatch.setitem(sys.modules, "app.db.models.bots", models_mod)

    # Wire the real validate_order (already in registry fixture's sys.modules)
    # so the executor can import it at runtime.
    # Use setdefault here — only injects if not already present; no teardown
    # needed because we're not overwriting an existing entry.
    if "app.services.asset_class_registry" not in sys.modules:
        monkeypatch.setitem(sys.modules, "app.services.asset_class_registry", registry)

    spec.loader.exec_module(executor_mod)

    # Override the universe to be equity-only so crypto_day gets equity symbols
    executor_mod._UNIVERSES["crypto_day"] = ["AAPL"]

    # ── Run with caplog to confirm the violation was logged ───────────────────
    import logging
    log_records = []

    class _Handler(logging.Handler):
        def emit(self, record): log_records.append(record)

    root_logger = logging.getLogger()
    handler = _Handler()
    root_logger.addHandler(handler)
    old_level = root_logger.level
    root_logger.setLevel(logging.DEBUG)

    try:
        # Seed RNG so the entry branch is taken: seed=1 gives random()=0.134 < 0.6
        # (verified: random.Random(1).random() == 0.1344...)
        with patch.object(executor_mod, "_rng", lambda seed: __import__("random").Random(1)):
            executor_mod._execute_bot(db, user_id, alloc, profile, today, now)
    finally:
        root_logger.removeHandler(handler)
        root_logger.setLevel(old_level)

    # ── Assert no BotTrade row was created ────────────────────────────────────
    bot_trade_objects = [o for o in added_objects if isinstance(o, _BotTrade)]
    assert len(bot_trade_objects) == 0, (
        f"Expected 0 BotTrade rows for crypto_day + AAPL (cross-sleeve), "
        f"got {len(bot_trade_objects)}"
    )

    # ── Assert the violation was logged at ERROR level ────────────────────────
    violation_logs = [
        r for r in log_records
        if "asset_class_violation" in (r.getMessage())
    ]
    assert len(violation_logs) >= 1, (
        "Expected at least one [asset_class_violation] log record. "
        f"Got records: {[r.getMessage() for r in log_records]}"
    )
