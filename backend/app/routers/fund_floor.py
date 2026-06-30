"""Fund Floor router — briefing board, agent overlay, veto SSE stream.

GET  /api/fund-floor/cio-briefing-board     — latest briefing
GET  /api/fund-floor/agent-overlay          — per-agent overlay data
GET  /api/fund-floor/veto-stream            — SSE stream of new veto_log rows
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/fund-floor", tags=["fund-floor"])

# Static one-liners for SPACE TALK pre-first-meeting fallback
_STATIC_LINES: dict[str, dict] = {
    "portfolio_manager":    {"display_name": "BRICK",   "role": "PORTFOLIO MANAGER",    "line": "Capital flows the way I tell it to."},
    "chief_risk_officer":   {"display_name": "DICK",    "role": "CHIEF RISK OFFICER",   "line": "I veto first, apologize never."},
    "equity_researcher":    {"display_name": "NICK",    "role": "EQUITY RESEARCHER",    "line": "AAPL up, NVDA crowded, MSFT boring."},
    "quant_researcher":     {"display_name": "MICK",    "role": "QUANT RESEARCHER",     "line": "Alpha decays. Numbers don't."},
    "macro_strategist":     {"display_name": "RICK",    "role": "MACRO STRATEGIST",     "line": "Regime: chop. Get used to it."},
    "data_quality_watcher": {"display_name": "VICK",    "role": "DATA QUALITY WATCHER", "line": "If the feed lies, I tell."},
    "execution_auditor":    {"display_name": "SLICK",   "role": "EXECUTION AUDITOR",    "line": "Slippage is the silent killer."},
    "operations":           {"display_name": "WICK",    "role": "OPERATIONS",           "line": "Back office, front-line eyes."},
    "sentinel_devops":      {"display_name": "PATRICK", "role": "SENTINEL DEVOPS",      "line": "Infra holds. For now."},
}


@router.get("/cio-briefing-board")
def cio_briefing_board(
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    """Returns latest briefing; 404 if none.

    Shape matches window.BMGFloor.setBriefing.
    {briefing_id, meeting_id, posted_at, markdown_body, summary_one_liner,
     vetoes_used, needs_brock}
    """
    row = db.execute(
        text(
            "SELECT b.briefing_id, b.meeting_id, b.posted_at, b.markdown_body, "
            "       b.summary_one_liner, b.needs_brock, m.vetoes_used "
            "FROM fund_briefings b "
            "LEFT JOIN fund_meetings m ON m.meeting_id = b.meeting_id "
            "ORDER BY b.created_at DESC LIMIT 1"
        )
    ).fetchone()
    if not row:
        raise HTTPException(404, "no briefing yet")
    result = dict(row._mapping)
    result["needs_brock"] = bool(result.get("needs_brock"))
    return result


@router.get("/agent-overlay")
def agent_overlay(
    agent_name: str = Query(...),
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    """Return per-agent overlay data for Fund Floor NPC display.

    {agent_id, display_name, role, status, last_opening_read, last_decision,
     daily_cost_usd, line}

    status: active if read in last 24h, degraded if 24h-7d, down otherwise.
    last_opening_read: most recent for this agent.
    last_decision: most recent agent_commitments row.
    daily_cost_usd: sum llm_call_log today (UTC) for this agent.
    line: static fallback if no opening read; else first 80 chars of what_im_seeing.
    """
    if agent_name not in _STATIC_LINES:
        raise HTTPException(404, f"Unknown agent: {agent_name}")

    static = _STATIC_LINES[agent_name]

    # Agent status from agent_opening_reads recency
    status = "down"
    try:
        recency_row = db.execute(
            text(
                "SELECT MAX(created_at) AS last_read FROM agent_opening_reads "
                "WHERE agent_name = :an AND status = 'ok'"
            ),
            {"an": agent_name},
        ).fetchone()
        if recency_row and recency_row[0]:
            last_read = str(recency_row[0])
            check_24h = db.execute(
                text("SELECT 1 WHERE :lr >= datetime('now', '-24 hours')"),
                {"lr": last_read},
            ).fetchone()
            check_7d = db.execute(
                text("SELECT 1 WHERE :lr >= datetime('now', '-7 days')"),
                {"lr": last_read},
            ).fetchone()
            if check_24h:
                status = "active"
            elif check_7d:
                status = "degraded"
    except Exception as exc:
        logger.warning("[fund_floor] agent status check failed for %s: %s", agent_name, exc)

    # Last opening read
    last_opening_read = None
    line = static["line"]
    try:
        read_row = db.execute(
            text(
                "SELECT meeting_id, structured_read_json, created_at "
                "FROM agent_opening_reads "
                "WHERE agent_name = :an AND status = 'ok' "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"an": agent_name},
        ).fetchone()
        if read_row:
            try:
                parsed = json.loads(read_row[1])
                what_im_seeing = parsed.get("what_im_seeing", "")
                confidence = parsed.get("confidence_in_book", "")
                if what_im_seeing:
                    line = what_im_seeing[:80]
                last_opening_read = {
                    "meeting_id": read_row[0],
                    "what_im_seeing": what_im_seeing,
                    "confidence_in_book": confidence,
                }
            except (json.JSONDecodeError, KeyError):
                pass
    except Exception as exc:
        logger.warning("[fund_floor] last_opening_read failed for %s: %s", agent_name, exc)

    # Last decision (agent_commitments)
    last_decision = None
    try:
        dec_row = db.execute(
            text(
                "SELECT action_description, deadline, status FROM agent_commitments "
                "WHERE owner_agent = :an ORDER BY created_at DESC LIMIT 1"
            ),
            {"an": agent_name},
        ).fetchone()
        if dec_row:
            last_decision = {
                "action": dec_row[0],
                "deadline": str(dec_row[1]),
                "status": dec_row[2],
            }
    except Exception as exc:
        logger.warning("[fund_floor] last_decision failed for %s: %s", agent_name, exc)

    # Daily cost (UTC day)
    daily_cost_usd = 0.0
    try:
        cost_row = db.execute(
            text(
                "SELECT COALESCE(SUM(estimated_cost_cents), 0) FROM llm_call_log "
                "WHERE agent_name = :an AND created_at >= datetime('now', 'start of day')"
            ),
            {"an": agent_name},
        ).scalar()
        daily_cost_usd = float(cost_row or 0) / 100.0
    except Exception as exc:
        logger.warning("[fund_floor] daily_cost failed for %s: %s", agent_name, exc)

    return {
        "agent_id": agent_name,
        "display_name": static["display_name"],
        "role": static["role"],
        "status": status,
        "last_opening_read": last_opening_read,
        "last_decision": last_decision,
        "daily_cost_usd": daily_cost_usd,
        "line": line,
    }


@router.get("/veto-stream")
async def veto_stream(_user=Depends(get_current_user)):
    """SSE stream — emits new veto_log rows as they're inserted.

    Polls every 2s. Keep-alive comment every 25s. Disconnect on client close.
    Yields: 'data: {...json...}\\n\\n'
    """
    async def gen():
        from app.db.session import SessionLocal
        db = SessionLocal()
        try:
            row = db.execute(text("SELECT COALESCE(MAX(id), 0) FROM veto_log")).fetchone()
            last_id = int(row[0]) if row else 0
            last_keepalive = asyncio.get_event_loop().time()
            while True:
                await asyncio.sleep(2)
                try:
                    new_rows = db.execute(
                        text(
                            "SELECT id, meeting_id, vetoed_target_proposal, reason, created_at "
                            "FROM veto_log WHERE id > :last ORDER BY id"
                        ),
                        {"last": last_id},
                    ).fetchall()
                    for r in new_rows:
                        payload = {
                            "meeting_id": r[1],
                            "vetoed_target": r[2],
                            "reason": r[3],
                            "ts": str(r[4]),
                        }
                        yield f"data: {json.dumps(payload)}\n\n"
                        last_id = max(last_id, int(r[0]))
                except Exception as exc:
                    logger.warning("[fund_floor] veto-stream query failed: %s", exc)

                now = asyncio.get_event_loop().time()
                if now - last_keepalive > 25:
                    yield ": keepalive\n\n"
                    last_keepalive = now
        finally:
            db.close()

    return StreamingResponse(gen(), media_type="text/event-stream")
