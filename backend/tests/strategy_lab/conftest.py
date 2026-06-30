"""
conftest for strategy_lab/ tests.

CRITICAL: Do NOT register stub modules under strategy_lab.* names at module
scope. The real strategy_lab package is on sys.path (backend/ is added by
the parent conftest). Any stub registration under strategy_lab.core breaks
test_concentration_gate.py and test_position_monitor_guards.py.

We load trade_journal_template by ensuring the real package hierarchy is
imported first, then loading the file normally. If the real import fails
for any reason, tests in this subdir will be skipped individually.
"""
import sys
import os

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))

# Ensure backend/ is on path so real strategy_lab package is importable
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

# Import the real strategy_lab package hierarchy so it's in sys.modules
# BEFORE any stub could shadow it. This ensures test_quant_strategies.py,
# test_concentration_gate.py, etc. all find the real modules.
try:
    import strategy_lab  # noqa: F401
    import strategy_lab.core  # noqa: F401
    import strategy_lab.core.expert  # noqa: F401
    import strategy_lab.core.expert.trade_journal_template  # noqa: F401
except ImportError:
    # If real modules fail to import here, tests using them will error
    # individually which is the right behaviour.
    pass
