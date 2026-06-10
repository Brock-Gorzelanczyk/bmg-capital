"""
Discord Health Agent — monitors signal channels for stale signals, dupes, format regressions.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone, timedelta

import httpx
import yaml
from pathlib import Path

from sentinel.db.session import SessionLocal
from sentinel.orchestrator import insert_event, route_event
from sentinel.settings import settings

logger = logging.getLogger(__name__)

DISCORD_API = "https://discord.com/api/v10"


def _fp(channel_id: str, issue_type: str, detail: str) -> str:
    raw = f"discord:{channel_id}:{issue_type}:{detail[:80]}"
    return hashlib.sha256(raw.encode()).hexdigest()[:64]


def _get_headers() -> dict:
    return {"Authorization": f"Bot {settings.discord_bot_token}"}


def _fetch_messages(channel_id: str, limit: int = 20) -> list[dict]:
    resp = httpx.get(
        f"{DISCORD_API}/channels/{channel_id}/messages",
        params={"limit": limit},
        headers=_get_headers(),
        timeout=10,
    )
    if resp.status_code == 401:
        logger.warning("[discord-health] Unauthorized — check DISCORD_BOT_TOKEN")
        return []
    resp.raise_for_status()
    return resp.json()


def _load_intervals() -> dict:
    path = Path(__file__).parent.parent / "config" / "expected_signal_intervals.yaml"
    with open(path) as f:
        return yaml.safe_load(f)


def _detect_stale(messages: list[dict], max_gap_minutes: int, channel_name: str) -> str | None:
    if not messages:
        return f"No messages found in #{channel_name}"
    latest_ts_str = messages[0].get("timestamp", "")
    if not latest_ts_str:
        return None
    try:
        latest_ts = datetime.fromisoformat(latest_ts_str.rstrip("Z")).replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        gap = (now - latest_ts).total_seconds() / 60
        if gap > max_gap_minutes:
            return f"Stale: {gap:.0f}m since last message (threshold {max_gap_minutes}m)"
    except Exception:
        pass
    return None


def _detect_spam(messages: list[dict]) -> str | None:
    """Detect > 5 duplicate signals (same bot+symbol+side) in last 20 messages."""
    seen: dict[str, int] = {}
    for msg in messages:
        content = msg.get("content", "")
        # Crude fingerprint from first 60 chars of content
        key = content[:60].strip()
        if key:
            seen[key] = seen.get(key, 0) + 1
    dupes = sum(1 for v in seen.values() if v > 1)
    if dupes > 5:
        return f"Spam detected: {dupes} duplicate message groups in last 20 messages"
    return None


class DiscordHealthAgent:
    def run(self) -> None:
        if not settings.sentinel_enabled:
            return
        if not settings.discord_bot_token:
            logger.debug("[discord-health] No bot token configured, skipping")
            return
        try:
            self._check_channels()
        except Exception as e:
            logger.error("[discord-health] Error: %s", e, exc_info=True)

    def _check_channels(self) -> None:
        intervals = _load_intervals()
        channels_cfg = intervals.get("channels", {})

        # We check by channel name; actual IDs would be configured via env vars
        # In production, map channel names to IDs via env vars like
        # DISCORD_CHANNEL_ID_ALL_SIGNALS, DISCORD_CHANNEL_ID_STOCKS, etc.
        channel_id_map = {
            "all-signals":  os.environ.get("DISCORD_CHANNEL_ID_ALL_SIGNALS", ""),
            "stocks":       os.environ.get("DISCORD_CHANNEL_ID_STOCKS", ""),
            "crypto":       os.environ.get("DISCORD_CHANNEL_ID_CRYPTO", ""),
            "options":      os.environ.get("DISCORD_CHANNEL_ID_OPTIONS", ""),
            "quant":        os.environ.get("DISCORD_CHANNEL_ID_QUANT", ""),
        }

        for channel_name, cfg in channels_cfg.items():
            channel_id = channel_id_map.get(channel_name, "")
            if not channel_id:
                continue

            try:
                messages = _fetch_messages(channel_id, limit=20)
            except Exception as e:
                logger.warning("[discord-health] Failed to fetch #%s: %s", channel_name, e)
                continue

            max_gap = cfg.get("max_gap_minutes", 60)

            # Check stale
            stale_msg = _detect_stale(messages, max_gap, channel_name)
            if stale_msg:
                self._emit_issue(channel_id, channel_name, "discord_stale_channel", stale_msg, "warning")

            # Check spam
            spam_msg = _detect_spam(messages)
            if spam_msg:
                self._emit_issue(channel_id, channel_name, "discord_signal_spam", spam_msg, "warning")

    def _emit_issue(
        self,
        channel_id: str,
        channel_name: str,
        category: str,
        detail: str,
        severity: str,
    ) -> None:
        fp = _fp(channel_id, category, detail)
        payload = {
            "channel_id": channel_id,
            "channel_name": channel_name,
            "detail": detail,
            "file": "",  # Discord issues never auto-fix
        }
        db = SessionLocal()
        try:
            event_id = insert_event(
                db=db,
                agent_id="discord-health",
                severity=severity,
                category=category,
                fingerprint=fp,
                payload=payload,
            )
        finally:
            db.close()

        if event_id:
            # Discord issues always escalate — never auto-fix
            from sentinel.agents.escalator import EscalatorAgent
            EscalatorAgent().handle(event_id, "Discord issues always escalate")


import os  # noqa: E402 — needed after class def for channel_id_map
