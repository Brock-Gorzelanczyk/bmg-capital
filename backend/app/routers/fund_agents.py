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

from app.dependencies import get_db, get_current_user

router = APIRouter(prefix="/api/agents", tags=["agents"])

# Agents not yet deployed — static metadata
_NOT_BUILT = {
    "quant_researcher": 6,
    "macro_strategist": 6,
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


def _get_proposal_stats(db: Session) -> dict:
    """Today's proposal counters for the Portfolio Manager /fund card."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    try:
        def _count(where: str, params: dict) -> int:
            return db.execute(
                text(f"SELECT COUNT(*) FROM proposal_audit WHERE {where}"),
                {**params},
            ).scalar() or 0
        return {
            "proposals_generated_today": _count("generated_ts >= :c", {"c": cutoff}),
            "pending_cio_approval":      _count("decision = 'pending'", {}),
            "approved_today":            _count("decision = 'approved' AND decision_ts >= :c", {"c": cutoff}),
            "rejected_today":            _count("decision IN ('rejected','auto_rejected') AND decision_ts >= :c", {"c": cutoff}),
        }
    except Exception:
        return {"proposals_generated_today": 0, "pending_cio_approval": 0, "approved_today": 0, "rejected_today": 0}


def _get_agent_today_count(db: Session, from_agent: str) -> int:
    """Count messages published today by an agent (any channel)."""
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=_TODAY_WINDOW_HOURS)).isoformat()
        return db.execute(
            text("SELECT COUNT(*) FROM agent_messages WHERE from_agent=:a AND created_at>=:c"),
            {"a": from_agent, "c": cutoff},
        ).scalar() or 0
    except Exception:
        return 0


def _get_heartbeat_status(db: Session, agent_id: str) -> tuple:
    """
    Read the most recent heartbeat from agent_heartbeats channel.
      active   — last beat < 90s ago
      degraded — 90-300s ago
      offline  — >300s or never
    Returns (status_str, last_ts_str | None).
    """
    try:
        row = db.execute(
            text("""
                SELECT created_at FROM agent_messages
                WHERE channel = 'agent_heartbeats' AND from_agent = :agent
                ORDER BY created_at DESC LIMIT 1
            """),
            {"agent": agent_id},
        ).fetchone()
        if not row or not row[0]:
            return "offline", None
        ts_raw = row[0]
        if isinstance(ts_raw, str):
            last = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        else:
            last = ts_raw
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        age_secs = (datetime.now(timezone.utc) - last).total_seconds()
        if age_secs < 90:
            status = "active"
        elif age_secs < 300:
            status = "degraded"
        else:
            status = "offline"
        return status, str(row[0])
    except Exception:
        return "offline", None


@router.get("/status")
def get_agents_status(db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)

    queen_hb_status,     queen_hb_ts     = _get_heartbeat_status(db, "queen")
    researcher_hb_status, researcher_hb_ts = _get_heartbeat_status(db, "researcher")
    sentinel_hb_status,  sentinel_hb_ts  = _get_heartbeat_status(db, "sentinel_devops")
    risk_hb_status,      risk_hb_ts      = _get_heartbeat_status(db, "risk_sentinel")
    dq_hb_status,        dq_hb_ts        = _get_heartbeat_status(db, "data_quality_watcher")
    exec_hb_status,      exec_hb_ts      = _get_heartbeat_status(db, "execution_auditor")
    ops_hb_status,       ops_hb_ts       = _get_heartbeat_status(db, "operations")

    queen_activity = _get_agent_activity(db, "queen")
    queen_stats = _queen_today_stats(db)
    researcher_activity = _get_agent_activity(db, "researcher")
    sentinel_activity = _sentinel_devops_activity(db)
    risk_today = _get_agent_today_count(db, "risk_sentinel")
    dq_today   = _get_agent_today_count(db, "data_quality_watcher")
    exec_today = _get_agent_today_count(db, "execution_auditor")
    ops_today  = _get_agent_today_count(db, "operations")

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
            "status": queen_hb_status,
            "last_activity": queen_hb_ts or queen_activity["last_activity"],
            "today": {
                "briefings_sent": queen_stats["briefings_sent"],
                "proposals_generated": queen_stats["proposals_generated"],
                "api_cost_usd": 0.0,
                "api_budget_usd": 2.0,
                "messages_sent": queen_activity["today_count"],
                **_get_proposal_stats(db),
            },
            "recent_activity": queen_activity["recent_activity"],
        },
        {
            "id": "equity_researcher",
            "status": researcher_hb_status,
            "last_activity": researcher_hb_ts or researcher_activity["last_activity"],
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
            "status": sentinel_hb_status,
            "last_activity": sentinel_hb_ts or sentinel_activity["last_activity"],
            "today": {
                "events_processed": sentinel_activity["today_count"],
                "api_cost_usd": 0.0,
                "api_budget_usd": 1.0,
            },
            "recent_activity": sentinel_activity["recent_activity"],
        },
        {
            "id": "chief_risk_officer",
            "status": risk_hb_status,
            "last_activity": risk_hb_ts,
            "today": {"checks_run": risk_today, "api_cost_usd": 0.0, "api_budget_usd": 0.0},
            "recent_activity": [],
        },
        {
            "id": "data_quality_watcher",
            "status": dq_hb_status,
            "last_activity": dq_hb_ts,
            "today": {"checks_run": dq_today, "api_cost_usd": 0.0, "api_budget_usd": 0.0},
            "recent_activity": [],
        },
        {
            "id": "execution_auditor",
            "status": exec_hb_status,
            "last_activity": exec_hb_ts,
            "today": {"audits_run": exec_today, "api_cost_usd": 0.0, "api_budget_usd": 0.0},
            "recent_activity": [],
        },
        {
            "id": "operations",
            "status": ops_hb_status,
            "last_activity": ops_hb_ts,
            "today": {"reconciliations_run": ops_today, "api_cost_usd": 0.0, "api_budget_usd": 0.0},
            "recent_activity": [],
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


@router.post("/standup/run")
def trigger_standup(force: bool = False, db: Session = Depends(get_db)):
    from agents.standup import run_daily_standup
    result = run_daily_standup(db)
    return result


@router.post("/{agent_name}/post-daily-summary")
def force_agent_summary(agent_name: str, force: bool = False, db: Session = Depends(get_db)):
    # Dispatch to the right agent function
    dispatch = {
        "data_quality_watcher": lambda: __import__("strategy_lab.agents.data_quality_watcher", fromlist=["run_data_quality_check"]).run_data_quality_check(db),
        "execution_auditor":    lambda: __import__("strategy_lab.agents.execution_auditor",    fromlist=["run_execution_audit"]).run_execution_audit(db),
        "operations":           lambda: __import__("strategy_lab.agents.operations",           fromlist=["run_operations_reconciliation"]).run_operations_reconciliation(db),
        "researcher":           lambda: __import__("strategy_lab.agents.researcher",           fromlist=["run_daily_research"]).run_daily_research(db),
    }
    if agent_name not in dispatch:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found or does not support force summary")
    result = dispatch[agent_name]()
    return {"ok": True, "agent": agent_name, "result": result}


@router.post("/observation/trigger")
def trigger_observation(agent: str = "risk_sentinel", force: bool = False, db: Session = Depends(get_db)):
    """Force an agent to post a test observation to #fund-team-chat."""
    from agents.bus import observe as _obs
    content_map = {
        "risk_sentinel":        "Test observation from Dick (CRO) — fleet metrics nominal, watching for drawdown signals.",
        "researcher":           "Test observation from Researcher — no high-conviction signals at this time, regime classification stable.",
        "data_quality_watcher": "Test observation from Data Quality — all feeds reporting within normal latency bounds.",
        "execution_auditor":    "Test observation from Execution Auditor — fill quality nominal, slippage within baseline.",
        "operations":           "Test observation from Operations — reconciliation pass, no position mismatches detected.",
    }
    content = content_map.get(agent, f"Test observation from {agent}.")
    _obs(db, agent_id=agent, content=content, context={"force": force})
    return {"ok": True, "agent": agent, "content": content}


@router.post("/cross-query/test")
def test_cross_query(
    from_agent: str = "risk_sentinel",
    to_agent: str = "researcher",
    db: Session = Depends(get_db),
):
    """Fire a test cross-agent query and wait for it to appear in #fund-team-chat."""
    from agents.bus import ask_agent
    msg_id = ask_agent(
        db,
        from_agent=from_agent,
        to_agent=to_agent,
        question=f"[TEST] {from_agent} → {to_agent}: What is the current regime classification and are there any bots showing edge degradation?",
    )
    return {"ok": True, "from": from_agent, "to": to_agent, "message_id": str(msg_id)}


@router.post("/intro-conversation/run")
def run_intro_conversation(force: bool = False, db: Session = Depends(get_db)):
    """
    Fire the one-time team intro sequence in #fund-team-chat.
    7 agents post Claude-generated intros 30s apart, then Brick wraps.
    Returns {"already_run": true} immediately if already completed (unless force=true).
    """
    from agents.intro_conversation import run_intro_conversation as _run
    result = _run(db, force=force)
    return result


@router.post("/plain-english/toggle")
async def toggle_plain_english(
    channel_id: str,
    enabled: bool = True,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    """Enable/disable Plain English summaries for a Discord channel."""
    db.execute(text("""
        INSERT INTO plain_english_channels_enabled (channel_id, enabled, set_at)
        VALUES (:c, :e, :ts)
        ON CONFLICT (channel_id) DO UPDATE SET enabled = :e, set_at = :ts
    """), {"c": channel_id, "e": (1 if enabled else 0), "ts": datetime.now(timezone.utc).isoformat()})
    db.commit()
    return {"channel_id": channel_id, "enabled": enabled}
