from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.backtesting.engine import PRESET_LABELS, load_cache, run_backtest
from app.db.models.bots import BotProfile
from app.db.models.pipeline import BacktestRun, CandidateStateHistory, StrategyCandidate
from app.db.models.users import User
from app.db.session import get_db
from app.dependencies import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/backtest", tags=["backtest"])

_running = False


def _run_and_flag(period_years: int) -> None:
    global _running
    try:
        run_backtest(period_years)
    except Exception as e:
        logger.error("Backtest background task failed: %s", e, exc_info=True)
    finally:
        _running = False


class CandidateBacktestBody(BaseModel):
    candidate_name: Optional[str] = None
    start_date: str = "2023-01-01"
    end_date: str = "2024-12-31"
    capital: float = 100_000.0


@router.get("/status")
async def backtest_status(current_user: User = Depends(get_current_user)):
    """Return whether a backtest is running and when the last one completed."""
    cache = load_cache()
    return {
        "running": _running,
        "available": cache is not None,
        "run_date": cache.get("run_date") if cache else None,
        "period_years": cache.get("period_years") if cache else None,
    }


@router.post("/run")
async def trigger_backtest(
    background_tasks: BackgroundTasks,
    body: CandidateBacktestBody = Body(default_factory=CandidateBacktestBody),
    period_years: int = Query(default=3, ge=1, le=5),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Enqueue a candidate backtest (body with candidate_name) or run a preset strategy backtest."""
    if body.candidate_name:
        c = db.query(StrategyCandidate).filter(StrategyCandidate.name == body.candidate_name).first()
        if not c:
            raise HTTPException(status_code=404, detail=f"Candidate '{body.candidate_name}' not found")
        if c.state == "RETIRED":
            raise HTTPException(status_code=409, detail="Candidate is retired")
        job_id = str(uuid.uuid4())
        run = BacktestRun(
            candidate_id=c.id,
            job_id=job_id,
            status="queued",
            start_date=body.start_date,
            end_date=body.end_date,
            params_json=json.dumps({"capital": body.capital}),
        )
        db.add(run)
        from_state = c.state
        c.state = "BACKTEST_QUEUED"
        c.updated_at = datetime.now(timezone.utc)
        db.add(CandidateStateHistory(
            candidate_id=c.id, from_state=from_state, to_state="BACKTEST_QUEUED",
            reason="enqueued via /api/backtest/run", triggered_by=str(current_user.id),
        ))
        db.commit()
        logger.info("[backtest/run] enqueued candidate=%s job=%s", body.candidate_name, job_id)
        return {"job_id": job_id, "mode": "candidate", "candidate_name": body.candidate_name}

    # Preset strategy backtest (legacy path)
    global _running
    if _running:
        raise HTTPException(status_code=409, detail="Backtest already running")
    _running = True
    loop = asyncio.get_running_loop()
    background_tasks.add_task(loop.run_in_executor, None, _run_and_flag, period_years)
    return {"ok": True, "message": "Backtest started — check /status to track progress", "mode": "preset"}


@router.get("/results")
async def backtest_results(current_user: User = Depends(get_current_user)):
    """Return summary metrics for all strategies from the last completed backtest."""
    cache = load_cache()
    if not cache:
        raise HTTPException(status_code=404, detail="No backtest results yet — run one first")

    summary = []
    for key, metrics in cache.get("results", {}).items():
        if not metrics:
            continue
        summary.append({
            "strategy_key":   key,
            "strategy_label": PRESET_LABELS.get(key, key),
            **metrics,
        })

    summary.sort(key=lambda x: x.get("total_return_pct", 0), reverse=True)

    return {
        "run_date":     cache.get("run_date"),
        "period_years": cache.get("period_years", 3),
        "strategies":   summary,
    }


@router.get("/results/{strategy_key}")
async def backtest_detail(
    strategy_key: str,
    current_user: User = Depends(get_current_user),
):
    """Return equity curve + trade list for a single strategy."""
    cache = load_cache()
    if not cache:
        raise HTTPException(status_code=404, detail="No backtest results yet")
    if strategy_key not in cache.get("results", {}):
        raise HTTPException(status_code=404, detail="Strategy not found")

    return {
        "strategy_key":   strategy_key,
        "strategy_label": PRESET_LABELS.get(strategy_key, strategy_key),
        "metrics":        cache["results"].get(strategy_key, {}),
        "equity_curve":   cache.get("equity_curves", {}).get(strategy_key, []),
        "trades":         cache.get("trades", {}).get(strategy_key, []),
        "period_years":   cache.get("period_years", 3),
        "run_date":       cache.get("run_date"),
    }
