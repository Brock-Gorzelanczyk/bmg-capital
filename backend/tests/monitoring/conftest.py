"""conftest for monitoring tests.

The global conftest registers `app` as a stub types.ModuleType, which prevents
`from app.monitoring.checks.X import ...` from resolving (non-package stub).

This local conftest registers the real monitoring submodules directly into
sys.modules so the R9 tests can import the actual ai_behavior.py and vendors.py
without a live DB or network connection.
"""
import sys
import os
import importlib.util

# Add backend/ to path (global conftest already does this, but be explicit)
_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

_BASE = os.path.join(_BACKEND_DIR, "app", "monitoring")


def _load_real_module(dotted_name: str, file_path: str):
    """Load a real .py file into sys.modules under dotted_name."""
    if dotted_name in sys.modules:
        return sys.modules[dotted_name]
    spec = importlib.util.spec_from_file_location(dotted_name, file_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[dotted_name] = mod
    spec.loader.exec_module(mod)
    return mod


# Register app.config as the real module so vendors.py can do `from app.config import settings`
_app_config = _load_real_module(
    "app.config", os.path.join(_BACKEND_DIR, "app", "config.py")
)

# Register real monitoring modules so imports work even though `app` is a stub
_mon = _load_real_module("app.monitoring", os.path.join(_BASE, "__init__.py"))
_chk = _load_real_module(
    "app.monitoring.checks", os.path.join(_BASE, "checks", "__init__.py")
)
_vnd = _load_real_module(
    "app.monitoring.checks.vendors", os.path.join(_BASE, "checks", "vendors.py")
)
_aib = _load_real_module(
    "app.monitoring.checks.ai_behavior",
    os.path.join(_BASE, "checks", "ai_behavior.py"),
)

# Wire attribute access so `app.monitoring.checks.vendors` traversal works
_app_stub = sys.modules.get("app")
if _app_stub is not None:
    _app_stub.config = _app_config  # type: ignore[attr-defined]
    _app_stub.monitoring = _mon  # type: ignore[attr-defined]
_mon.checks = _chk
_chk.vendors = _vnd
_chk.ai_behavior = _aib
