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
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)

_AGENT_DISPLAY = {
    "queen":                ("👑 Brick (PM)",              ""),
    "researcher":           ("🔬 Nick (Equity Research)",  ""),
    "risk_sentinel":        ("🛡️ Dick (CRO)",              ""),
    "macro_strategist":     ("📈 Rick (Macro Strategist)", ""),
    "quant_researcher":     ("🧮 Mick (Quant Research)",   ""),
    "data_quality_watcher": ("📊 Vick (Data Quality)",     ""),
    "execution_auditor":    ("⚡ Slick (Execution)",       ""),
    "operations":           ("🏦 Wick (Operations)",       ""),
    "sentinel_devops":      ("🖥️ Patrick (DevOps)",        ""),
}

_last_observe_ts: dict[str, datetime] = {}
_OBSERVE_COOLDOWN_MINUTES = 15


def _chat_webhook_url() -> str:
    return os.getenv("DISCORD_WH_FUND_TEAM_CHAT", "").strip()


def _agent_display(agent_id: str) -> tuple[str, str]:
    return _AGENT_DISPLAY.get(agent_id, (agent_id.replace("_", " ").title(), ""))


def _post_to_team_chat(from_agent: str, to_agent, content: str, msg_type: str, reply_to_content: str = "") -> None:
    url = _chat_webhook_url()
    if not url:
        return
    display_name, avatar_url = _agent_display(from_agent)

    if to_agent and to_agent != from_agent:
        to_display, _ = _agent_display(to_agent)
        prefix = f"→ **{to_display}**  "
    else:
        prefix = ""

    quote = ""
    if reply_to_content:
        trimmed = reply_to_content[:120].replace("\n", " ")
        quote = f"> {trimmed}\n"

    badge = {"query": "❓", "query_response": "💬", "observation": "👁️"}.get(msg_type, "📨")

    full_text = f"{badge} {prefix}{quote}{content}"[:2000]

    payload = {"username": display_name, "content": full_text}
    if avatar_url:
        payload["avatar_url"] = avatar_url

    try:
        import httpx as _hx
        _hx.post(url, json=payload, timeout=5)
    except Exception as exc:
        logger.debug("[bus] team chat post failed: %s", exc)


def _updates_webhook_url() -> str:
    return os.getenv("DISCORD_WH_FUND_UPDATES", "").strip()


def post_update_request(
    from_agent: str,
    title: str,
    body: str,
    paste_ready: str,
    priority: str = "normal",
) -> bool:
    """
    Post a paste-ready update request to #fund-updates so Brock can copy it
    directly into Claude Code.

    Args:
        from_agent:   agent ID (e.g. "risk_sentinel")
        title:        short headline, e.g. "crypto_meanrev_2163 tier demotion needed"
        body:         1-3 sentence context for why this is needed
        paste_ready:  the exact text Brock should paste into Claude Code
        priority:     "low" | "normal" | "high" | "critical"
    """
    url = _updates_webhook_url()
    if not url:
        logger.debug("[bus] DISCORD_WH_FUND_UPDATES not set — update request not posted")
        return False

    display_name, _ = _agent_display(from_agent)
    priority_prefix = {"low": "🔵", "normal": "🟡", "high": "🟠", "critical": "🔴"}.get(priority, "🟡")
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Cap paste_ready to fit in a Discord embed field (1024 chars)
    if len(paste_ready) > 900:
        paste_ready = paste_ready[:900] + "\n…(truncated)"

    embed = {
        "title":       f"{priority_prefix} {title}",
        "description": body,
        "color":       {"low": 0x3B82F6, "normal": 0xFBBF24, "high": 0xF97316, "critical": 0xEF4444}.get(priority, 0xFBBF24),
        "fields": [
            {
                "name":   "📋 Paste into Claude Code",
                "value":  f"```\n{paste_ready}\n```",
                "inline": False,
            }
        ],
        "footer": {"text": f"{display_name} · {now_str}"},
    }

    try:
        import httpx as _hx
        resp = _hx.post(url, json={"embeds": [embed], "username": display_name}, timeout=8)
        return resp.is_success
    except Exception as exc:
        logger.warning("[bus] post_update_request failed: %s", exc)
        return False


def observe(db: Session, *, agent_id: str, content: str, context: dict | None = None) -> None:
    """Post an unsolicited observation. Throttled to 1 per agent per 15 min."""
    now = datetime.now(timezone.utc)
    last = _last_observe_ts.get(agent_id)
    if last and (now - last).total_seconds() < _OBSERVE_COOLDOWN_MINUTES * 60:
        logger.debug("[bus] observe throttled for %s", agent_id)
        return
    _last_observe_ts[agent_id] = now

    try:
        publish(
            db,
            channel="agent_observations",
            from_agent=agent_id,
            msg_type="observation",
            subject=content[:200],
            payload={"content": content, "context": context or {}},
            priority=3,
        )
    except Exception as exc:
        logger.debug("[bus] observe bus publish failed: %s", exc)

    _post_to_team_chat(agent_id, None, content, "observation")

def post_daily_checkin(db: Session, agent_id: str, message: str) -> bool:
    """
    Post a daily check-in to #fund-team-chat once per UTC day per agent.
    Returns True if posted, False if already posted today or webhook not set.
    """
    import os as _os
    from datetime import date as _date
    today = _date.today().isoformat()
    state_key = f"last_chat_post_{agent_id}"

    # Check if already posted today
    try:
        row = db.execute(
            text("SELECT value FROM fund_team_chat_state WHERE key = :k"),
            {"k": state_key}
        ).fetchone()
        if row and row[0] == today:
            return False  # already posted today
    except Exception:
        pass

    # Post
    _post_to_team_chat(agent_id, None, message, "observation")

    # Record
    try:
        db.execute(text("""
            INSERT INTO fund_team_chat_state (key, value, set_at)
            VALUES (:k, :v, :ts)
            ON CONFLICT (key) DO UPDATE SET value = :v, set_at = :ts
        """), {"k": state_key, "v": today, "ts": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()})
        db.commit()
    except Exception:
        pass

    return True


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

        # Mirror queries and responses to #fund-team-chat
        if msg_type in ("query", "query_response"):
            reply_content = ""
            if msg_type == "query_response" and subject:
                reply_content = subject.replace("Re: ", "", 1)
            chat_content = subject or (json.dumps(payload)[:300] if payload else "")
            _post_to_team_chat(from_agent, to_agent, chat_content, msg_type, reply_content)

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


def charge_api_usage(db: Session, agent_id: str, cost_usd: float) -> bool:
    """
    Record an API spend and return True if the call should proceed.
    Returns False when the daily cap has been hit — callers must skip the LLM call.
    """
    try:
        from agents.budget import charge as _charge
        return _charge(db, agent_id, cost_usd)
    except Exception as exc:
        logger.warning("[bus] charge_api_usage failed (non-fatal, allowing call): %s", exc)
        return True  # fail open — don't block on budget errors


def is_budget_capped(db: Session) -> bool:
    """Return True if today's API budget cap has been hit."""
    try:
        from agents.budget import is_capped as _is_capped
        return _is_capped(db)
    except Exception:
        return False
