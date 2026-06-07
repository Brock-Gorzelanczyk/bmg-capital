import sys
import os
import types
from unittest.mock import MagicMock

# Add backend/ to path so `strategy_lab` and `app` are importable without install
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Pre-mock the DB module hierarchy so tests can run without a live database.
# We must wire the parent ↔ child relationships (app.db = app.db_mod, etc.) so
# that __import__("app.db.session") → getattr(app, "db") → getattr(db, "session")
# resolves to the SAME object as sys.modules["app.db.session"].
# Without this, patch("app.db.session.SessionLocal") patches the wrong object.

def _make_mock_module(name: str) -> types.ModuleType:
    mod = types.ModuleType(name)
    mod.__spec__ = None
    return mod

_app = _make_mock_module("app")
_app_db = _make_mock_module("app.db")
_app_db_session = _make_mock_module("app.db.session")
_app_db_models = _make_mock_module("app.db.models")
_app_db_models_bots = _make_mock_module("app.db.models.bots")
_app_services = _make_mock_module("app.services")
_app_services_live = _make_mock_module("app.services.live_prices")
_app_services_gc = _make_mock_module("app.services.guardrail_checker")

# Wire child references so getattr traversal finds the right module
_app.db = _app_db
_app_db.session = _app_db_session
_app_db.models = _app_db_models
_app_db_models.bots = _app_db_models_bots
_app.services = _app_services
_app_services.live_prices = _app_services_live
_app_services.guardrail_checker = _app_services_gc

# Add stub attributes needed by position_monitor and runner
_app_db_session.SessionLocal = MagicMock(name="SessionLocal")
_app_db_models_bots.BotPosition = MagicMock(name="BotPosition")
_app_db_models_bots.BotAllocation = MagicMock(name="BotAllocation")
_app_db_models_bots.BotProfile = MagicMock(name="BotProfile")
_app_db_models_bots.BotTrade = MagicMock(name="BotTrade")
_app_db_models_bots.BotDailyPnL = MagicMock(name="BotDailyPnL")
_app_services_live.fetch_live_prices = MagicMock(name="fetch_live_prices")
_app_services_gc.check_guardrails = MagicMock(name="check_guardrails", return_value=(True, "ok"))

for _name, _mod in [
    ("app", _app),
    ("app.db", _app_db),
    ("app.db.session", _app_db_session),
    ("app.db.models", _app_db_models),
    ("app.db.models.bots", _app_db_models_bots),
    ("app.services", _app_services),
    ("app.services.live_prices", _app_services_live),
    ("app.services.guardrail_checker", _app_services_gc),
]:
    sys.modules.setdefault(_name, _mod)
