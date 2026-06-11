"""Candidate pipeline API — strategy lifecycle from CANDIDATE to PROMOTED."""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.models.pipeline import (
    BacktestRun,
    CandidateStateHistory,
    StrategyCandidate,
    WfaRun,
)
from app.db.session import get_db
from app.dependencies import get_current_user
from app.db.models.users import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/candidates", tags=["candidates"])

_CANDIDATES_DIR = Path(__file__).parent.parent.parent.parent / "strategy_lab" / "candidates"

# ── Valid state transitions ────────────────────────────────────────────────────

_VALID_TRANSITIONS: dict[str, list[str]] = {
    "CANDIDATE":      ["BACKTEST_QUEUED", "RETIRED"],
    "BACKTEST_QUEUED": ["BACKTEST_DONE", "CANDIDATE"],
    "BACKTEST_DONE":  ["WFA_QUEUED", "RETIRED"],
    "WFA_QUEUED":     ["WFA_DONE", "BACKTEST_DONE"],
    "WFA_DONE":       ["SHADOW_PAPER", "RETIRED"],
    "SHADOW_PAPER":   ["PROMOTED", "RETIRED"],
    "PROMOTED":       ["RETIRED"],
    "RETIRED":        [],
}


def _transition(db: Session, candidate: StrategyCandidate, to_state: str, reason: str = "", triggered_by: str = "system") -> None:
    from_state = candidate.state
    history = CandidateStateHistory(
        candidate_id=candidate.id,
        from_state=from_state,
        to_state=to_state,
        reason=reason,
        triggered_by=triggered_by,
    )
    candidate.state = to_state
    candidate.updated_at = datetime.now(timezone.utc)
    db.add(history)
    db.commit()


def _candidate_detail(c: StrategyCandidate, db: Session) -> dict:
    latest_bt = (
        db.query(BacktestRun)
        .filter(BacktestRun.candidate_id == c.id, BacktestRun.status == "done")
        .order_by(BacktestRun.completed_at.desc())
        .first()
    )
    latest_wfa = (
        db.query(WfaRun)
        .filter(WfaRun.candidate_id == c.id, WfaRun.status == "done")
        .order_by(WfaRun.completed_at.desc())
        .first()
    )
    return {
        "id": c.id,
        "name": c.name,
        "file_path": c.file_path,
        "asset_class": c.asset_class,
        "style": c.style,
        "state": c.state,
        "promoted_at": c.promoted_at.isoformat() if c.promoted_at else None,
        "retired_at": c.retired_at.isoformat() if c.retired_at else None,
        "created_at": c.created_at.isoformat(),
        "updated_at": c.updated_at.isoformat(),
        "metadata_json": c.metadata_json,
        "latest_backtest": {
            "job_id": latest_bt.job_id,
            "completed_at": latest_bt.completed_at.isoformat() if latest_bt.completed_at else None,
            "net_sharpe": latest_bt.net_sharpe,
            "max_drawdown_pct": latest_bt.max_drawdown_pct,
            "win_rate": latest_bt.win_rate,
            "profit_factor": latest_bt.profit_factor,
            "n_trades": latest_bt.n_trades,
        } if latest_bt else None,
        "latest_wfa": {
            "job_id": latest_wfa.job_id,
            "completed_at": latest_wfa.completed_at.isoformat() if latest_wfa.completed_at else None,
            "wfe": latest_wfa.wfe,
            "pbo": latest_wfa.pbo,
            "dsr": latest_wfa.dsr,
            "aggregate_oos_sharpe": latest_wfa.aggregate_oos_sharpe,
            "n_walks": latest_wfa.n_walks,
        } if latest_wfa else None,
    }


# ── POST /sync ────────────────────────────────────────────────────────────────

@router.post("/sync")
def sync_candidates(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    """Scan candidates/ folder and upsert strategy_candidates rows."""
    if not _CANDIDATES_DIR.exists():
        return {"synced": 0, "message": "candidates/ directory not found"}

    synced = 0
    for path in sorted(_CANDIDATES_DIR.glob("*.py")):
        if path.name.startswith("_"):
            continue
        name = path.stem
        existing = db.query(StrategyCandidate).filter(StrategyCandidate.name == name).first()
        if existing:
            existing.file_path = str(path)
            existing.updated_at = datetime.now(timezone.utc)
        else:
            candidate = StrategyCandidate(
                name=name,
                file_path=str(path),
                state="CANDIDATE",
            )
            db.add(candidate)
            synced += 1
    db.commit()
    total = db.query(StrategyCandidate).count()
    return {"synced": synced, "total": total}


# ── GET / ─────────────────────────────────────────────────────────────────────

@router.get("/")
def list_candidates(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    candidates = db.query(StrategyCandidate).order_by(StrategyCandidate.name).all()
    return {"candidates": [_candidate_detail(c, db) for c in candidates]}


# ── GET /{name} ───────────────────────────────────────────────────────────────

@router.get("/{name}")
def get_candidate(name: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    c = db.query(StrategyCandidate).filter(StrategyCandidate.name == name).first()
    if not c:
        raise HTTPException(status_code=404, detail="Candidate not found")
    detail = _candidate_detail(c, db)
    history = (
        db.query(CandidateStateHistory)
        .filter(CandidateStateHistory.candidate_id == c.id)
        .order_by(CandidateStateHistory.created_at.desc())
        .all()
    )
    detail["state_history"] = [
        {
            "from_state": h.from_state,
            "to_state": h.to_state,
            "reason": h.reason,
            "triggered_by": h.triggered_by,
            "created_at": h.created_at.isoformat(),
        }
        for h in history
    ]
    return detail


# ── POST /{name}/run-backtest ─────────────────────────────────────────────────

class BacktestRequest(BaseModel):
    start_date: str = "2023-01-01"
    end_date: str = "2024-12-31"
    capital: float = 100_000.0


@router.post("/{name}/run-backtest")
def enqueue_backtest(name: str, req: BacktestRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    c = db.query(StrategyCandidate).filter(StrategyCandidate.name == name).first()
    if not c:
        raise HTTPException(status_code=404, detail="Candidate not found")
    if c.state == "RETIRED":
        raise HTTPException(status_code=409, detail="Candidate is retired")

    job_id = str(uuid.uuid4())
    run = BacktestRun(
        candidate_id=c.id,
        job_id=job_id,
        status="queued",
        start_date=req.start_date,
        end_date=req.end_date,
        params_json=json.dumps({"capital": req.capital}),
    )
    db.add(run)
    _transition(db, c, "BACKTEST_QUEUED", reason="enqueued via API", triggered_by=str(current_user.id))
    return {"job_id": job_id}


# ── POST /{name}/run-wfa ──────────────────────────────────────────────────────

class WfaRequest(BaseModel):
    is_years: float = 5.0
    oos_years: float = 1.0
    embargo_days: int = 21


@router.post("/{name}/run-wfa")
def enqueue_wfa(name: str, req: WfaRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    c = db.query(StrategyCandidate).filter(StrategyCandidate.name == name).first()
    if not c:
        raise HTTPException(status_code=404, detail="Candidate not found")
    if c.state not in ("BACKTEST_DONE", "WFA_QUEUED"):
        raise HTTPException(status_code=409, detail=f"Must be in BACKTEST_DONE state (currently {c.state})")

    job_id = str(uuid.uuid4())
    run = WfaRun(
        candidate_id=c.id,
        job_id=job_id,
        status="queued",
        is_years=req.is_years,
        oos_years=req.oos_years,
        embargo_days=req.embargo_days,
    )
    db.add(run)
    _transition(db, c, "WFA_QUEUED", reason="enqueued via API", triggered_by=str(current_user.id))
    return {"job_id": job_id}


# ── GET /{name}/promotion-eval ────────────────────────────────────────────────

@router.get("/{name}/promotion-eval")
def promotion_eval(name: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    from strategy_lab.core.pipeline.scorer import evaluate_promotion

    c = db.query(StrategyCandidate).filter(StrategyCandidate.name == name).first()
    if not c:
        raise HTTPException(status_code=404, detail="Candidate not found")

    bt = (
        db.query(BacktestRun)
        .filter(BacktestRun.candidate_id == c.id, BacktestRun.status == "done")
        .order_by(BacktestRun.completed_at.desc())
        .first()
    )
    wfa = (
        db.query(WfaRun)
        .filter(WfaRun.candidate_id == c.id, WfaRun.status == "done")
        .order_by(WfaRun.completed_at.desc())
        .first()
    )

    bt_dict  = {"net_sharpe": bt.net_sharpe,  "total_cost_pct": bt.total_cost_pct}  if bt  else {}
    wfa_dict = {"wfe": wfa.wfe, "pbo": wfa.pbo, "dsr": wfa.dsr, "aggregate_oos_sharpe": wfa.aggregate_oos_sharpe} if wfa else {}

    shadow_days = 0
    if c.state == "SHADOW_PAPER" and c.updated_at:
        shadow_days = (datetime.now(timezone.utc) - c.updated_at).days

    result = evaluate_promotion(bt_dict, wfa_dict, shadow_days=shadow_days)
    return {
        "name": name,
        "passes": result.passes,
        "score": result.score,
        "hard_failures": result.hard_failures,
        "soft_warnings": result.soft_warnings,
        "details": result.details,
    }


# ── POST /{name}/promote ──────────────────────────────────────────────────────

@router.post("/{name}/promote")
def promote_candidate(name: str, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    from strategy_lab.core.pipeline.scorer import evaluate_promotion

    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")

    c = db.query(StrategyCandidate).filter(StrategyCandidate.name == name).first()
    if not c:
        raise HTTPException(status_code=404, detail="Candidate not found")

    bt  = db.query(BacktestRun).filter(BacktestRun.candidate_id == c.id, BacktestRun.status == "done").order_by(BacktestRun.completed_at.desc()).first()
    wfa = db.query(WfaRun).filter(WfaRun.candidate_id == c.id, WfaRun.status == "done").order_by(WfaRun.completed_at.desc()).first()
    bt_dict  = {"net_sharpe": bt.net_sharpe, "total_cost_pct": bt.total_cost_pct}   if bt  else {}
    wfa_dict = {"wfe": wfa.wfe, "pbo": wfa.pbo, "dsr": wfa.dsr, "aggregate_oos_sharpe": wfa.aggregate_oos_sharpe} if wfa else {}
    shadow_days = (datetime.now(timezone.utc) - c.updated_at).days if c.state == "SHADOW_PAPER" and c.updated_at else 0

    gate = evaluate_promotion(bt_dict, wfa_dict, shadow_days=shadow_days)
    if not gate.passes:
        raise HTTPException(status_code=422, detail={"message": "Promotion gates not met", "failures": gate.hard_failures})

    _transition(db, c, "PROMOTED", reason="all gates passed", triggered_by=str(current_user.id))
    c.promoted_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True, "message": f"{name} promoted. Update YAML to allocate capital."}


# ── POST /{name}/retire ───────────────────────────────────────────────────────

@router.post("/{name}/retire")
def retire_candidate(name: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    c = db.query(StrategyCandidate).filter(StrategyCandidate.name == name).first()
    if not c:
        raise HTTPException(status_code=404, detail="Candidate not found")
    _transition(db, c, "RETIRED", reason="manual retirement", triggered_by=str(current_user.id))
    c.retired_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}


# ── GET /{name}/backtest-history ─────────────────────────────────────────────

@router.get("/{name}/backtest-history")
def backtest_history(name: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    c = db.query(StrategyCandidate).filter(StrategyCandidate.name == name).first()
    if not c:
        raise HTTPException(status_code=404, detail="Candidate not found")
    runs = (
        db.query(BacktestRun)
        .filter(BacktestRun.candidate_id == c.id)
        .order_by(BacktestRun.started_at.desc())
        .all()
    )
    return {"runs": [
        {
            "job_id": r.job_id,
            "status": r.status,
            "started_at": r.started_at.isoformat(),
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            "start_date": r.start_date,
            "end_date": r.end_date,
            "gross_sharpe": r.gross_sharpe,
            "net_sharpe": r.net_sharpe,
            "max_drawdown_pct": r.max_drawdown_pct,
            "win_rate": r.win_rate,
            "profit_factor": r.profit_factor,
            "n_trades": r.n_trades,
            "total_cost_pct": r.total_cost_pct,
            "error_message": r.error_message,
        }
        for r in runs
    ]}


# ── GET /{name}/wfa-history ───────────────────────────────────────────────────

@router.get("/{name}/wfa-history")
def wfa_history(name: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    c = db.query(StrategyCandidate).filter(StrategyCandidate.name == name).first()
    if not c:
        raise HTTPException(status_code=404, detail="Candidate not found")
    runs = (
        db.query(WfaRun)
        .filter(WfaRun.candidate_id == c.id)
        .order_by(WfaRun.started_at.desc())
        .all()
    )
    return {"runs": [
        {
            "job_id": r.job_id,
            "status": r.status,
            "started_at": r.started_at.isoformat(),
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            "is_years": r.is_years,
            "oos_years": r.oos_years,
            "embargo_days": r.embargo_days,
            "wfe": r.wfe,
            "pbo": r.pbo,
            "dsr": r.dsr,
            "aggregate_oos_sharpe": r.aggregate_oos_sharpe,
            "aggregate_is_sharpe": r.aggregate_is_sharpe,
            "n_walks": r.n_walks,
            "error_message": r.error_message,
        }
        for r in runs
    ]}


# ── GET /{name}/backtest/{job_id} ─────────────────────────────────────────────

@router.get("/{name}/backtest/{job_id}")
def get_backtest_result(name: str, job_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    c = db.query(StrategyCandidate).filter(StrategyCandidate.name == name).first()
    if not c:
        raise HTTPException(status_code=404, detail="Candidate not found")
    r = db.query(BacktestRun).filter(BacktestRun.candidate_id == c.id, BacktestRun.job_id == job_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Backtest run not found")
    prev = (
        db.query(BacktestRun)
        .filter(BacktestRun.candidate_id == c.id, BacktestRun.status == "done", BacktestRun.id < r.id)
        .order_by(BacktestRun.completed_at.desc())
        .first()
    )
    return {
        "job_id": r.job_id,
        "status": r.status,
        "started_at": r.started_at.isoformat(),
        "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        "start_date": r.start_date,
        "end_date": r.end_date,
        "params_json": r.params_json,
        "gross_sharpe": r.gross_sharpe,
        "net_sharpe": r.net_sharpe,
        "max_drawdown_pct": r.max_drawdown_pct,
        "win_rate": r.win_rate,
        "profit_factor": r.profit_factor,
        "beta_spy": r.beta_spy,
        "total_cost_pct": r.total_cost_pct,
        "n_trades": r.n_trades,
        "equity_curve_json": r.equity_curve_json,
        "error_message": r.error_message,
        "previous_run": {
            "net_sharpe": prev.net_sharpe,
            "max_drawdown_pct": prev.max_drawdown_pct,
            "win_rate": prev.win_rate,
        } if prev else None,
    }


# ── GET /{name}/wfa/{job_id} ──────────────────────────────────────────────────

@router.get("/{name}/wfa/{job_id}")
def get_wfa_result(name: str, job_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    c = db.query(StrategyCandidate).filter(StrategyCandidate.name == name).first()
    if not c:
        raise HTTPException(status_code=404, detail="Candidate not found")
    r = db.query(WfaRun).filter(WfaRun.candidate_id == c.id, WfaRun.job_id == job_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="WFA run not found")
    return {
        "job_id": r.job_id,
        "status": r.status,
        "started_at": r.started_at.isoformat(),
        "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        "is_years": r.is_years,
        "oos_years": r.oos_years,
        "embargo_days": r.embargo_days,
        "wfe": r.wfe,
        "pbo": r.pbo,
        "dsr": r.dsr,
        "aggregate_oos_sharpe": r.aggregate_oos_sharpe,
        "aggregate_is_sharpe": r.aggregate_is_sharpe,
        "n_walks": r.n_walks,
        "walks_json": r.walks_json,
        "error_message": r.error_message,
    }


# ── POST /run-all-backtests ───────────────────────────────────────────────────

@router.post("/run-all-backtests")
def run_all_backtests(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    candidates = db.query(StrategyCandidate).filter(StrategyCandidate.state == "CANDIDATE").all()
    job_ids = []
    for c in candidates:
        job_id = str(uuid.uuid4())
        run = BacktestRun(candidate_id=c.id, job_id=job_id, status="queued",
                          start_date="2021-01-01", end_date="2024-12-31",
                          params_json=json.dumps({"capital": 100_000.0}))
        db.add(run)
        _transition(db, c, "BACKTEST_QUEUED", reason="bulk enqueue", triggered_by=str(current_user.id))
        job_ids.append(job_id)
    return {"enqueued": len(job_ids), "job_ids": job_ids}
