"""
T1 — Audit documents all Anthropic callsites.

Grep for raw Anthropic API patterns in the main code paths.
Asserts count parity: the PART 1 table has 35 callsites (some deleted, some routed).
After SHIP 4, the grep for api.anthropic.com / messages.create / Anthropic(api_key
in non-whitelist files must return ZERO hits in main code.
"""
import subprocess
import os
import pytest


_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../../../")
)

_WHITELIST = [
    "backend/app/services/llm_client.py",
    "backend/app/config.py",
    "backend/app/monitoring/checks/vendors.py",
    "backend/app/monitoring/checks/security.py",
    "backend/app/monitoring/registry.py",
    "backend/strategy_lab/core/cost_monitor.py",
    "sentinel/settings.py",
]


def _grep_raw_api_calls():
    """Grep for direct Anthropic API patterns that should not exist outside whitelist."""
    dirs = ["backend", "sentinel"]
    dw = os.path.join(_REPO_ROOT, "discord-worker")
    if os.path.isdir(dw):
        dirs.append("discord-worker")

    result = subprocess.run(
        [
            "grep", "-rn",
            r"api\.anthropic\.com\|messages\.create\|anthropic\.Anthropic\|AsyncAnthropic",
            "--include=*.py",
        ] + dirs,
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
    )

    hits = []
    for line in result.stdout.splitlines():
        skip = False
        for skip_pattern in [".venv", "__pycache__", "/tests/"]:
            if skip_pattern in line:
                skip = True
                break
        for wl in _WHITELIST:
            if wl in line:
                skip = True
                break
        if not skip:
            hits.append(line)
    return hits


def test_no_raw_anthropic_api_calls():
    """All 35 callsites must be replaced or deleted — no raw API calls in main code."""
    hits = _grep_raw_api_calls()
    assert hits == [], (
        f"Found {len(hits)} raw Anthropic API call(s) outside whitelisted files "
        f"(should be 0 after SHIP 4):\n"
        + "\n".join(hits[:20])
    )
