"""
Proposal reaction handler — polls Discord for ✅ / ❌ / 🕐 reactions
on #queen-proposals messages and routes to the appropriate executor.

Called by APScheduler every 60 seconds.
Reads CIO_DISCORD_USER_ID env var to identify the authorised approver.
If the env var is not set, reactions are observed but ignored (logged only).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from urllib.parse import quote

import httpx

from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)

# Reaction emoji → decision string
_EMOJI_DECISION = {
    "✅": "approved",
    "❌": "rejected",
    "🕐": "deferred",
}

# URL-encoded emoji for Discord API route
_EMOJI_ENCODED = {
    "✅": "%E2%9C%85",
    "❌": "%E2%9D%8C",
    "🕐": "%F0%9F%95%90",
}

_DISCORD_API = "https://discord.com/api/v10"


def _get_bot_headers() -> dict:
    token = os.getenv("DISCORD_BOT_TOKEN", "")
    try:
        from app.config import settings
        token = settings.discord_bot_token or token
    except Exception:
        pass
    return {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json",
        "User-Agent": "DiscordBot (https://github.com/BMG-Capital/bmg-capital, 1.0.0)",
    }


def _get_cio_user_id() -> str | None:
    return os.getenv("CIO_DISCORD_USER_ID", "").strip() or None


def _get_reactions(channel_id: str, message_id: str, emoji_encoded: str) -> list[str]:
    """Return list of user IDs who reacted with this emoji. Empty list on failure."""
    try:
        url = f"{_DISCORD_API}/channels/{channel_id}/messages/{message_id}/reactions/{emoji_encoded}"
        resp = httpx.get(url, headers=_get_bot_headers(), timeout=8)
        if resp.status_code == 404:
            return []
        if not resp.is_success:
            logger.debug("[proposal_handler] reactions fetch failed: %s", resp.status_code)
            return []
        return [str(u["id"]) for u in resp.json()]
    except Exception as exc:
        logger.debug("[proposal_handler] reactions error: %s", exc)
        return []


def _record_decision(db: Session, proposal_id: str, decision: str, reason: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    try:
        db.execute(
            text("""
                UPDATE proposal_audit
                SET decision = :decision, decision_ts = :ts, decision_reason = :reason
                WHERE proposal_id = :pid AND decision = 'pending'
            """),
            {"decision": decision, "ts": now, "reason": reason, "pid": proposal_id},
        )
        db.commit()
    except Exception as exc:
        logger.warning("[proposal_handler] record_decision failed: %s", exc)


def _execute_proposal(db: Session, row: dict, decision: str) -> None:
    """Route an approved proposal to the right executor."""
    proposal_id = row["proposal_id"]

    if decision == "approved":
        change = row["proposed_change"]
        if isinstance(change, str):
            try:
                change = json.loads(change)
            except Exception:
                change = {}

        if change.get("type") == "allocation_change":
            from agents.executors.execute_allocation_change import execute_allocation_change
            result = execute_allocation_change(
                db,
                proposal_id=proposal_id,
                bot_name=change["bot"],
                proposed_pct=float(change["proposed_value"]),
            )
            logger.warning(
                "[proposal_handler] allocation change executed: %s ok=%s",
                proposal_id, result.get("ok"),
            )
            _record_decision(
                db, proposal_id, "approved",
                f"CIO approved; executor {'succeeded' if result.get('ok') else 'failed: ' + result.get('reason', '')}",
            )
            return

        # Unknown type — log and skip
        logger.warning("[proposal_handler] unknown proposal type: %s", change.get("type"))
        _record_decision(db, proposal_id, "approved", "CIO approved; no executor matched")

    elif decision == "rejected":
        _record_decision(db, proposal_id, "rejected", "CIO rejected via ❌ reaction")
        try:
            from agents.bus import publish as _pub
            _pub(db, channel="proposals", from_agent="proposal_handler",
                 msg_type="rejected", subject=f"Proposal {proposal_id} rejected by CIO",
                 payload={"proposal_id": proposal_id}, priority=4)
        except Exception:
            pass

    elif decision == "deferred":
        _record_decision(db, proposal_id, "deferred", "CIO deferred via 🕐 reaction")


def run_proposal_handler(db: Session) -> dict:
    """
    Main entry point — called every 60s by APScheduler.

    Fetches pending proposals that have been posted to Discord,
    checks for CIO reactions, and routes decisions to executors.
    """
    cio_id = _get_cio_user_id()
    if not cio_id:
        logger.debug("[proposal_handler] no CIO_DISCORD_USER_ID configured, ignoring reactions")
        return {"checked": 0, "acted": 0}

    # Get pending proposals with a message ID
    try:
        rows = db.execute(
            text("""
                SELECT proposal_id, posted_message_id, posted_channel_id,
                       proposed_change
                FROM proposal_audit
                WHERE decision = 'pending'
                  AND posted_message_id IS NOT NULL
                  AND posted_channel_id IS NOT NULL
                ORDER BY generated_ts DESC
                LIMIT 20
            """)
        ).fetchall()
    except Exception as exc:
        logger.warning("[proposal_handler] query failed: %s", exc)
        return {"checked": 0, "acted": 0}

    checked = 0
    acted = 0

    for row in rows:
        proposal_id, message_id, channel_id, proposed_change = row
        checked += 1

        for emoji, decision in _EMOJI_DECISION.items():
            reactors = _get_reactions(channel_id, message_id, _EMOJI_ENCODED[emoji])
            if cio_id in reactors:
                logger.warning(
                    "[proposal_handler] CIO reacted %s on proposal %s → %s",
                    emoji, proposal_id, decision,
                )
                _execute_proposal(
                    db,
                    {"proposal_id": proposal_id, "proposed_change": proposed_change},
                    decision,
                )
                acted += 1
                break  # first matching emoji wins; don't check others

    logger.debug("[proposal_handler] checked=%d acted=%d", checked, acted)
    return {"checked": checked, "acted": acted}
