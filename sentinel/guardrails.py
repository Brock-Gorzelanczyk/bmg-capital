"""
Safety guardrails — hardcoded, no env-var override.
Enforced by orchestrator before ANY fixer dispatch.
"""
from __future__ import annotations

import fnmatch
import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_CFG_PATH = Path(__file__).parent / "config" / "safe_fixes.yaml"


def _load_cfg() -> dict:
    with open(_CFG_PATH) as f:
        return yaml.safe_load(f)


def category_allowed_auto_pr(category: str) -> bool:
    cfg = _load_cfg()
    return category in cfg.get("auto_pr_allowed", [])


def path_is_blocked(file_path: str) -> bool:
    cfg = _load_cfg()
    for pattern in cfg.get("blocklist_patterns", []):
        if fnmatch.fnmatch(file_path, pattern):
            logger.warning("[guardrails] BLOCKED path: %s matches pattern %s", file_path, pattern)
            return True
    return False


def contains_trading_keywords(file_path: str) -> bool:
    """Extra defense: flag any path that looks like trading logic."""
    keywords = ["trade", "position", "order", "execution", "strategy_lab"]
    lower = file_path.lower()
    for kw in keywords:
        if kw in lower:
            return True
    return False


def validate_fix_request(category: str, file_path: str) -> tuple[bool, str]:
    """
    Returns (allowed, reason). Must return (True, '') to proceed with auto-PR.
    All checks are applied — first failure wins.
    """
    if not category_allowed_auto_pr(category):
        return False, f"category '{category}' not in auto_pr whitelist"

    if path_is_blocked(file_path):
        return False, f"path '{file_path}' matches blocklist pattern"

    if contains_trading_keywords(file_path):
        return False, f"path '{file_path}' contains trading keyword — escalate only"

    return True, ""
