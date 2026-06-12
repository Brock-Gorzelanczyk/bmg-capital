"""
Inter-agent message bus backed by the agent_messages Postgres table.

Every agent publishes structured messages here; subscribers poll or react
to pg_notify notifications. This is the single shared communication layer
for the BMG Capital agent fleet.

Functions:
  publish()      — write a message, emit NOTIFY
  reply()        — write a reply threaded to an original message
  query_recent() — fetch recent messages for a channel
  mark_read()    — mark a message as acknowledged by an agent
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)

_CHANNEL = "bmg_agent_bus"   # Postgres NOTIFY channel name


def publish(
    db: Session,
    *,
    channel: str,
    from_agent: str,
    to_agent: Optional[str] = None,
    msg_type: str,
    subject: str,
    payload: dict[str, Any] | None = None,
    priority: int = 5,
    reply_to_id: Optional[int] = None,
) -> Optional[int]:
    """
    Write a message to agent_messages and emit pg_notify.

    Returns the new message id, or None on failure.
    """
    try:
        result = db.execute(
            text("""
                INSERT INTO agent_messages
                    (channel, from_agent, to_agent, msg_type, subject, payload,
                     priority, reply_to_id, created_at)
                VALUES
                    (:channel, :from_agent, :to_agent, :msg_type, :subject, :payload,
                     :priority, :reply_to_id, :now)
                RETURNING id
            """),
            {
                "channel":     channel,
                "from_agent":  from_agent,
                "to_agent":    to_agent,
                "msg_type":    msg_type,
                "subject":     subject,
                "payload":     json.dumps(payload or {}),
                "priority":    priority,
                "reply_to_id": reply_to_id,
                "now":         datetime.now(timezone.utc).isoformat(),
            },
        )
        row = result.fetchone()
        db.commit()

        msg_id = row[0] if row else None

        # Best-effort pg_notify so long-polling consumers wake immediately.
        # Silently skipped on SQLite (no NOTIFY support).
        if msg_id is not None:
            try:
                db.execute(
                    text("SELECT pg_notify(:ch, :payload)"),
                    {"ch": _CHANNEL, "payload": json.dumps({"id": msg_id, "channel": channel})},
                )
                db.commit()
            except Exception:
                pass  # SQLite / non-Postgres — pg_notify not available

        return msg_id
    except Exception as exc:
        logger.warning("[bus] publish failed (channel=%s from=%s): %s", channel, from_agent, exc)
        try:
            db.rollback()
        except Exception:
            pass
        return None


def reply(
    db: Session,
    *,
    original_msg_id: int,
    from_agent: str,
    msg_type: str,
    subject: str,
    payload: dict[str, Any] | None = None,
) -> Optional[int]:
    """Convenience wrapper: publish a reply threaded to original_msg_id."""
    original = db.execute(
        text("SELECT channel, from_agent FROM agent_messages WHERE id = :id"),
        {"id": original_msg_id},
    ).fetchone()

    if not original:
        logger.warning("[bus] reply: original message %d not found", original_msg_id)
        return None

    return publish(
        db,
        channel=original[0],
        from_agent=from_agent,
        to_agent=original[1],
        msg_type=msg_type,
        subject=subject,
        payload=payload,
        reply_to_id=original_msg_id,
    )


def query_recent(
    db: Session,
    channel: str,
    *,
    since_hours: float = 24,
    limit: int = 50,
    to_agent: Optional[str] = None,
    msg_type: Optional[str] = None,
) -> list[dict]:
    """
    Return recent messages for a channel, newest first.

    Optionally filter by to_agent or msg_type.
    """
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).isoformat()

        filters = "WHERE channel = :channel AND created_at >= :cutoff"
        params: dict[str, Any] = {"channel": channel, "cutoff": cutoff, "limit": limit}

        if to_agent is not None:
            filters += " AND to_agent = :to_agent"
            params["to_agent"] = to_agent

        if msg_type is not None:
            filters += " AND msg_type = :msg_type"
            params["msg_type"] = msg_type

        rows = db.execute(
            text(f"""
                SELECT id, channel, from_agent, to_agent, msg_type, subject,
                       payload, priority, reply_to_id, read_by, created_at
                FROM agent_messages
                {filters}
                ORDER BY created_at DESC
                LIMIT :limit
            """),
            params,
        ).fetchall()

        return [
            {
                "id":          row[0],
                "channel":     row[1],
                "from_agent":  row[2],
                "to_agent":    row[3],
                "msg_type":    row[4],
                "subject":     row[5],
                "payload":     json.loads(row[6]) if row[6] else {},
                "priority":    row[7],
                "reply_to_id": row[8],
                "read_by":     json.loads(row[9]) if row[9] else [],
                "created_at":  row[10],
            }
            for row in rows
        ]
    except Exception as exc:
        logger.warning("[bus] query_recent failed (channel=%s): %s", channel, exc)
        return []


def heartbeat(db: Session, *, agent_id: str, status: str = "active") -> None:
    """Publish a lightweight liveness tick. Called every 30s by fleet_heartbeat job."""
    try:
        publish(
            db,
            channel="agent_heartbeats",
            from_agent=agent_id,
            msg_type="heartbeat",
            subject=f"{agent_id} alive",
            payload={"status": status},
            priority=1,
        )
    except Exception as exc:
        logger.debug("[bus] heartbeat failed (agent=%s): %s", agent_id, exc)


def ask_agent(
    db: Session, *,
    from_agent: str,
    to_agent: str,
    question: str,
    correlation_id: str | None = None,
) -> int:
    """Post a query to another agent. Returns the message id."""
    import uuid
    corr = correlation_id or str(uuid.uuid4())[:8]
    msg_id = publish(
        db,
        channel="agent_queries",
        from_agent=from_agent,
        to_agent=to_agent,
        msg_type="query",
        subject=question[:200],
        payload={"question": question, "correlation_id": corr},
        priority=5,
    )
    return msg_id if msg_id is not None else corr


def get_pending_queries(db: Session, *, agent_id: str) -> list[dict]:
    """Fetch unanswered queries addressed to this agent (last 4h)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=4)).isoformat()
    try:
        rows = db.execute(
            text("""
                SELECT id, from_agent, subject, payload, created_at
                FROM agent_messages
                WHERE channel = 'agent_queries'
                  AND to_agent = :a
                  AND msg_type = 'query'
                  AND created_at >= :c
                ORDER BY created_at ASC
            """),
            {"a": agent_id, "c": cutoff},
        ).fetchall()
        result = []
        for r in rows:
            payload = r[3]
            try:
                import json as _j
                payload = _j.loads(payload) if isinstance(payload, str) else payload
            except Exception:
                pass
            result.append({
                "id": r[0], "from_agent": r[1],
                "question": r[2], "payload": payload,
                "created_at": str(r[4]),
            })
        return result
    except Exception as exc:
        logger.debug("[bus] get_pending_queries failed: %s", exc)
        return []


def answer_query(
    db: Session, *,
    from_agent: str,
    to_agent: str,
    question: str,
    answer: str,
    correlation_id: str = "",
) -> None:
    """Post a response back to the querying agent."""
    publish(
        db,
        channel="agent_queries",
        from_agent=from_agent,
        to_agent=to_agent,
        msg_type="query_response",
        subject=f"Re: {question[:150]}",
        payload={"answer": answer, "correlation_id": correlation_id},
        priority=4,
    )


def mark_read(db: Session, *, msg_id: int, agent: str) -> None:
    """Record that `agent` has acknowledged message `msg_id`."""
    try:
        row = db.execute(
            text("SELECT read_by FROM agent_messages WHERE id = :id"),
            {"id": msg_id},
        ).fetchone()
        if not row:
            return

        readers: list[str] = json.loads(row[0]) if row[0] else []
        if agent not in readers:
            readers.append(agent)
            db.execute(
                text("UPDATE agent_messages SET read_by = :rb WHERE id = :id"),
                {"rb": json.dumps(readers), "id": msg_id},
            )
            db.commit()
    except Exception as exc:
        logger.warning("[bus] mark_read failed (msg_id=%d agent=%s): %s", msg_id, agent, exc)
