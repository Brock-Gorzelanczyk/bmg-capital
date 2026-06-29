"""
Relay health monitor — SHIP 3.

Polls RELAY_URL/health every 5 minutes.
After 30 consecutive minutes down (>= 6 failures at 5-min cadence),
posts a severity="critical" ops alert.
Debounces repeat alert to 60 minutes.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory state (reset on process restart)
# ---------------------------------------------------------------------------

_consecutive_failures: int = 0
_offline_since: Optional[datetime] = None
_last_alert_sent: Optional[datetime] = None

# 6 consecutive failures × 5-min cadence = 30 minutes down
_ALERT_AFTER_N_FAILURES: int = 6
_ALERT_DEBOUNCE_MINUTES: int = 60


def check_relay_health() -> dict:
    """
    GET RELAY_URL/health with 10s timeout. Track consecutive failures.
    Post ops alert after 30 min down (>= 6 consecutive failures at 5-min cadence).
    Debounce repeat alert to 60 min.

    Returns dict with keys: ok, consecutive_failures, offline_since, alert_sent.
    """
    global _consecutive_failures, _offline_since, _last_alert_sent

    import os
    relay_url = os.getenv("RELAY_URL", "").rstrip("/")

    if not relay_url:
        logger.debug("[relay_health] RELAY_URL not set — skipping health check")
        return {"ok": False, "skipped": True, "reason": "RELAY_URL not configured"}

    try:
        resp = httpx.get(f"{relay_url}/health", timeout=10)
        resp.raise_for_status()
        # Healthy — reset failure count
        if _consecutive_failures > 0:
            logger.info(
                "[relay_health] Relay back online after %d consecutive failures",
                _consecutive_failures,
            )
        _consecutive_failures = 0
        _offline_since = None
        return {"ok": True, "consecutive_failures": 0, "alert_sent": False}

    except Exception as exc:
        _consecutive_failures += 1
        now = datetime.now(timezone.utc)

        if _offline_since is None:
            _offline_since = now
            logger.warning("[relay_health] Relay health check failed (attempt 1): %s", exc)
        else:
            logger.warning(
                "[relay_health] Relay health check failed (consecutive=%d): %s",
                _consecutive_failures, exc,
            )

        alert_sent = False
        if _consecutive_failures >= _ALERT_AFTER_N_FAILURES:
            # Check debounce
            should_alert = (
                _last_alert_sent is None
                or (now - _last_alert_sent) >= timedelta(minutes=_ALERT_DEBOUNCE_MINUTES)
            )
            if should_alert:
                _send_relay_down_alert(now)
                _last_alert_sent = now
                alert_sent = True

        return {
            "ok": False,
            "consecutive_failures": _consecutive_failures,
            "offline_since": _offline_since.isoformat() if _offline_since else None,
            "alert_sent": alert_sent,
        }


def _send_relay_down_alert(now: datetime) -> None:
    """Post severity='critical' ops alert for relay downtime > 30 min."""
    try:
        from app.services.discord import send_ops_alert

        offline_since = _offline_since or now
        minutes_down = int((now - offline_since).total_seconds() / 60)

        send_ops_alert(
            severity="critical",
            title="LLM relay offline > 30 min",
            message=(
                f"Relay health check failing for {minutes_down} min. "
                f"No LLM calls executing across the agent fleet. Mac may be asleep. "
                f"To investigate: check cloudflared tunnel list on Mac. "
                f"To resolve: wake Mac, or flip FALLBACK_TO_API=true in Railway "
                f"(will bill at $5/day cap)."
            ),
            source="relay_health_monitor",
            fields=[
                {"name": "Affected", "value": "All agent fleet, Copilot, Sentinel", "inline": True},
                {"name": "Offline since", "value": offline_since.isoformat(), "inline": True},
            ],
        )
        logger.critical(
            "[relay_health] Ops alert sent: relay offline %d min (since %s)",
            minutes_down, offline_since.isoformat(),
        )
    except Exception as e:
        logger.error("[relay_health] Failed to send ops alert: %s", e)


def reset_state() -> None:
    """Reset in-memory state — used by tests."""
    global _consecutive_failures, _offline_since, _last_alert_sent
    _consecutive_failures = 0
    _offline_since = None
    _last_alert_sent = None
