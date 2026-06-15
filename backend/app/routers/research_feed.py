"""
/api/research-feed — browse the Researcher agent's persistent memory store.

GET /api/research-feed/findings
  ?agent=researcher|all
  ?memory_type=<type>
  ?days=7|30|90|0 (0=all time)
  ?q=<search>
  ?limit=100
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.dependencies import get_db, get_current_user
from app.db.models.users import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/research-feed", tags=["research-feed"])


def _safe_json(raw: str | None) -> Any:
    if not raw:
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return raw


def _value_preview(value: Any, max_len: int = 200) -> str:
    if isinstance(value, dict):
        return "; ".join(f"{k}: {v}" for k, v in list(value.items())[:5])[:max_len]
    if isinstance(value, list):
        return ", ".join(str(x) for x in value[:5])[:max_len]
    return str(value)[:max_len]


@router.get("/findings")
def get_findings(
    agent: str = Query("researcher", description="Agent ID or 'all'"),
    memory_type: Optional[str] = Query(None, description="Filter to a specific memory_type"),
    days: int = Query(30, ge=0, description="Lookback days; 0 = all time"),
    q: Optional[str] = Query(None, description="Full-text search on key or value"),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat() if days > 0 else None

    where_clauses = ["(expires_at IS NULL OR expires_at > :now)"]
    params: dict[str, Any] = {"now": now, "limit": limit}

    if agent != "all":
        where_clauses.append("agent_id = :agent")
        params["agent"] = agent

    if memory_type:
        where_clauses.append("memory_type = :mtype")
        params["mtype"] = memory_type

    if cutoff:
        where_clauses.append("updated_at >= :cutoff")
        params["cutoff"] = cutoff

    if q:
        where_clauses.append("(key LIKE :q OR value LIKE :q)")
        params["q"] = f"%{q}%"

    where_sql = " AND ".join(where_clauses)

    try:
        rows = db.execute(
            text(f"""
                SELECT id, agent_id, memory_type, key, value, updated_at
                FROM agent_memory
                WHERE {where_sql}
                ORDER BY updated_at DESC
                LIMIT :limit
            """),
            params,
        ).fetchall()
    except Exception as exc:
        logger.warning("[research-feed] findings query failed: %s", exc)
        rows = []

    try:
        type_rows = db.execute(
            text("SELECT DISTINCT memory_type FROM agent_memory ORDER BY memory_type")
        ).fetchall()
        memory_types = [r[0] for r in type_rows]
    except Exception:
        memory_types = []

    try:
        agent_rows = db.execute(
            text("SELECT DISTINCT agent_id FROM agent_memory ORDER BY agent_id")
        ).fetchall()
        agents = [r[0] for r in agent_rows]
    except Exception:
        agents = ["researcher"]

    findings = []
    for r in rows:
        parsed = _safe_json(r[4])
        findings.append({
            "id":          r[0],
            "agent_id":    r[1],
            "memory_type": r[2],
            "key":         r[3],
            "value":       parsed,
            "preview":     _value_preview(parsed),
            "updated_at":  str(r[5]),
        })

    return {
        "findings":     findings,
        "total":        len(findings),
        "memory_types": memory_types,
        "agents":       agents,
    }
