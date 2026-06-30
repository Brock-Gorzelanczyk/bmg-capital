"""
conftest for sentinel/ tests.

The parent conftest adds backend/ to sys.path. Sentinel code lives one level
above backend at the project root.

IMPORTANT: pytest treats tests/sentinel/ as a package (because it has __init__.py)
and registers it in sys.modules['sentinel'], shadowing the real sentinel package.

Rather than replacing sys.modules['sentinel'] (which would break pytest's test
collection that expects tests/sentinel/*.py to live under the 'sentinel' package
namespace), we register the real sentinel submodules we need under their dotted
names directly, which makes `from sentinel.agents.X import Y` resolve correctly.
"""
import sys
import os
import types
import importlib.util as _ilu
from unittest.mock import MagicMock

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
_SENTINEL_DIR = os.path.join(_PROJECT_ROOT, "sentinel")
_SENTINEL_AGENTS_DIR = os.path.join(_SENTINEL_DIR, "agents")


def _load_sentinel_submodule(dotted_name: str, abs_path: str):
    """Load a sentinel submodule and register it under dotted_name in sys.modules."""
    if dotted_name in sys.modules:
        return sys.modules[dotted_name]
    if not os.path.exists(abs_path):
        return None
    spec = _ilu.spec_from_file_location(dotted_name, abs_path)
    mod = _ilu.module_from_spec(spec)
    sys.modules[dotted_name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        del sys.modules[dotted_name]
        return None
    return mod


# Register sentinel.agents as a namespace/package pointing to the real agents dir
if "sentinel.agents" not in sys.modules and os.path.isdir(_SENTINEL_AGENTS_DIR):
    import types
    _agents_pkg = types.ModuleType("sentinel.agents")
    _agents_pkg.__path__ = [_SENTINEL_AGENTS_DIR]
    _agents_pkg.__package__ = "sentinel.agents"
    _agents_pkg.__spec__ = None
    sys.modules["sentinel.agents"] = _agents_pkg

    # Wire it to the test-package sentinel so attribute access works
    _test_sentinel = sys.modules.get("sentinel")
    if _test_sentinel is not None:
        _test_sentinel.agents = _agents_pkg

# Pre-load the specific agent modules the tests need
_to_load = [
    ("sentinel.agents.error_classifier",
     os.path.join(_SENTINEL_AGENTS_DIR, "error_classifier.py")),
    ("sentinel.agents.incident_classifier",
     os.path.join(_SENTINEL_AGENTS_DIR, "incident_classifier.py")),
    ("sentinel.agents.tier1_autofix",
     os.path.join(_SENTINEL_AGENTS_DIR, "tier1_autofix.py")),
]

for _dotted, _path in _to_load:
    _mod = _load_sentinel_submodule(_dotted, _path)
    if _mod is not None:
        _attr = _dotted.split(".")[-1]
        _pkg = sys.modules.get("sentinel.agents")
        if _pkg is not None:
            setattr(_pkg, _attr, _mod)

# Register a stub app.services.llm_client so patch("app.services.llm_client.call_llm")
# works in tier1_autofix tests.  The global conftest registers app.services as a stub
# types.ModuleType (non-package), so llm_client is not auto-importable.
# We inject a minimal stub; `call_llm` on this stub is a MagicMock that can be further
# patched by individual tests via patch("app.services.llm_client.call_llm").
_llm_client_stub = sys.modules.get("app.services.llm_client")
if _llm_client_stub is None:
    _llm_client_stub = types.ModuleType("app.services.llm_client")
    _llm_client_stub.call_llm = MagicMock(name="call_llm")
    _llm_client_stub.call_llm_cached = MagicMock(name="call_llm_cached")
    sys.modules["app.services.llm_client"] = _llm_client_stub
    # Wire as attribute on the app.services stub so dot-lookup resolves
    _app_services_stub = sys.modules.get("app.services")
    if _app_services_stub is not None:
        _app_services_stub.llm_client = _llm_client_stub
