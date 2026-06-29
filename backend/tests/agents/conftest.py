"""
conftest for agents/ tests.

The parent conftest pre-mocks app.services as a bare module.
These tests import from agents.intros and patch app.services.llm_client.

IMPORTANT: pytest treats tests/agents/ as a package (because it has __init__.py)
and registers it in sys.modules['agents'], shadowing the real backend/agents/ package.

We register 'agents.intros' directly in sys.modules (from the real backend/agents/
source) without replacing sys.modules['agents'] itself, which would break pytest's
collection of test_intros.py as 'agents.test_intros'.
"""
import sys
import os
import importlib.util as _ilu

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
_AGENTS_DIR = os.path.join(_BACKEND, "agents")


def _load_real_module(dotted_name: str, abs_path: str):
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


def _make_stub(dotted_name: str):
    import types
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


# ── Fix agents.intros resolution ────────────────────────────────────────────
# pytest registers tests/agents/ as 'agents' in sys.modules. We load the REAL
# agents.intros module from backend/agents/intros.py and register it under
# 'agents.intros'. Also wire it as an attribute on the test-package sentinel
# so attribute traversal works. We do NOT replace sys.modules['agents'] since
# that would break pytest's test collection.
_intros_path = os.path.join(_AGENTS_DIR, "intros.py")
_intros = _load_real_module("agents.intros", _intros_path)
if _intros is not None:
    _test_agents = sys.modules.get("agents")
    if _test_agents is not None:
        _test_agents.intros = _intros

# ── Fix app.services.llm_client ────────────────────────────────────────────
if "app.services.discord" not in sys.modules:
    from unittest.mock import MagicMock
    _discord_stub = _make_stub("app.services.discord")
    _discord_stub.send_ops_alert = MagicMock(name="send_ops_alert")
    _wire("app.services", "discord", _discord_stub)

_llm_client = _load_real_module(
    "app.services.llm_client",
    os.path.join(_BACKEND, "app/services/llm_client.py"),
)
_wire("app.services", "llm_client", _llm_client)
