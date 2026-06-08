"""Order idempotency — prevents duplicate fills within the same scan cycle."""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# In-process dedup store; keyed by idempotency hash
_seen_keys: dict[str, dict] = {}


def order_idempotency_key(bot_name: str, symbol: str, side: str, scan_ts: datetime) -> str:
    """Stable key for (bot, symbol, side, scan_minute).

    Two calls in the same minute for the same bot+symbol+side return identical
    keys, so a retry during the same scan cycle won't double-fill.
    """
    minute_str = scan_ts.strftime("%Y%m%d%H%M")
    raw = f"{bot_name}:{symbol}:{side}:{minute_str}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def is_duplicate(key: str) -> bool:
    """True if this key was already attempted in this process."""
    return key in _seen_keys


def log_order_attempt(key: str, status: str, response: dict | None = None) -> None:
    """Record an attempt so retries within the same scan cycle are suppressed."""
    _seen_keys[key] = {
        "status": status,
        "ts": datetime.now(timezone.utc).isoformat(),
        "response": response or {},
    }
    logger.debug("[idempotency] key=%s status=%s", key, status)
