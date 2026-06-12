"""
Agent memory store — persistent key/value observations backed by agent_memory table.

Used by Researcher to carry context across daily runs (regime notes, bot observations,
candidate history). Can be extended to any agent that needs cross-session memory.

Functions:
  save_memory()            — write or update a memory entry
  get_memories()           — fetch recent memories for an agent
  get_context_for_research() — formatted context string for researcher prompt injection
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)


def save_memory(
    db: Session,
    *,
    agent_id: str,
    memory_type: str,
    key: str,
    value: Any,
    ttl_days: Optional[int] = 30,
) -> bool:
    """
    Upsert a memory entry. If a row with (agent_id, memory_type, key) already
    exists it is overwritten in-place, preserving a single canonical memory
    per key rather than accumulating duplicates.
    """
    try:
        now = datetime.now(timezone.utc).isoformat()
        expires_at = (
            (datetime.now(timezone.utc) + timedelta(days=ttl_days)).isoformat()
            if ttl_days is not None
            else None
        )
        value_str = json.dumps(value) if not isinstance(value, str) else value

        existing = db.execute(
            text("""
                SELECT id FROM agent_memory
                WHERE agent_id = :agent AND memory_type = :mtype AND key = :key
                LIMIT 1
            """),
            {"agent": agent_id, "mtype": memory_type, "key": key},
        ).fetchone()

        if existing:
            db.execute(
                text("""
                    UPDATE agent_memory
                    SET value = :value, updated_at = :now, expires_at = :exp
                    WHERE id = :id
                """),
                {"value": value_str, "now": now, "exp": expires_at, "id": existing[0]},
            )
        else:
            db.execute(
                text("""
                    INSERT INTO agent_memory
                        (agent_id, memory_type, key, value, created_at, updated_at, expires_at)
                    VALUES (:agent, :mtype, :key, :value, :now, :now, :exp)
                """),
                {
                    "agent": agent_id, "mtype": memory_type, "key": key,
                    "value": value_str, "now": now, "exp": expires_at,
                },
            )
        db.commit()
        return True
    except Exception as exc:
        logger.warning("[memory] save_memory failed (agent=%s key=%s): %s", agent_id, key, exc)
        try:
            db.rollback()
        except Exception:
            pass
        return False


def get_memories(
    db: Session,
    *,
    agent_id: str,
    memory_type: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """
    Return non-expired memories for an agent, newest first.
    Optionally filter to a specific memory_type.
    """
    try:
        now = datetime.now(timezone.utc).isoformat()
        filters = "WHERE agent_id = :agent AND (expires_at IS NULL OR expires_at > :now)"
        params: dict[str, Any] = {"agent": agent_id, "now": now, "limit": limit}

        if memory_type:
            filters += " AND memory_type = :mtype"
            params["mtype"] = memory_type

        rows = db.execute(
            text(f"""
                SELECT id, memory_type, key, value, updated_at
                FROM agent_memory
                {filters}
                ORDER BY updated_at DESC
                LIMIT :limit
            """),
            params,
        ).fetchall()

        return [
            {
                "id":          row[0],
                "memory_type": row[1],
                "key":         row[2],
                "value":       _safe_json(row[3]),
                "updated_at":  str(row[4]),
            }
            for row in rows
        ]
    except Exception as exc:
        logger.warning("[memory] get_memories failed (agent=%s): %s", agent_id, exc)
        return []


def get_context_for_research(db: Session) -> str:
    """
    Return a compact context string the Researcher can prepend to its prompt.
    Pulls the 10 most recent memories across all types and formats them as
    a bullet list that fits comfortably within a prompt context window.
    """
    memories = get_memories(db, agent_id="researcher", limit=10)
    if not memories:
        return ""

    lines = ["[Memory context from prior research runs]"]
    for m in memories:
        val = m["value"]
        if isinstance(val, dict):
            val_str = "; ".join(f"{k}={v}" for k, v in list(val.items())[:4])
        else:
            val_str = str(val)[:120]
        lines.append(f"• [{m['memory_type']}] {m['key']}: {val_str}")

    return "\n".join(lines)


def _safe_json(raw: str) -> Any:
    if not raw:
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return raw
