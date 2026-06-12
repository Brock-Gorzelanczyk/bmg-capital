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
import urllib.request
from datetime import datetime, timedelta, timezone
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


def _get_cio_user_ids() -> set[str]:
    """Returns the set of Discord user IDs authorised to approve proposals.
    Reads CIO_DISCORD_USER_IDS (comma-separated) first, falls back to CIO_DISCORD_USER_ID."""
    multi = os.getenv("CIO_DISCORD_USER_IDS", "").strip()
    if multi:
        return {uid.strip() for uid in multi.split(",") if uid.strip()}
    single = os.getenv("CIO_DISCORD_USER_ID", "").strip()
    return {single} if single else set()


def _get_cio_user_id() -> str | None:
    ids = _get_cio_user_ids()
    return next(iter(ids), None)


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


def _record_decision(
    db: Session,
    proposal_id: str,
    decision: str,
    reason: str,
    *,
    allow_override_deferred: bool = False,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    try:
        if allow_override_deferred:
            # Allow overriding both pending and deferred states (late CIO reaction)
            db.execute(
                text("""
                    UPDATE proposal_audit
                    SET decision = :decision, decision_ts = :ts, decision_reason = :reason
                    WHERE proposal_id = :pid AND decision IN ('pending', 'deferred')
                """),
                {"decision": decision, "ts": now, "reason": reason, "pid": proposal_id},
            )
        else:
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


def _execute_proposal(db: Session, row: dict, decision: str, *, late_decision: bool = False) -> None:
    """Route an approved proposal to the right executor.

    When late_decision=True the proposal was already auto-deferred; the CIO
    reaction overrides it and the outcome is logged as 'late_decision'.
    """
    proposal_id = row["proposal_id"]
    decision_suffix = " (late override of auto-deferred)" if late_decision else ""

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
                "[proposal_handler] allocation change executed: %s ok=%s late=%s",
                proposal_id, result.get("ok"), late_decision,
            )
            _record_decision(
                db, proposal_id, "approved",
                f"CIO approved{decision_suffix}; executor {'succeeded' if result.get('ok') else 'failed: ' + result.get('reason', '')}",
                allow_override_deferred=late_decision,
            )
            return

        # Unknown type — log and skip
        logger.warning("[proposal_handler] unknown proposal type: %s", change.get("type"))
        _record_decision(
            db, proposal_id, "approved",
            f"CIO approved{decision_suffix}; no executor matched",
            allow_override_deferred=late_decision,
        )

    elif decision == "rejected":
        _record_decision(
            db, proposal_id, "rejected",
            f"CIO rejected via ❌ reaction{decision_suffix}",
            allow_override_deferred=late_decision,
        )
        try:
            from agents.bus import publish as _pub
            _pub(db, channel="proposals", from_agent="proposal_handler",
                 msg_type="rejected", subject=f"Proposal {proposal_id} rejected by CIO",
                 payload={"proposal_id": proposal_id}, priority=4)
        except Exception:
            pass

    elif decision == "deferred":
        _record_decision(
            db, proposal_id, "deferred",
            f"CIO deferred via 🕐 reaction{decision_suffix}",
            allow_override_deferred=late_decision,
        )


def run_proposal_handler(db: Session) -> dict:
    """
    Main entry point — called every 60s by APScheduler.

    Fetches pending proposals that have been posted to Discord,
    checks for CIO reactions, and routes decisions to executors.
    """
    cio_ids = _get_cio_user_ids()
    if not cio_ids:
        logger.debug("[proposal_handler] no CIO_DISCORD_USER_IDS configured, ignoring reactions")
        return {"checked": 0, "acted": 0}

    # Get pending AND deferred proposals with a message ID.
    # Deferred proposals are included so that a late CIO reaction can still
    # override the auto-deferred state and log it as a 'late_decision'.
    try:
        rows = db.execute(
            text("""
                SELECT proposal_id, posted_message_id, posted_channel_id,
                       proposed_change, decision
                FROM proposal_audit
                WHERE decision IN ('pending', 'deferred')
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
        proposal_id, message_id, channel_id, proposed_change, current_decision = row
        checked += 1
        is_deferred = current_decision == "deferred"

        for emoji, decision in _EMOJI_DECISION.items():
            reactors = _get_reactions(channel_id, message_id, _EMOJI_ENCODED[emoji])
            if cio_ids & set(reactors):
                logger.warning(
                    "[proposal_handler] CIO reacted %s on proposal %s → %s (was: %s)",
                    emoji, proposal_id, decision, current_decision,
                )
                _execute_proposal(
                    db,
                    {"proposal_id": proposal_id, "proposed_change": proposed_change},
                    decision,
                    late_decision=is_deferred,
                )
                acted += 1
                break  # first matching emoji wins; don't check others

    logger.debug("[proposal_handler] checked=%d acted=%d", checked, acted)
    return {"checked": checked, "acted": acted}


def run_auto_defer_check(db: Session) -> dict:
    """
    Runs every 5 minutes. Any proposal pending > 6h gets auto-deferred.
    Brock can still react ✅/❌ after deferral — handler logs it as 'late_decision'.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
    now = datetime.now(timezone.utc).isoformat()

    try:
        rows = db.execute(
            text("""
                SELECT proposal_id, posted_message_id, posted_channel_id, proposed_change
                FROM proposal_audit
                WHERE decision = 'pending'
                  AND generated_ts < :cutoff
                  AND posted_message_id IS NOT NULL
            """),
            {"cutoff": cutoff},
        ).fetchall()
    except Exception as exc:
        logger.warning("[auto_defer] query failed: %s", exc)
        return {"checked": 0, "deferred": 0}

    checked = len(rows)
    deferred_count = 0

    bot_token = os.getenv("DISCORD_BOT_TOKEN", "")
    try:
        from app.config import settings as _settings
        bot_token = _settings.discord_bot_token or bot_token
    except Exception:
        pass

    for row in rows:
        proposal_id, posted_message_id, posted_channel_id, proposed_change = row

        # 1. Update decision to 'deferred'
        try:
            db.execute(
                text("""
                    UPDATE proposal_audit
                    SET decision = 'deferred',
                        decision_ts = :now,
                        decision_reason = 'auto_deferred: no CIO reaction in 6h'
                    WHERE proposal_id = :pid AND decision = 'pending'
                """),
                {"now": now, "pid": proposal_id},
            )
            db.commit()
        except Exception as exc:
            logger.warning("[auto_defer] update failed for %s: %s", proposal_id, exc)
            continue

        deferred_count += 1
        logger.warning("[auto_defer] proposal %s auto-deferred (no reaction in 6h)", proposal_id)

        # 2. Post a follow-up reply to the original Discord message
        if posted_channel_id and posted_message_id and bot_token:
            try:
                payload = {
                    "content": (
                        "\U0001f550 **Auto-deferred** — No reaction in 6h. "
                        "Proposal will re-queue after 24h cooldown. "
                        "React ✅ or ❌ to override."
                    ),
                    "message_reference": {
                        "message_id": posted_message_id,
                        "fail_if_not_exists": False,
                    },
                }
                body = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(
                    f"{_DISCORD_API}/channels/{posted_channel_id}/messages",
                    data=body,
                    method="POST",
                    headers={
                        "Authorization": f"Bot {bot_token}",
                        "Content-Type": "application/json",
                        "User-Agent": "DiscordBot (https://github.com, 1.0.0)",
                    },
                )
                with urllib.request.urlopen(req, timeout=8) as resp:
                    if resp.status not in (200, 201):
                        logger.warning(
                            "[auto_defer] Discord reply failed for %s: status %s",
                            proposal_id, resp.status,
                        )
            except Exception as exc:
                logger.warning("[auto_defer] Discord reply error for %s: %s", proposal_id, exc)

        # 3. Parse bot name from proposed_change for memory
        bot_name = "unknown"
        try:
            change = proposed_change
            if isinstance(change, str):
                change = json.loads(change)
            bot_name = change.get("bot", "unknown")
        except Exception:
            pass

        # 4. Save memory for researcher
        try:
            from agents.memory import save_memory
            save_memory(
                db,
                agent_id="researcher",
                memory_type="proposal_outcome",
                key=proposal_id,
                value={"outcome": "no_response", "proposal_id": proposal_id, "bot": bot_name},
                ttl_days=30,
            )
        except Exception as exc:
            logger.warning("[auto_defer] save_memory failed for %s: %s", proposal_id, exc)

    logger.warning("[auto_defer] checked=%d deferred=%d", checked, deferred_count)
    return {"checked": checked, "deferred": deferred_count}
