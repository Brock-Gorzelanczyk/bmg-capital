"""
conftest for services/ tests.

The parent conftest pre-mocks app.services as a bare module.
These tests import real modules from app.services (llm_client, robo_prompt_parser,
robo_templates), so we load and register them under the correct dotted names.
"""
import sys
import os
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


# --- app.services.discord stub (needed by llm_client alerts) ---
if "app.services.discord" not in sys.modules:
    from unittest.mock import MagicMock
    _discord_stub = _make_stub("app.services.discord")
    _discord_stub.send_ops_alert = MagicMock(name="send_ops_alert")
    _wire("app.services", "discord", _discord_stub)

# --- app.services.llm_client (real module) ---
_llm_client = _load_real_module(
    "app.services.llm_client",
    "app/services/llm_client.py",
)
_wire("app.services", "llm_client", _llm_client)

# --- app.services.robo_prompt_parser (real module) ---
_robo_parser = _load_real_module(
    "app.services.robo_prompt_parser",
    "app/services/robo_prompt_parser.py",
)
_wire("app.services", "robo_prompt_parser", _robo_parser)

# --- app.services.robo_templates (real module) ---
_robo_templates = _load_real_module(
    "app.services.robo_templates",
    "app/services/robo_templates.py",
)
_wire("app.services", "robo_templates", _robo_templates)
