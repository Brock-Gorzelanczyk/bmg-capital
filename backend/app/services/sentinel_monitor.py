"""
Sentinel integration — lightweight observation layer wired into the main backend.

Responsibilities:
  1. Startup heartbeat: post to #sentinel-ops on service start
  2. Hourly status: "👁️ Hourly status: N events observed, M dedup'd, K resolved"
  3. Log Discord channel ID on startup for env-var diagnosis
  4. Expose test-heartbeat endpoint callable from admin routes

This runs inside the main disciplined-intuition service (not a separate sentinel
service), so it uses the same DISCORD_BOT_TOKEN the signal poster already has.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

# ── counters (in-process, reset on restart) ──────────────────────────────────
_events_observed: int = 0
_events_deduped: int = 0
_events_resolved: int = 0


def increment_observed() -> None:
    global _events_observed
    _events_observed += 1


def increment_deduped() -> None:
    global _events_deduped
    _events_deduped += 1


def increment_resolved() -> None:
    global _events_resolved
    _events_resolved += 1


# ── Discord helpers ───────────────────────────────────────────────────────────

def _token() -> str:
    return os.getenv("DISCORD_BOT_TOKEN", "")


def _channel() -> str:
    return os.getenv("DISCORD_CHANNEL_ID_SENTINEL_OPS", "")


def _post_plain(text: str) -> bool:
    """Post a plain-text message to #sentinel-ops. Returns True on success."""
    token = _token()
    channel = _channel()
    if not token or not channel:
        logger.warning(
            "[sentinel] cannot post — DISCORD_BOT_TOKEN=%s DISCORD_CHANNEL_ID_SENTINEL_OPS=%s",
            "SET" if token else "MISSING",
            channel if channel else "MISSING",
        )
        return False
    url = f"https://discord.com/api/v10/channels/{channel}/messages"
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.post(
                url,
                headers={"Authorization": f"Bot {token}", "Content-Type": "application/json"},
                json={"content": text},
            )
        if resp.status_code == 429:
            logger.warning("[sentinel] Discord rate limited on sentinel-ops")
            return False
        if not resp.is_success:
            logger.warning(
                "[sentinel] Discord post failed status=%s: %s",
                resp.status_code, resp.text[:200],
            )
            return False
        return True
    except Exception as exc:
        logger.error("[sentinel] Discord post error: %s", exc)
        return False


# ── Public API ────────────────────────────────────────────────────────────────

def log_config() -> None:
    """Log resolved Discord config once at startup — helps diagnose missing env vars."""
    token = _token()
    channel = _channel()
    sentinel_enabled = os.getenv("SENTINEL_ENABLED", "false").lower() == "true"
    logger.warning(
        "[sentinel] enabled=%s discord_token=%s discord_channel=%s",
        sentinel_enabled,
        "SET" if token else "MISSING",
        channel if channel else "MISSING",
    )


def send_startup_heartbeat() -> None:
    """Post a one-time startup message to #sentinel-ops."""
    enabled = os.getenv("SENTINEL_ENABLED", "false").lower() == "true"
    if not enabled:
        logger.info("[sentinel] SENTINEL_ENABLED=false — skipping startup heartbeat")
        return

    now = datetime.now(timezone.utc).strftime("%H:%M UTC")
    ok = _post_plain(
        f"🤖 **Sentinel online** · {now}\n"
        f"> Observation mode active · `SENTINEL_ENABLED=true`\n"
        f"> Monitoring Railway builds · Discord health · App scanner"
    )
    if ok:
        logger.warning("[sentinel] startup heartbeat sent to #sentinel-ops")
    else:
        logger.warning("[sentinel] startup heartbeat failed — check Discord env vars above")


def send_hourly_status() -> None:
    """Scheduled job: post hourly status to #sentinel-ops."""
    enabled = os.getenv("SENTINEL_ENABLED", "false").lower() == "true"
    if not enabled:
        return

    now = datetime.now(timezone.utc).strftime("%H:%M UTC")
    _post_plain(
        f"👁️ **Hourly status** · {now}\n"
        f"> Observed: **{_events_observed}** · Dedup'd: **{_events_deduped}** · Resolved: **{_events_resolved}**"
    )


def send_test_heartbeat() -> dict:
    """
    Called from POST /api/admin/sentinel/test-heartbeat.
    Returns a result dict with ok/error info.
    """
    token = _token()
    channel = _channel()
    now = datetime.now(timezone.utc).strftime("%H:%M UTC")

    if not token:
        return {"ok": False, "error": "DISCORD_BOT_TOKEN not set in environment"}
    if not channel:
        return {"ok": False, "error": "DISCORD_CHANNEL_ID_SENTINEL_OPS not set in environment"}

    ok = _post_plain(f"🤖 Sentinel test heartbeat · {now}")
    if ok:
        return {"ok": True, "channel": channel, "posted_at": now}
    return {"ok": False, "error": "Discord post failed — check bot token / channel permissions"}
