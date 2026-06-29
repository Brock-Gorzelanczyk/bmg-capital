"""
Human Escalator Agent — packages issues as paste-readys and posts to #sentinel-ops.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import text

from sentinel.db.session import SessionLocal
from sentinel.settings import settings

logger = logging.getLogger(__name__)

SONNET = "claude-sonnet-4-6"


def _post_discord(msg: str) -> None:
    if not settings.discord_sentinel_channel_id:
        logger.debug("[escalator] No Discord channel configured, skipping post")
        return
    try:
        resp = httpx.post(
            f"https://discord.com/api/v10/channels/{settings.discord_sentinel_channel_id}/messages",
            json={"content": msg[:2000]},
            headers={"Authorization": f"Bot {settings.discord_bot_token}"},
            timeout=10,
        )
        resp.raise_for_status()
    except Exception as e:
        logger.warning("[escalator] Discord post failed: %s", e)


class EscalatorAgent:
    def handle(self, event_id: int, reason: str) -> None:
        db = SessionLocal()
        try:
            event = db.execute(text("""
                SELECT id, agent_id, severity, category, payload, detected_at
                FROM agent_events WHERE id = :id
            """), {"id": event_id}).fetchone()

            if not event:
                logger.warning("[escalator] Event #%d not found", event_id)
                return

            # Check if escalation already exists
            existing = db.execute(text("""
                SELECT id FROM agent_escalations WHERE event_id = :eid
            """), {"eid": event_id}).fetchone()
            if existing:
                logger.debug("[escalator] Escalation already exists for event #%d", event_id)
                return

            payload = event.payload if isinstance(event.payload, dict) else json.loads(event.payload)
            paste_ready = self._draft_paste_ready(event, payload, reason)

            # Insert escalation
            esc_row = db.execute(text("""
                INSERT INTO agent_escalations (event_id, paste_ready, sent_to_discord)
                VALUES (:eid, :paste, false)
                RETURNING id
            """), {"eid": event_id, "paste": paste_ready}).fetchone()
            esc_id = esc_row[0]

            # Mark event escalated
            db.execute(text("""
                UPDATE agent_events SET state = 'escalated' WHERE id = :id
            """), {"id": event_id})
            db.commit()

            # Post to Discord
            severity = event.severity
            category = event.category
            preview = paste_ready[:200].replace("\n", " ")
            discord_msg = (
                f"@here **{severity.upper()} escalation** from Sentinel\n"
                f"Event #{event_id} · `{category}`\n"
                f"> {reason}\n"
                f"Preview: {preview}…\n"
                f"→ Run `/sentinel claim {event_id}` to view full paste-ready"
            )
            _post_discord(discord_msg)

            # Mark as sent
            db.execute(text("""
                UPDATE agent_escalations SET sent_to_discord = true, sent_at = NOW()
                WHERE id = :id
            """), {"id": esc_id})
            db.commit()

            logger.info("[escalator] Escalation #%d posted for event #%d", esc_id, event_id)

        except Exception as e:
            logger.error("[escalator] Failed for event #%d: %s", event_id, e, exc_info=True)
        finally:
            db.close()

    def _draft_paste_ready(self, event, payload: dict, reason: str) -> str:
        """Draft paste-ready via relay with 24h cache (SHIP 3 — no direct Anthropic SDK)."""
        import hashlib
        try:
            from app.services.llm_client import call_llm_cached
            context = (
                f"Event #{event.id}\n"
                f"Agent: {event.agent_id}\n"
                f"Severity: {event.severity}\n"
                f"Category: {event.category}\n"
                f"Escalation reason: {reason}\n"
                f"Detected: {event.detected_at}\n"
                f"Payload: {json.dumps(payload, indent=2)[:1500]}"
            )
            stack_hash = hashlib.sha256(context.encode()).hexdigest()[:16]
            return call_llm_cached(
                model=SONNET,
                prompt=context,
                system_prompt=(
                    "You are drafting a clear, actionable paste-ready for a developer to send to Claude Code. "
                    "Be specific about file, line number, and the exact fix approach. "
                    "Format: start with the file path and error, then context, then a precise fix instruction. "
                    "Under 500 words. No fluff."
                ),
                max_tokens=600,
                ttl_seconds=86400,
                cache_key_extra=f"{event.category}_{stack_hash}",
                agent_name="escalator",
            )
        except Exception as e:
            logger.warning("[escalator] LLM draft failed, using raw context: %s", e)
            return (
                f"SENTINEL ESCALATION — Event #{event.id}\n"
                f"Category: {event.category}\n"
                f"Reason: {reason}\n"
                f"File: {payload.get('file', 'unknown')}\n"
                f"Error: {payload.get('error_text') or payload.get('error_block', '')[:500]}\n"
            )
