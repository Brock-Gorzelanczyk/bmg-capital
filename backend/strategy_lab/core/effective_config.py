"""Effective config resolution — YAML profile merged with DB overrides.

Dot-notation keys like "risk.deployment_target_pct" map into nested dicts.
A 5-second TTL cache prevents hammering the DB when many strategies in one
scan cycle all call load_effective_config for the same bot.
"""
from __future__ import annotations

import copy
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

_CACHE_TTL = 5.0  # seconds
_cache: dict[str, dict] = {}   # {bot_id: {"ts": float, "data": dict}}


def load_effective_config(bot_id: str, db) -> dict:
    """Return the merged config for bot_id, with overrides winning over YAML.

    Uses a 5-second TTL cache keyed by bot_id so the DB is hit at most once
    per scan cycle per bot.
    """
    entry = _cache.get(bot_id)
    if entry and time.time() - entry["ts"] < _CACHE_TTL:
        return entry["data"]

    from strategy_lab.seeds import load_profile
    cfg = copy.deepcopy(load_profile(bot_id))

    try:
        from app.db.models.bot_config import BotConfigOverride
        from sqlalchemy.orm import Session
        rows = (
            db.query(BotConfigOverride)
            .filter(BotConfigOverride.bot_id == bot_id)
            .all()
        )
        for row in rows:
            _set_nested(cfg, row.key, row.value)
        if rows:
            logger.debug(
                "[effective_config] %s — applied %d overrides: %s",
                bot_id, len(rows), [r.key for r in rows],
            )
    except Exception as exc:
        logger.warning("[effective_config] %s — override fetch failed: %s", bot_id, exc)

    _cache[bot_id] = {"ts": time.time(), "data": cfg}
    return cfg


def invalidate_cache(bot_id: str) -> None:
    """Evict a bot's cached config so the next call re-reads from DB."""
    _cache.pop(bot_id, None)


def _set_nested(cfg: dict, key: str, value: Any) -> None:
    """Write value into cfg at dot-separated key path (mutates in place)."""
    parts = key.split(".")
    d = cfg
    for part in parts[:-1]:
        if part not in d or not isinstance(d[part], dict):
            d[part] = {}
        d = d[part]
    d[parts[-1]] = value
