"""AQA proposal writer: persists proposals to DB + posts to Discord.

Functions:
  write_proposal(...) -> int         -- insert row into aqa_proposals, return id
  post_to_discord(proposal_dict)     -- POST to DISCORD_WH_AQA_PROPOSALS webhook
  mark_posted(db, id, message_id)    -- update posted_at + discord_message_id

Rules:
  - NEVER raises on Discord failures; proposal persists to DB regardless.
  - Uses dedicated DISCORD_WH_AQA_PROPOSALS webhook (not send_ops_alert, not signal hooks).
  - Truncates llm_response_md at 1900 chars for Discord embed description cap.
  - context_summary JSON-serialized with default=str (handles datetime/Decimal).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_DISCORD_EMBED_COLOR = 16760576  # amber / orange
_EMBED_DESC_MAX = 1900


def write_proposal(
    db: Session,
    cycle_id: str,
    issue_tags: list[str],
    llm_response_md: str,
    context_summary: dict,
) -> int:
    """Insert row into aqa_proposals. Return the new proposal id."""
    issue_tags_json = json.dumps(issue_tags)
    context_summary_json = json.dumps(context_summary, default=str)

    result = db.execute(
        text(
            "INSERT INTO aqa_proposals "
            "(cycle_id, issue_tags, llm_response_md, context_summary) "
            "VALUES (:cycle_id, :issue_tags, :llm_response_md, :context_summary)"
        ),
        {
            "cycle_id": cycle_id,
            "issue_tags": issue_tags_json,
            "llm_response_md": llm_response_md,
            "context_summary": context_summary_json,
        },
    )
    db.commit()

    new_id = result.lastrowid
    logger.info(
        "[aqa-proposal] wrote proposal id=%d cycle=%s tags=%s response_len=%d",
        new_id,
        cycle_id,
        issue_tags,
        len(llm_response_md),
    )
    return new_id


def post_to_discord(proposal_dict: dict) -> Optional[str]:
    """Post proposal to DISCORD_WH_AQA_PROPOSALS webhook.

    proposal_dict shape: {id, cycle_id, issue_tags (list), llm_response_md, created_at}.
    Returns Discord message_id on success, None on failure (no webhook, network error, non-2xx).
    NEVER raises.
    """
    webhook_url = os.getenv("DISCORD_WH_AQA_PROPOSALS", "").strip()
    if not webhook_url:
        logger.warning(
            "[aqa-proposal] DISCORD_WH_AQA_PROPOSALS not set -- "
            "proposal #%s persisted to DB only",
            proposal_dict.get("id"),
        )
        return None

    proposal_id = proposal_dict.get("id", "?")
    cycle_id = proposal_dict.get("cycle_id", "")
    issue_tags: list = proposal_dict.get("issue_tags") or []
    llm_response_md: str = proposal_dict.get("llm_response_md") or ""
    created_at: str = proposal_dict.get("created_at", "")

    # Title: join tags, fallback if empty
    tags_str = " | ".join(issue_tags) if issue_tags else "(no tags)"
    title = f"[AQA PROPOSAL] {tags_str}"

    # Truncate description to Discord embed limit
    if len(llm_response_md) > _EMBED_DESC_MAX:
        description = (
            llm_response_md[:_EMBED_DESC_MAX]
            + f"\n\n_[truncated -- see DB proposal #{proposal_id} for full text]_"
        )
    else:
        description = llm_response_md

    footer_text = f"BMG Capital - AQA Phase A - proposal #{proposal_id} - cycle {cycle_id}"

    payload = {
        "embeds": [
            {
                "title": title,
                "description": description,
                "color": _DISCORD_EMBED_COLOR,
                "footer": {"text": footer_text},
                "timestamp": created_at if created_at else None,
            }
        ]
    }

    # Remove None timestamp to avoid Discord parse errors
    if payload["embeds"][0]["timestamp"] is None:
        del payload["embeds"][0]["timestamp"]

    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.post(
                webhook_url,
                json=payload,
                params={"wait": "true"},
            )
        if resp.status_code >= 400:
            logger.error(
                "[aqa-proposal] Discord webhook returned %d for proposal #%s",
                resp.status_code,
                proposal_id,
            )
            return None
        message_id = resp.json().get("id")
        logger.info(
            "[aqa-proposal] posted to Discord proposal #%s message_id=%s",
            proposal_id,
            message_id,
        )
        return message_id
    except Exception as exc:
        logger.error(
            "[aqa-proposal] Discord post failed for proposal #%s: %s",
            proposal_id,
            exc,
        )
        return None


def mark_posted(db: Session, proposal_id: int, discord_message_id: str) -> None:
    """Update aqa_proposals row with posted_at=now UTC and discord_message_id."""
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    db.execute(
        text(
            "UPDATE aqa_proposals "
            "SET posted_at = :posted_at, discord_message_id = :msg_id "
            "WHERE id = :id"
        ),
        {"posted_at": now_iso, "msg_id": discord_message_id, "id": proposal_id},
    )
    db.commit()
