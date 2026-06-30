"""
conftest for llm/ tests.

The parent conftest pre-mocks app.services as a bare module.
These tests import real modules (llm_client, relay_health_monitor, etc.),
so we load them directly and register under the right dotted names.
"""
import sys
import os
import types
import importlib.util

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))


def _load_real_module(dotted_name: str, rel_path: str):
    """Load a real Python file and register it under dotted_name."""
    abs_path = os.path.join(_BACKEND, rel_path)
    if not os.path.exists(abs_path):
        return None
    if dotted_name in sys.modules:
        return sys.modules[dotted_name]
    spec = importlib.util.spec_from_file_location(dotted_name, abs_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[dotted_name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        del sys.modules[dotted_name]
        return None
    return mod


def _make_stub(dotted_name: str) -> types.ModuleType:
    if dotted_name in sys.modules:
        return sys.modules[dotted_name]
    mod = types.ModuleType(dotted_name)
    mod.__spec__ = None
    sys.modules[dotted_name] = mod
    return mod


def _wire(parent_dotted: str, child_attr: str, child_mod):
    parent = sys.modules.get(parent_dotted)
    if parent is not None and child_mod is not None:
        setattr(parent, child_attr, child_mod)


# --- app.jobs stub hierarchy ---
_app_jobs = _make_stub("app.jobs")
_app = sys.modules.get("app")
if _app is not None:
    _app.jobs = _app_jobs

# Load relay_health_monitor
_relay_hm = _load_real_module(
    "app.jobs.relay_health_monitor",
    "app/jobs/relay_health_monitor.py",
)
if _relay_hm:
    _app_jobs.relay_health_monitor = _relay_hm

# Load llm_log_retention
_log_ret = _load_real_module(
    "app.jobs.llm_log_retention",
    "app/jobs/llm_log_retention.py",
)
if _log_ret:
    _app_jobs.llm_log_retention = _log_ret

# --- app.services.llm_client ---
_llm_client = _load_real_module(
    "app.services.llm_client",
    "app/services/llm_client.py",
)
_app_services = sys.modules.get("app.services")
if _app_services is not None and _llm_client is not None:
    _app_services.llm_client = _llm_client

# --- app.services.discord stub (needed by llm_client alerts) ---
if "app.services.discord" not in sys.modules:
    _discord_stub = _make_stub("app.services.discord")
    from unittest.mock import MagicMock
    _discord_stub.send_ops_alert = MagicMock(name="send_ops_alert")
    if _app_services is not None:
        _app_services.discord = _discord_stub

# --- app.routers stub (for admin endpoint tests) ---
_app_routers = _make_stub("app.routers")
if _app is not None:
    _app.routers = _app_routers

_app_routers_admin = _make_stub("app.routers.admin")
_app_routers.admin = _app_routers_admin
