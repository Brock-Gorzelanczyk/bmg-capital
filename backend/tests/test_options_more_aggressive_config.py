"""Regression: options bot config locked to Brock's 2026-07-01 "more
aggressive, less cash per position" tuning.

Guards against silent drift on 4 knobs:
  1. options_income   composite_threshold == 30
  2. options_directional composite_threshold == 30
  3. options_income   position_size_pct   == 8.0
  4. options_directional position_size_pct == 8.0
  5. runner.py OPTIONS_MAX_NOTIONAL_PCT == 0.03
  6. Neither profile has max_concurrent_positions (removed the 2026-06-24
     concentration override so position_cap governs concurrency instead)

If Brock later says "back to conservative" the YAML values can be raised
back — this test locks the CURRENT approved values so a drive-by edit
doesn't quietly loosen or tighten them.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "backend"
PROFILES = BACKEND / "strategy_lab" / "profiles"


def _load_profile(name: str) -> dict:
    return yaml.safe_load((PROFILES / f"{name}.yaml").read_text())


def test_options_income_more_aggressive_config():
    cfg = _load_profile("options_income")
    assert cfg["composite_threshold"] == 30, (
        f"options_income.composite_threshold must be 30 per 2026-07-01 tuning; "
        f"got {cfg['composite_threshold']}"
    )
    assert cfg["position_size_pct"] == 8.0, (
        f"options_income.position_size_pct must be 8.0; got {cfg['position_size_pct']}"
    )
    assert cfg["position_cap"] == 15, (
        f"options_income.position_cap must be 15; got {cfg['position_cap']}"
    )
    assert "max_concurrent_positions" not in cfg, (
        "options_income must NOT have max_concurrent_positions (2026-06-24 "
        "concentration override was removed 2026-07-01)"
    )


def test_options_directional_more_aggressive_config():
    cfg = _load_profile("options_directional")
    assert cfg["composite_threshold"] == 30
    assert cfg["position_size_pct"] == 8.0
    assert cfg["position_cap"] == 15
    assert "max_concurrent_positions" not in cfg


def test_runner_options_max_notional_pct_is_three_percent():
    """runner.py's hard notional cap must be 3% per 2026-07-01 tuning."""
    src = (BACKEND / "strategy_lab" / "runner.py").read_text()
    m = re.search(r"OPTIONS_MAX_NOTIONAL_PCT\s*=\s*([0-9.]+)", src)
    assert m is not None, "OPTIONS_MAX_NOTIONAL_PCT constant missing"
    val = float(m.group(1))
    assert val == 0.03, (
        f"OPTIONS_MAX_NOTIONAL_PCT must be 0.03 (3% sleeve cap for smaller "
        f"positions per Brock 2026-07-01); got {val}"
    )
