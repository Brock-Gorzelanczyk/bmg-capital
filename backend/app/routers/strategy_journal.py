"""strategy_journal.py — read-only API for per-bot daily journal entries.

Phase 1 of the closed-loop learning system. Exposes the bot_daily_journals
table to admin users and Cowork Claude via WebFetch.

All endpoints are read-only. No POST/PATCH/DELETE. Auth via require_admin.
Response shape uses explicit dict construction (known-issues #4 — no raw ORM objects).
"""
from __future__ import annotations

import json
import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies import require_admin
from app.services.journal_writer import vault_path_for

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/strategy-journal", tags=["strategy-journal"])


def _row_to_raw(row) -> dict:
    """Convert a BotDailyJournal ORM row to a plain dict (no raw ORM objects)."""
    breakdown = None
    if row.strategies_breakdown_json:
        try:
            breakdown = json.loads(row.strategies_breakdown_json)
        except (json.JSONDecodeError, TypeError):
            breakdown = {}

    sentry = None
    if row.sentry_issues_json:
        try:
            sentry = json.loads(row.sentry_issues_json)
        except (json.JSONDecodeError, TypeError):
            sentry = []

    return {
        "id": row.id,
        "allocation_id": row.allocation_id,
        "bot_id": row.bot_id,
        "user_id": row.user_id,
        "journal_date": row.journal_date.isoformat() if hasattr(row.journal_date, "isoformat") else str(row.journal_date),
        "sleeve": row.sleeve,
        "asset_class": row.asset_class,
        "starting_capital_cents": row.starting_capital_cents,
        "ending_pv_cents": row.ending_pv_cents,
        "day_pnl_cents": row.day_pnl_cents,
        "day_return_pct": row.day_return_pct,
        "trades_count": row.trades_count,
        "winning_trades": row.winning_trades,
        "losing_trades": row.losing_trades,
        "win_rate": row.win_rate,
        "avg_winner_cents": row.avg_winner_cents,
        "avg_loser_cents": row.avg_loser_cents,
        "profit_factor": row.profit_factor,
        "avg_hold_minutes": row.avg_hold_minutes,
        "max_concurrent_positions": row.max_concurrent_positions,
        "end_of_day_positions": row.end_of_day_positions,
        "end_of_day_deployed_cents": row.end_of_day_deployed_cents,
        "deployment_pct_avg": row.deployment_pct_avg,
        "regime_vix_band": row.regime_vix_band,
        "regime_trend": row.regime_trend,
        "regime_btc_dom_band": row.regime_btc_dom_band,
        "strategies_breakdown": breakdown,
        "errors_24h": row.errors_24h,
        "sentry_issues": sentry,
        "created_at": row.created_at.isoformat() if hasattr(row.created_at, "isoformat") else str(row.created_at),
    }


@router.get("/{bot_id}/rolling/30d")
def get_rolling(
    bot_id: str,
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
) -> dict:
    """Return the latest __rolling30 pseudo-row for bot_id, or 404.

    This endpoint MUST be registered before /{bot_id}/{journal_date} to avoid
    FastAPI routing '30d' as a date parameter.
    """
    from app.db.models.bot_daily_journal import BotDailyJournal

    pseudo_bot_id = f"{bot_id}__rolling30"
    row = (
        db.query(BotDailyJournal)
        .filter(BotDailyJournal.bot_id == pseudo_bot_id)
        .order_by(BotDailyJournal.journal_date.desc())
        .first()
    )
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"No rolling summary found for bot_id={bot_id}",
        )

    rolling_data = None
    if row.strategies_breakdown_json:
        try:
            rolling_data = json.loads(row.strategies_breakdown_json)
        except (json.JSONDecodeError, TypeError):
            rolling_data = {}

    return {
        "bot_id": bot_id,
        "pseudo_bot_id": pseudo_bot_id,
        "journal_date": row.journal_date.isoformat() if hasattr(row.journal_date, "isoformat") else str(row.journal_date),
        "rolling_summary": rolling_data,
        "raw": _row_to_raw(row),
    }


@router.get("/{bot_id}/{journal_date}")
def get_journal(
    bot_id: str,
    journal_date: date,
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
) -> dict:
    """Return the journal row for bot_id on journal_date.

    Response: {bot_id, journal_date, frontmatter_yaml, body_md, vault_path, raw: {...}}.
    Returns 404 if not found.
    """
    from app.db.models.bot_daily_journal import BotDailyJournal
    from sqlalchemy import and_

    row = (
        db.query(BotDailyJournal)
        .filter(
            and_(
                BotDailyJournal.bot_id == bot_id,
                BotDailyJournal.journal_date == journal_date,
                # Exclude rolling pseudo-rows
                ~BotDailyJournal.bot_id.like("%__rolling30"),
            )
        )
        .first()
    )
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"No journal found for bot_id={bot_id} on {journal_date}",
        )

    vpath = vault_path_for(bot_id, journal_date)

    return {
        "bot_id": row.bot_id,
        "journal_date": row.journal_date.isoformat() if hasattr(row.journal_date, "isoformat") else str(row.journal_date),
        "frontmatter_yaml": row.frontmatter_yaml or "",
        "body_md": row.body_md or "",
        "vault_path": vpath,
        "raw": _row_to_raw(row),
    }


@router.get("/{bot_id}")
def list_journals(
    bot_id: str,
    limit: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
) -> dict:
    """Return the last `limit` journal entries for bot_id, ordered desc by journal_date.

    Excludes pseudo-rows with '__rolling30' suffix.
    Response: {bot_id, count, entries: [{journal_date, day_pnl_cents, day_return_pct, trades_count}]}.
    """
    from app.db.models.bot_daily_journal import BotDailyJournal

    rows = (
        db.query(BotDailyJournal)
        .filter(
            BotDailyJournal.bot_id == bot_id,
            ~BotDailyJournal.bot_id.like("%__rolling30"),
        )
        .order_by(BotDailyJournal.journal_date.desc())
        .limit(limit)
        .all()
    )

    entries = [
        {
            "journal_date": r.journal_date.isoformat() if hasattr(r.journal_date, "isoformat") else str(r.journal_date),
            "day_pnl_cents": r.day_pnl_cents,
            "day_return_pct": r.day_return_pct,
            "trades_count": r.trades_count,
            "win_rate": r.win_rate,
        }
        for r in rows
    ]

    return {
        "bot_id": bot_id,
        "count": len(entries),
        "entries": entries,
    }
