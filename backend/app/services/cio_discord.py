"""CIO Discord posting — posts briefings to #cio-briefings via DISCORD_WH_CIO_BRIEFINGS.

NEVER gates on DISCORD_SIGNAL_POSTING_ENABLED (known-issue #9 / commit 10385b5).
Gates on DISCORD_OPS_ALERTS_ENABLED.
Uses ONLY the DISCORD_WH_CIO_BRIEFINGS webhook — never reuses any other webhook.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

DISCORD_WH_CIO_BRIEFINGS_ENV = "DISCORD_WH_CIO_BRIEFINGS"
_DISCORD_EMBED_DESCRIPTION_LIMIT = 4000
_TRUNCATION_FOOTER = "\n\n...see fund_briefings table for full text"


def post_cio_briefing(
    *,
    markdown_body: str,
    summary_one_liner: str,
    needs_brock: bool,
    db: Session,
    briefing_id: str,
    vetoes_used: int,
    cost_usd: float,
    duration_seconds: int,
) -> Optional[str]:
    """Post the CIO briefing to #cio-briefings.

    Returns discord_message_id on success, None on skip/failure.

    Gating: requires DISCORD_OPS_ALERTS_ENABLED in {"true","1"}.
    Webhook URL: env DISCORD_WH_CIO_BRIEFINGS only. NEVER reuse other webhooks.
    Truncates markdown to 4000 chars; appends truncation footer if truncated.
    Updates fund_briefings.discord_message_id + posted_at on success.
    """
    # Gate on ops alerts env (NOT signal posting — known-issue #9)
    if os.getenv("DISCORD_OPS_ALERTS_ENABLED", "false").strip().lower() not in ("true", "1"):
        logger.info("[cio_discord] DISCORD_OPS_ALERTS_ENABLED=false — skipping post")
        return None

    url = os.getenv(DISCORD_WH_CIO_BRIEFINGS_ENV, "").strip()
    if not url:
        logger.warning(
            "[cio_discord] %s unset — skipping post (set this to a NEW webhook on #cio-briefings)",
            DISCORD_WH_CIO_BRIEFINGS_ENV,
        )
        return None

    # Build description: summary + markdown body (truncated)
    full_desc = f"{summary_one_liner}\n\n{markdown_body}"
    truncated = False
    if len(full_desc) > _DISCORD_EMBED_DESCRIPTION_LIMIT:
        cutoff = _DISCORD_EMBED_DESCRIPTION_LIMIT - len(_TRUNCATION_FOOTER)
        full_desc = full_desc[:cutoff] + _TRUNCATION_FOOTER
        truncated = True

    # Embed color: green if no vetoes and no brock action needed; amber otherwise
    color = 0x4ADE80 if (vetoes_used == 0 and not needs_brock) else 0xFBBF24

    # Brock ping content
    brock_role_id = os.getenv("BROCK_DISCORD_ROLE_ID", "").strip()
    content = ""
    if needs_brock:
        mention = f"<@&{brock_role_id}>" if brock_role_id else "@Brock"
        content = f"{mention} — decisions await"

    embed = {
        "title": "CIO Morning Briefing",
        "description": full_desc,
        "color": color,
        "fields": [
            {"name": "Cost", "value": f"${cost_usd:.4f}", "inline": True},
            {"name": "Duration", "value": f"{duration_seconds}s", "inline": True},
            {"name": "Vetoes", "value": str(vetoes_used), "inline": True},
            {"name": "Briefing ID", "value": briefing_id, "inline": False},
        ],
    }

    payload: dict = {"embeds": [embed]}
    if content:
        payload["content"] = content

    try:
        resp = httpx.post(
            url,
            content=json.dumps(payload),
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        message_id = str(data.get("id", "")) or None

        # Update fund_briefings
        if message_id:
            try:
                db.execute(
                    text(
                        "UPDATE fund_briefings "
                        "SET discord_message_id=:mid, posted_at=CURRENT_TIMESTAMP "
                        "WHERE briefing_id=:bid"
                    ),
                    {"mid": message_id, "bid": briefing_id},
                )
                db.commit()
            except Exception as db_exc:
                logger.warning("[cio_discord] fund_briefings update failed: %s", db_exc)

        logger.info(
            "[cio_discord] posted briefing %s → discord msg %s (truncated=%s)",
            briefing_id, message_id, truncated,
        )
        return message_id

    except httpx.HTTPStatusError as exc:
        logger.error(
            "[cio_discord] Discord webhook returned %s: %s",
            exc.response.status_code, exc.response.text[:500],
        )
        return None
    except Exception as exc:
        logger.error("[cio_discord] post_cio_briefing failed: %s", exc)
        return None
