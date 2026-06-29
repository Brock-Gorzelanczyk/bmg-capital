"""
T2 — No anthropic imports outside llm_client.py.

grep -rn "from anthropic|import anthropic" across backend/, sentinel/, discord-worker/
minus .venv, __pycache__, tests/, llm_client.py, and the known-whitelist files.
Must return zero hits.
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


def _grep_anthropic_imports():
    cmd = [
        "grep", "-rn",
        r"from anthropic\|import anthropic",
        "--include=*.py",
        "backend", "sentinel",
    ]
    # discord-worker may not exist; add conditionally
    dirs = ["backend", "sentinel"]
    dw = os.path.join(_REPO_ROOT, "discord-worker")
    if os.path.isdir(dw):
        dirs.append("discord-worker")

    result = subprocess.run(
        ["grep", "-rn", r"from anthropic\|import anthropic", "--include=*.py"] + dirs,
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
    )
    hits = []
    for line in result.stdout.splitlines():
        # Normalise path separator
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


def test_no_anthropic_imports_outside_llm_client():
    hits = _grep_anthropic_imports()
    assert hits == [], (
        f"Found {len(hits)} unexpected anthropic import(s) outside whitelisted files:\n"
        + "\n".join(hits[:20])
    )
