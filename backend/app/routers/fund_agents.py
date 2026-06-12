"""
/api/agents/status — live status for every agent in the BMG Capital fleet.

Active agents (Queen, Researcher, Sentinel DevOps) report status from the
agent_messages bus. Not-yet-built agents return status="not_built" with
their expected deploy phase.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.dependencies import get_db

router = APIRouter(prefix="/api/agents", tags=["agents"])

# Agents not yet deployed — static metadata
_NOT_BUILT = {
    "chief_risk_officer": 2,
    "data_quality_watcher": 2,
    "execution_auditor": 2,
    "quant_researcher": 6,
    "macro_strategist": 6,
    "operations": 6,
}

# Map agent bus from_agent values to role IDs
_AGENT_TO_ROLE = {
    "queen":        "portfolio_manager",
    "researcher":   "equity_researcher",
    "sentinel":     "sentinel_devops",
    "sentinel_devops": "sentinel_devops",
}

# How much today activity to return
_TODAY_WINDOW_HOURS = 24
_RECENT_ACTIVITY_LIMIT = 5


def _get_agent_activity(db: Session, from_agent: str) -> dict:
    """Pull last activity and today's message count from agent_messages."""
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=_TODAY_WINDOW_HOURS)).isoformat()

        rows = db.execute(
            text("""
                SELECT msg_type, subject, created_at
                FROM agent_messages
                WHERE from_agent = :agent AND created_at >= :cutoff
                ORDER BY created_at DESC
                LIMIT :limit
            """),
            {"agent": from_agent, "cutoff": cutoff, "limit": _RECENT_ACTIVITY_LIMIT},
        ).fetchall()

        last_any = db.execute(
            text("""
                SELECT created_at FROM agent_messages
                WHERE from_agent = :agent
                ORDER BY created_at DESC LIMIT 1
            """),
            {"agent": from_agent},
        ).fetchone()

        return {
            "last_activity": last_any[0] if last_any else None,
            "today_count": len(rows),
            "recent_activity": [
                {"ts": str(r[2]), "action": r[0], "result": r[1][:80]}
                for r in rows
            ],
        }
    except Exception:
        return {"last_activity": None, "today_count": 0, "recent_activity": []}


def _queen_today_stats(db: Session) -> dict:
    """Count queen briefings and proposals sent today."""
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=_TODAY_WINDOW_HOURS)).isoformat()
        briefings = db.execute(
            text("""
                SELECT COUNT(*) FROM agent_messages
                WHERE from_agent='queen' AND msg_type='brief' AND created_at >= :c
            """),
            {"c": cutoff},
        ).scalar() or 0
        proposals = db.execute(
            text("""
                SELECT COUNT(*) FROM agent_messages
                WHERE from_agent='queen' AND msg_type='proposal' AND created_at >= :c
            """),
            {"c": cutoff},
        ).scalar() or 0
        return {"briefings_sent": briefings, "proposals_generated": proposals}
    except Exception:
        return {"briefings_sent": 0, "proposals_generated": 0}


def _sentinel_devops_activity(db: Session) -> dict:
    """Pull from agent_events table for Sentinel DevOps status."""
    try:
        last = db.execute(
            text("""
                SELECT detected_at, category, payload
                FROM agent_events
                ORDER BY detected_at DESC LIMIT 1
            """)
        ).fetchone()

        cutoff = (datetime.now(timezone.utc) - timedelta(hours=_TODAY_WINDOW_HOURS)).isoformat()
        today_count = db.execute(
            text("SELECT COUNT(*) FROM agent_events WHERE detected_at >= :c"),
            {"c": cutoff},
        ).scalar() or 0

        recent = db.execute(
            text("""
                SELECT category, payload, detected_at FROM agent_events
                WHERE detected_at >= :c ORDER BY detected_at DESC LIMIT 5
            """),
            {"c": cutoff},
        ).fetchall()

        return {
            "last_activity": str(last[0]) if last else None,
            "today_count": today_count,
            "recent_activity": [
                {"ts": str(r[2]), "action": r[0], "result": str(r[1])[:80]}
                for r in recent
            ],
        }
    except Exception:
        return {"last_activity": None, "today_count": 0, "recent_activity": []}


@router.get("/status")
def get_agents_status(db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)

    queen_activity = _get_agent_activity(db, "queen")
    queen_stats = _queen_today_stats(db)
    researcher_activity = _get_agent_activity(db, "researcher")
    sentinel_activity = _sentinel_devops_activity(db)

    def _status_from_last(last_ts_str) -> str:
        if not last_ts_str:
            return "offline"
        try:
            last = datetime.fromisoformat(str(last_ts_str).replace("Z", "+00:00"))
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            hours_ago = (now - last).total_seconds() / 3600
            if hours_ago < 26:   # within expected 24h window
                return "active"
            if hours_ago < 72:   # missed a day
                return "degraded"
            return "offline"
        except Exception:
            return "offline"

    agents = [
        {
            "id": "cio",
            "status": "active",
            "last_activity": now.isoformat(),
            "today": {"briefings_sent": 0, "proposals_generated": 0, "api_cost_usd": 0.0, "api_budget_usd": 0.0},
            "recent_activity": [],
        },
        {
            "id": "portfolio_manager",
            "status": _status_from_last(queen_activity["last_activity"]),
            "last_activity": queen_activity["last_activity"],
            "today": {
                "briefings_sent": queen_stats["briefings_sent"],
                "proposals_generated": queen_stats["proposals_generated"],
                "api_cost_usd": 0.0,
                "api_budget_usd": 2.0,
                "messages_sent": queen_activity["today_count"],
            },
            "recent_activity": queen_activity["recent_activity"],
        },
        {
            "id": "equity_researcher",
            "status": _status_from_last(researcher_activity["last_activity"]),
            "last_activity": researcher_activity["last_activity"],
            "today": {
                "briefings_sent": researcher_activity["today_count"],
                "proposals_generated": 0,
                "api_cost_usd": 0.0,
                "api_budget_usd": 0.5,
            },
            "recent_activity": researcher_activity["recent_activity"],
        },
        {
            "id": "sentinel_devops",
            "status": _status_from_last(sentinel_activity["last_activity"]) if sentinel_activity["today_count"] > 0 else "active",
            "last_activity": sentinel_activity["last_activity"],
            "today": {
                "events_processed": sentinel_activity["today_count"],
                "api_cost_usd": 0.0,
                "api_budget_usd": 1.0,
            },
            "recent_activity": sentinel_activity["recent_activity"],
        },
        *[
            {
                "id": role_id,
                "status": "not_built",
                "expected_deploy_phase": phase,
                "last_activity": None,
                "today": {},
                "recent_activity": [],
            }
            for role_id, phase in _NOT_BUILT.items()
        ],
    ]

    return {"agents": agents, "as_of": now.isoformat()}
