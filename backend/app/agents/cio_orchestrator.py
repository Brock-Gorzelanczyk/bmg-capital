"""CIO Orchestrator — entry point for manual CIO Morning Meeting kickoff.

Zero direct SDK usage. Zero calls to claude binary.
ALL LLM inference routed through call_llm via cio_chair.run_meeting.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.cio_chair import (
    run_meeting,
    render_briefing_markdown,
    build_canonical_snapshot,
    _load_memory,
)
from app.services.cio_discord import post_cio_briefing

logger = logging.getLogger(__name__)


def _new_meeting_id() -> str:
    return "mtg_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _new_briefing_id() -> str:
    return "brf_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _summarize_one_liner(result, snapshot: dict) -> str:
    """Derive a one-line summary for the briefing header + Discord embed."""
    if result.status in ("failed_budget", "failed_timeout", "failed_partial"):
        return f"PARTIAL: {result.failure_reason or result.status}"
    if result.top_items:
        p0s = [it for it in result.top_items if it.severity == "P0"]
        if p0s:
            return f"P0 ALERT: {p0s[0].title[:80]} — {result.vetoes_used} veto(s)"
        top = result.top_items[0]
        return f"{top.severity}: {top.title[:80]} — {result.vetoes_used} veto(s), cost ${result.total_cost_usd:.4f}"
    pv = snapshot.get("pv_dollars", 0)
    return f"Meeting completed — PV ${pv:,.0f}, no items surfaced, cost ${result.total_cost_usd:.4f}"


def create_meeting_record(db: Session, *, runner_label: str = "manual_api") -> str:
    """Insert fund_meetings row with status='running' and return the meeting_id.

    Returns the new meeting_id. Commits the INSERT. Caller (router) will spawn
    run_meeting_background(meeting_id) into FastAPI BackgroundTasks.

    Raises HTTPException(409) if an in-progress meeting exists started within last 15 min.
    The 409 check + INSERT happen in the SAME transaction (SELECT then INSERT) — SQLite's
    default isolation is sufficient for this rare-write path.
    """
    from fastapi import HTTPException

    existing = db.execute(
        text(
            "SELECT meeting_id FROM fund_meetings "
            "WHERE status='running' AND started_at > datetime('now', '-15 minutes') LIMIT 1"
        )
    ).fetchone()
    if existing:
        raise HTTPException(409, f"meeting already in progress: {existing[0]}")

    meeting_id = _new_meeting_id()
    started_at_iso = datetime.now(timezone.utc).isoformat()
    db.execute(
        text(
            "INSERT INTO fund_meetings "
            "(meeting_id, started_at, status, created_by_runner) "
            "VALUES (:mid, :sa, 'running', :rl)"
        ),
        {"mid": meeting_id, "sa": started_at_iso, "rl": runner_label},
    )
    db.commit()
    return meeting_id


def kick_off_cio_meeting(
    db: Session,
    *,
    runner_label: str = "manual_api",
    budget_cap_usd: float = 1.50,
    daily_cap_usd: float = 3.00,
    wall_clock_cap_seconds: int = 600,
    dry_run: bool = False,
) -> dict:
    """Synchronous full-meeting kick-off. Used by tests + future cron.

    For HTTP callers, prefer the background-task pattern in the router
    (create_meeting_record + run_meeting_background) so requests return in <2s.

    Returns:
        {meeting_id, briefing_id, cost_usd, duration_s, status, vetoes_used,
         discord_message_id, summary_one_liner, needs_brock, markdown_body (dry_run only)}
    """
    if dry_run:
        # Dry run: skip row insert, run inline, return result
        meeting_id = _new_meeting_id()
    else:
        meeting_id = create_meeting_record(db, runner_label=runner_label)

    snapshot = build_canonical_snapshot(db)
    memory = _load_memory(db)

    result = run_meeting(  # sync wrapper from cio_chair
        db,
        meeting_id=meeting_id,
        budget_cap_usd=budget_cap_usd,
        daily_cap_usd=daily_cap_usd,
        wall_clock_cap_seconds=wall_clock_cap_seconds,
        poll_dick_veto=True,
        dry_run=dry_run,
        skip_row_insert=not dry_run,  # row created above for non-dry runs
    )

    md = render_briefing_markdown(result, snapshot, memory)
    summary = _summarize_one_liner(result, snapshot)
    needs_brock = (result.status != "completed") or any(
        it.severity == "P0" for it in result.top_items
    )

    briefing_id: Optional[str] = None
    discord_message_id: Optional[str] = None

    if not dry_run:
        briefing_id = _new_briefing_id()
        try:
            db.execute(
                text(
                    "INSERT INTO fund_briefings "
                    "(briefing_id, meeting_id, markdown_body, summary_one_liner, needs_brock) "
                    "VALUES (:b, :m, :md, :s, :nb)"
                ),
                {
                    "b": briefing_id,
                    "m": meeting_id,
                    "md": md,
                    "s": summary,
                    "nb": 1 if needs_brock else 0,
                },
            )
            db.execute(
                text("UPDATE fund_meetings SET briefing_id=:b WHERE meeting_id=:m"),
                {"b": briefing_id, "m": meeting_id},
            )
            db.commit()
        except Exception as exc:
            logger.error("[cio_orchestrator] briefing INSERT failed: %s", exc)

        discord_message_id = post_cio_briefing(
            markdown_body=md,
            summary_one_liner=summary,
            needs_brock=needs_brock,
            db=db,
            briefing_id=briefing_id,
            vetoes_used=result.vetoes_used,
            cost_usd=result.total_cost_usd,
            duration_seconds=result.duration_seconds,
        )

    return {
        "meeting_id": meeting_id,
        "briefing_id": briefing_id,
        "cost_usd": result.total_cost_usd,
        "duration_s": result.duration_seconds,
        "status": result.status,
        "vetoes_used": result.vetoes_used,
        "discord_message_id": discord_message_id,
        "summary_one_liner": summary,
        "needs_brock": needs_brock,
        "markdown_body": md if dry_run else None,
    }
