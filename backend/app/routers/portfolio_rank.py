"""Portfolio-Rank bot admin router (Phase 1).

Read endpoints are always available so the leaderboard integration can
render bot state. Write endpoints (rebalance, enable/disable) require
BMG_PORTFOLIO_RANK_BOTS_ENABLED=true so Brock controls the rollout.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies import require_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/portfolio-rank", tags=["admin", "portfolio-rank"])


def _env_flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("true", "1", "yes")


def _row_to_bot(r) -> dict:
    return {
        "id": int(r[0]),
        "name": r[1],
        "description": r[2],
        "factor_definition": json.loads(r[3] or "{}"),
        "universe": json.loads(r[4] or "{}"),
        "rebalance_schedule": r[5],
        "long_decile": int(r[6] or 10),
        "short_decile": int(r[7] or 0),
        "position_sizing": r[8],
        "starting_capital_cents": int(r[9] or 0),
        "enabled": bool(r[10]),
        "paper_citation": r[11],
        "ssrn_id": r[12],
        "last_rebalanced_at": str(r[13]) if r[13] else None,
        "next_rebalance_at": str(r[14]) if r[14] else None,
        "created_at": str(r[15]) if r[15] else None,
    }


_BOT_COLS = (
    "id, name, description, factor_definition, universe, "
    "rebalance_schedule, long_decile, short_decile, position_sizing, "
    "starting_capital_cents, enabled, paper_citation, ssrn_id, "
    "last_rebalanced_at, next_rebalance_at, created_at"
)


@router.get("/bots")
def list_bots(
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
) -> dict:
    rows = db.execute(text(
        f"SELECT {_BOT_COLS} FROM portfolio_rank_bots ORDER BY name"
    )).fetchall()
    return {"count": len(rows), "bots": [_row_to_bot(r) for r in rows]}


@router.get("/bots/{bot_id}")
def get_bot(
    bot_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
) -> dict:
    row = db.execute(text(
        f"SELECT {_BOT_COLS} FROM portfolio_rank_bots WHERE id = :bid"
    ), {"bid": bot_id}).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="bot not found")
    return _row_to_bot(row)


@router.get("/bots/{bot_id}/holdings")
def get_holdings(
    bot_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
) -> dict:
    rows = db.execute(text("""
        SELECT symbol, side, target_weight, actual_weight,
               entry_price_cents, current_price_cents,
               entry_ts, last_marked_at, current_pnl_cents
        FROM portfolio_rank_holdings
        WHERE bot_id = :bid
        ORDER BY symbol
    """), {"bid": bot_id}).fetchall()
    return {
        "bot_id": bot_id,
        "count": len(rows),
        "holdings": [
            {
                "symbol": r[0],
                "side": r[1],
                "target_weight": float(r[2] or 0),
                "actual_weight": float(r[3] or 0),
                "entry_price_cents": int(r[4]) if r[4] is not None else None,
                "current_price_cents": int(r[5]) if r[5] is not None else None,
                "entry_ts": str(r[6]) if r[6] else None,
                "last_marked_at": str(r[7]) if r[7] else None,
                "current_pnl_cents": int(r[8] or 0),
            }
            for r in rows
        ],
    }


@router.get("/bots/{bot_id}/rebalance-log")
def get_rebalance_log(
    bot_id: int,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
) -> dict:
    limit = max(1, min(200, limit))
    rows = db.execute(text("""
        SELECT id, triggered_by, ranking_output, target_basket,
               adds, removes, latency_ms, error, created_at
        FROM portfolio_rank_rebalance_log
        WHERE bot_id = :bid
        ORDER BY created_at DESC
        LIMIT :lim
    """), {"bid": bot_id, "lim": limit}).fetchall()
    return {
        "bot_id": bot_id,
        "count": len(rows),
        "entries": [
            {
                "id": int(r[0]),
                "triggered_by": r[1],
                "ranking_output": json.loads(r[2] or "{}"),
                "target_basket": json.loads(r[3] or "{}"),
                "adds": json.loads(r[4] or "[]"),
                "removes": json.loads(r[5] or "[]"),
                "latency_ms": int(r[6] or 0),
                "error": r[7],
                "created_at": str(r[8]) if r[8] else None,
            }
            for r in rows
        ],
    }


@router.post("/bots/{bot_id}/rebalance")
def rebalance_bot(
    bot_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
) -> dict:
    """Trigger one rebalance for the bot. Feature-flag gated."""
    if not _env_flag("BMG_PORTFOLIO_RANK_BOTS_ENABLED", "false"):
        raise HTTPException(
            status_code=403,
            detail="portfolio-rank bots disabled — set BMG_PORTFOLIO_RANK_BOTS_ENABLED=true",
        )
    from strategy_lab.portfolio_rank_runner import rebalance as _rebalance
    result = _rebalance(db, bot_id, triggered_by="manual")
    if "error" in result and result["error"]:
        raise HTTPException(status_code=400, detail=result)
    return result


@router.post("/nightly-run")
def nightly_run_endpoint(
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
) -> dict:
    """Manually trigger the nightly rebalance loop.

    Same code path as the 03:00 America/Chicago cron. Feature-flag gated
    inside nightly_run(). Useful for verification without waiting for
    cron; also lets Brock re-run a missed night.
    """
    if not _env_flag("BMG_PORTFOLIO_RANK_BOTS_ENABLED", "false"):
        raise HTTPException(
            status_code=403,
            detail="portfolio-rank bots disabled — set BMG_PORTFOLIO_RANK_BOTS_ENABLED=true",
        )
    from strategy_lab.portfolio_rank_runner import nightly_run as _run
    return _run(db, triggered_by="manual_nightly_endpoint")


@router.get("/status")
def status(
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
) -> dict:
    counts = db.execute(text(
        "SELECT COUNT(*) FROM portfolio_rank_bots"
    )).fetchone()
    enabled = db.execute(text(
        "SELECT COUNT(*) FROM portfolio_rank_bots WHERE enabled = 1"
    )).fetchone()
    holdings = db.execute(text(
        "SELECT COUNT(*) FROM portfolio_rank_holdings"
    )).fetchone()
    logs = db.execute(text(
        "SELECT COUNT(*) FROM portfolio_rank_rebalance_log"
    )).fetchone()
    return {
        "feature_enabled": _env_flag("BMG_PORTFOLIO_RANK_BOTS_ENABLED", "false"),
        "live_orders_enabled": _env_flag("BMG_PORTFOLIO_RANK_LIVE_ORDERS", "false"),
        "bot_count_total": int(counts[0]) if counts else 0,
        "bot_count_enabled": int(enabled[0]) if enabled else 0,
        "holdings_total": int(holdings[0]) if holdings else 0,
        "rebalance_log_total": int(logs[0]) if logs else 0,
    }
