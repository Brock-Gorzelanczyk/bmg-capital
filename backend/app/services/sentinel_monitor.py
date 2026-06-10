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
_cycles_complete: int = 0
_events_since_last_hb: int = 0   # resets each time we post the hourly heartbeat


def increment_observed() -> None:
    global _events_observed, _events_since_last_hb
    _events_observed += 1
    _events_since_last_hb += 1


def increment_deduped() -> None:
    global _events_deduped
    _events_deduped += 1


def increment_resolved() -> None:
    global _events_resolved
    _events_resolved += 1


def _get_cost_24h() -> float:
    """Query agent_fixes for total LLM cost in the last 24 hours."""
    try:
        from datetime import timedelta
        from sqlalchemy import func
        from app.db.session import SessionLocal
        from app.db.models.sentinel import AgentFix
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        db = SessionLocal()
        try:
            result = db.query(func.coalesce(func.sum(AgentFix.cost_usd), 0)).filter(
                AgentFix.created_at >= cutoff
            ).scalar()
            return float(result) if result else 0.0
        finally:
            db.close()
    except Exception:
        return 0.0


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


def _post_hourly_heartbeat() -> None:
    """Build and post the rich hourly heartbeat. Resets the per-hour event counter."""
    global _events_since_last_hb, _cycles_complete
    cost = _get_cost_24h()
    now = datetime.now(timezone.utc).strftime("%H:%M UTC")
    text = (
        f"💓 **Sentinel** @ {now} — "
        f"events observed (1h): **{_events_since_last_hb}**, "
        f"cost (24h): **${cost:.2f}**, "
        f"cycles complete: **{_cycles_complete}**"
    )
    _post_plain(text)
    _events_since_last_hb = 0  # reset window


def send_hourly_status() -> None:
    """APScheduler fallback — delegates to the same rich heartbeat post."""
    enabled = os.getenv("SENTINEL_ENABLED", "false").lower() == "true"
    if not enabled:
        return
    _post_hourly_heartbeat()


async def sentinel_loop() -> None:
    """
    Internal tick loop — runs every 60 s for responsiveness.
    Posts to Discord ONCE PER HOUR; individual ticks only log.
    """
    import asyncio

    TICK_S = 60
    DISCORD_EVERY_N = 60   # 60 ticks × 60 s = 3600 s = 1 hour

    enabled = os.getenv("SENTINEL_ENABLED", "false").lower() == "true"
    channel = _channel()
    logger.warning(
        "[sentinel] loop starting — enabled=%s channel=%s tick=%ds discord_every=%d ticks",
        enabled, channel if channel else "MISSING", TICK_S, DISCORD_EVERY_N,
    )

    global _cycles_complete
    tick = 0
    while True:
        await asyncio.sleep(TICK_S)
        tick += 1
        _cycles_complete += 1
        logger.debug("[sentinel] tick=%d cycles=%d", tick, _cycles_complete)

        if enabled and channel and tick % DISCORD_EVERY_N == 0:
            await asyncio.to_thread(_post_hourly_heartbeat)


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
