"""cio_meeting_runner — background task entry point for CIO Morning Meeting.

Owns its own SessionLocal(). Wraps the full meeting flow in a 15-min watchdog.
Spawned from the router via FastAPI BackgroundTasks.

DO NOT import call_llm or the anthropic SDK here.
DO NOT reuse the request-scoped db session — always SessionLocal() in the runner.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

# 15-min hard watchdog. Safety net above run_meeting's own wall_clock_cap_seconds (default 600s).
BG_WATCHDOG_SECONDS = 900


async def run_meeting_background(
    meeting_id: str,
    *,
    runner_label: str = "manual_api",
    budget_cap_usd: float = 1.50,
    daily_cap_usd: float = 3.00,
    wall_clock_cap_seconds: int = 600,
) -> None:
    """Entry point for FastAPI BackgroundTasks.

    Owns a fresh SessionLocal(). Wraps the whole flow in asyncio.wait_for(..., BG_WATCHDOG_SECONDS).
    On watchdog fire: forcibly UPDATEs fund_meetings.status='failed_timeout' + failure_reason='bg_watchdog_15min'.
    On any other exception: UPDATEs status='failed_partial' + failure_reason=str(exc)[:500].
    Always closes the session in finally.
    """
    db = SessionLocal()
    try:
        try:
            await asyncio.wait_for(
                _run_meeting_inner(
                    db, meeting_id,
                    runner_label=runner_label,
                    budget_cap_usd=budget_cap_usd,
                    daily_cap_usd=daily_cap_usd,
                    wall_clock_cap_seconds=wall_clock_cap_seconds,
                ),
                timeout=BG_WATCHDOG_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.error("[cio_meeting_runner] watchdog fired for meeting %s", meeting_id)
            _mark_failed(db, meeting_id, "failed_timeout", "bg_watchdog_15min")
        except Exception as exc:
            logger.exception("[cio_meeting_runner] meeting %s crashed: %s", meeting_id, exc)
            _mark_failed(db, meeting_id, "failed_partial", f"bg_exception: {str(exc)[:480]}")
    finally:
        db.close()


async def _run_meeting_inner(
    db, meeting_id: str, *, runner_label: str, budget_cap_usd: float,
    daily_cap_usd: float, wall_clock_cap_seconds: int,
) -> None:
    """Calls the (now async) chair runner, then renders briefing, posts Discord, finalizes."""
    # Imported here to avoid circular import (orchestrator imports runner conditionally)
    from app.services.cio_chair import (
        run_meeting_async,
        render_briefing_markdown,
        build_canonical_snapshot,
        _load_memory,
    )
    from app.services.cio_discord import post_cio_briefing
    from app.agents.cio_orchestrator import (
        _summarize_one_liner,
        _new_briefing_id,
    )
    from sqlalchemy import text

    snapshot = build_canonical_snapshot(db)
    memory = _load_memory(db)

    # Stamp runner label up-front (row already exists from create_meeting_record)
    try:
        db.execute(
            text("UPDATE fund_meetings SET created_by_runner=:r WHERE meeting_id=:m"),
            {"r": runner_label, "m": meeting_id},
        )
        db.commit()
    except Exception as exc:
        logger.warning("[cio_meeting_runner] runner_label stamp failed: %s", exc)

    # run_meeting_async returns the same MeetingResult dataclass run_meeting did.
    result = await run_meeting_async(
        db,
        meeting_id=meeting_id,
        budget_cap_usd=budget_cap_usd,
        daily_cap_usd=daily_cap_usd,
        wall_clock_cap_seconds=wall_clock_cap_seconds,
        poll_dick_veto=True,
        dry_run=False,
        skip_row_insert=True,  # row already exists; router created it in-request
    )

    md = render_briefing_markdown(result, snapshot, memory)
    summary = _summarize_one_liner(result, snapshot)
    needs_brock = (result.status != "completed") or any(
        it.severity == "P0" for it in result.top_items
    )

    briefing_id = _new_briefing_id()
    try:
        db.execute(
            text(
                "INSERT INTO fund_briefings "
                "(briefing_id, meeting_id, markdown_body, summary_one_liner, needs_brock) "
                "VALUES (:b, :m, :md, :s, :nb)"
            ),
            {"b": briefing_id, "m": meeting_id, "md": md, "s": summary, "nb": 1 if needs_brock else 0},
        )
        db.execute(
            text("UPDATE fund_meetings SET briefing_id=:b WHERE meeting_id=:m"),
            {"b": briefing_id, "m": meeting_id},
        )
        db.commit()
    except Exception as exc:
        logger.error("[cio_meeting_runner] briefing INSERT failed: %s", exc)

    # Discord post is sync; wrap in to_thread to not block the event loop.
    try:
        discord_message_id = await asyncio.to_thread(
            post_cio_briefing,
            markdown_body=md,
            summary_one_liner=summary,
            needs_brock=needs_brock,
            db=db,
            briefing_id=briefing_id,
            vetoes_used=result.vetoes_used,
            cost_usd=result.total_cost_usd,
            duration_seconds=result.duration_seconds,
        )
        if discord_message_id:
            try:
                db.execute(
                    text(
                        "UPDATE fund_briefings SET discord_message_id=:d, "
                        "posted_at=CURRENT_TIMESTAMP WHERE briefing_id=:b"
                    ),
                    {"d": discord_message_id, "b": briefing_id},
                )
                db.commit()
            except Exception as exc:
                logger.warning("[cio_meeting_runner] discord_message_id stamp failed: %s", exc)
    except Exception as exc:
        logger.error("[cio_meeting_runner] Discord post failed: %s", exc)
        # Do NOT mark the whole meeting failed for a Discord error — briefing row is still saved.


def _mark_failed(db, meeting_id: str, status: str, reason: str) -> None:
    from sqlalchemy import text
    try:
        db.execute(
            text(
                "UPDATE fund_meetings SET status=:st, failure_reason=:fr, "
                "ended_at=COALESCE(ended_at, :ea), "
                "duration_seconds=COALESCE(duration_seconds, "
                "  CAST((julianday(:ea) - julianday(started_at)) * 86400 AS INTEGER)) "
                "WHERE meeting_id=:mid AND status='running'"
            ),
            {"st": status, "fr": reason, "ea": datetime.now(timezone.utc).isoformat(), "mid": meeting_id},
        )
        db.commit()
    except Exception as exc:
        logger.error("[cio_meeting_runner] _mark_failed failed for %s: %s", meeting_id, exc)
