"""Critical-alert channel — severity-filtered, always-on by default.

Brock 2026-08-10: DISCORD_ENABLED=false + DISCORD_OPS_ALERTS_ENABLED=false
were both flipped weeks ago to silence noise. Result: every auto-action
since (I2, I3, I18) has been silent by construction — an auto-action
with no notification path is worse than no auto-action, because it
creates false confidence.

Fix: this module is a dedicated CRITICAL-only channel that BYPASSES
both existing kill switches. Independent enable via CRITICAL_ALERTS_ENABLED
(default true). Categories are hardcoded — no free-form messages, so
callers can't sneak noise into this channel.

Categories (severity filter — only these post):
  AUTO_PAUSE          — invariant auto-action paused a sleeve
  INVARIANT_RED_STALE — invariant red > 24h without resolution
  DISK_HIGH           — /data > 80% used
  SIM_FILL_DETECTED   — I3 red (sim trade in 24h window)
  MANUAL_TEST         — test-alert endpoint to verify delivery

Anything not in this list DOES NOT belong here. Use send_ops_alert()
for warn/info; that's the noise-muted channel.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

CATEGORIES = (
    "AUTO_PAUSE",
    "INVARIANT_RED_STALE",
    "DISK_HIGH",
    "SIM_FILL_DETECTED",
    "MANUAL_TEST",
)


def _enabled() -> bool:
    return os.getenv("CRITICAL_ALERTS_ENABLED", "true").strip().lower() != "false"


def _webhook_url() -> str:
    # Uses existing ALERT_WEBHOOK_URL (ops channel). Explicitly does NOT
    # check DISCORD_ENABLED / DISCORD_OPS_ALERTS_ENABLED — critical bypasses.
    return os.getenv("ALERT_WEBHOOK_URL", "").strip()


_COLOR_RED = 0xE53935


def send_critical(
    *,
    category: str,
    title: str,
    message: str,
    source: str,
    fields: Optional[list[dict]] = None,
) -> bool:
    """Fire a critical alert. Bypasses DISCORD_ENABLED and DISCORD_OPS_ALERTS_ENABLED.

    Only posts if:
      1. CRITICAL_ALERTS_ENABLED != "false" (default: enabled)
      2. category is in CATEGORIES (hardcoded severity filter — anti-noise)
      3. ALERT_WEBHOOK_URL is set

    Returns True on 2xx, False otherwise (never raises).
    """
    if category not in CATEGORIES:
        logger.warning("[critical-alert] rejected — unknown category %r (allowed: %s)",
                       category, ", ".join(CATEGORIES))
        return False
    if not _enabled():
        logger.warning("[critical-alert] SUPPRESSED (CRITICAL_ALERTS_ENABLED=false): [%s] %s",
                       category, title)
        return False
    url = _webhook_url()
    if not url:
        logger.error("[critical-alert] no ALERT_WEBHOOK_URL configured — [%s] %s DROPPED",
                     category, title)
        return False

    embed = {
        "title": f"[CRITICAL:{category}] {title}",
        "description": message[:1900],
        "color": _COLOR_RED,
        "footer": {"text": f"BMG Capital · CRITICAL · {source}"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if fields:
        embed["fields"] = fields[:20]

    try:
        import httpx
        with httpx.Client(timeout=5) as client:
            resp = client.post(url, json={"embeds": [embed]})
            if resp.status_code in (200, 204):
                logger.warning("[critical-alert] delivered [%s] %s", category, title)
                return True
            logger.error("[critical-alert] webhook returned %s: %s",
                         resp.status_code, resp.text[:200])
            return False
    except Exception as exc:
        logger.error("[critical-alert] webhook failed: %s", exc)
        return False
