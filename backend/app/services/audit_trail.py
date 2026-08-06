"""
C7 — Audit Trail Compliance Log.

Every manual intervention (bot enable/disable/pause/resume, config change,
capital change, position force-close) is written to audit_trail table AND
posted to the #audit-trail Discord channel (append-only, no editing).

Call post_audit_event() from any endpoint that mutates bot/capital state.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text

logger = logging.getLogger(__name__)

# Warn at import time so Railway startup logs make the missing config obvious
if not os.getenv("DISCORD_CH_AUDIT_TRAIL"):
    logger.warning(
        "[audit_trail] DISCORD_CH_AUDIT_TRAIL env var not set — "
        "audit events will write to DB only (no Discord). "
        "Create #audit-trail channel, copy its ID, and set the env var in Railway."
    )


def _ensure_audit_trail_table(db: Session) -> None:
    try:
        db.execute(sql_text("""
            CREATE TABLE IF NOT EXISTS audit_trail (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          TEXT    NOT NULL,
                actor       TEXT    NOT NULL,
                action      TEXT    NOT NULL,
                entity_type TEXT    NOT NULL,
                entity_id   TEXT,
                before_val  TEXT,
                after_val   TEXT,
                notes       TEXT
            )
        """))
        db.commit()
    except Exception as exc:
        logger.debug("[audit_trail] table ensure failed: %s", exc)


def _write_db(
    db: Session,
    *,
    actor: str,
    action: str,
    entity_type: str,
    entity_id: str | None,
    before_val: Any,
    after_val: Any,
    notes: str | None = None,
) -> int | None:
    _ensure_audit_trail_table(db)
    try:
        result = db.execute(sql_text("""
            INSERT INTO audit_trail (ts, actor, action, entity_type, entity_id, before_val, after_val, notes)
            VALUES (:ts, :actor, :action, :entity_type, :entity_id, :before, :after, :notes)
        """), {
            "ts":          datetime.now(timezone.utc).isoformat(),
            "actor":       actor,
            "action":      action,
            "entity_type": entity_type,
            "entity_id":   entity_id,
            "before":      json.dumps(before_val) if before_val is not None else None,
            "after":       json.dumps(after_val)  if after_val  is not None else None,
            "notes":       notes,
        })
        db.commit()
        return result.lastrowid
    except Exception as exc:
        logger.warning("[audit_trail] db write failed: %s", exc)
        return None


def _post_discord(
    *,
    actor: str,
    action: str,
    entity_type: str,
    entity_id: str | None,
    before_val: Any,
    after_val: Any,
    notes: str | None,
    ts: str,
) -> None:
    if os.getenv("NOTIFICATIONS_DISCORD_ENABLED", "false").strip().lower() != "true":
        return
    token      = os.getenv("DISCORD_BOT_TOKEN", "")
    channel_id = os.getenv("DISCORD_CH_AUDIT_TRAIL", "") or os.getenv("DISCORD_CH_DEV_LOG", "")
    if not token or not channel_id:
        return

    entity_label = f"{entity_type}/{entity_id}" if entity_id else entity_type
    before_str   = json.dumps(before_val, default=str) if before_val is not None else "—"
    after_str    = json.dumps(after_val,  default=str) if after_val  is not None else "—"

    # Truncate for Discord field limits
    if len(before_str) > 300:
        before_str = before_str[:297] + "..."
    if len(after_str) > 300:
        after_str = after_str[:297] + "..."

    action_colors = {
        "enable":         0x16A34A,   # green
        "disable":        0xDC2626,   # red
        "pause":          0xCA8A04,   # yellow
        "resume":         0x2563EB,   # blue
        "config_change":  0x7C3AED,   # purple
        "capital_change": 0xEA580C,   # orange
        "position_close": 0xDC2626,   # red
    }
    color = action_colors.get(action, 0x6366F1)

    embed = {
        "title":       f"📋 {action.replace('_', ' ').title()} — {entity_label}",
        "description": notes or "",
        "color":       color,
        "fields": [
            {"name": "Actor",  "value": actor,      "inline": True},
            {"name": "Action", "value": action,     "inline": True},
            {"name": "Entity", "value": entity_label, "inline": True},
            {"name": "Before", "value": f"`{before_str}`", "inline": False},
            {"name": "After",  "value": f"`{after_str}`",  "inline": False},
        ],
        "footer":    {"text": f"audit_trail · append-only · {ts[:19]} UTC"},
        "timestamp": ts,
    }

    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.post(
                url,
                headers={
                    "Authorization": f"Bot {token}",
                    "Content-Type":  "application/json",
                    "User-Agent":    "DiscordBot (https://github.com/BMG-Capital/bmg-capital, 1.0.0)",
                },
                json={"embeds": [embed]},
            )
        if not resp.is_success:
            logger.debug("[audit_trail] Discord post failed: %s — %s", resp.status_code, resp.text[:120])
    except Exception as exc:
        logger.debug("[audit_trail] Discord HTTP error: %s", exc)


def post_audit_event(
    db: Session,
    *,
    actor: str,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    before_val: Any = None,
    after_val: Any = None,
    notes: str | None = None,
) -> None:
    """
    Record a manual intervention to DB + Discord.

    action should be one of: enable, disable, pause, resume,
                              config_change, capital_change, position_close
    entity_type: "bot", "portfolio", "position"
    entity_id:   bot name, portfolio asset_class, position id
    before_val / after_val: any JSON-serializable value
    actor: typically current_user.email
    """
    ts = datetime.now(timezone.utc).isoformat()

    _write_db(
        db,
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before_val=before_val,
        after_val=after_val,
        notes=notes,
    )

    try:
        _post_discord(
            actor=actor,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            before_val=before_val,
            after_val=after_val,
            notes=notes,
            ts=ts,
        )
    except Exception as exc:
        logger.debug("[audit_trail] discord post wrapper failed: %s", exc)
