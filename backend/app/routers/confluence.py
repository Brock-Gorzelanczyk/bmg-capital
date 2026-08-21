"""Confluence stock-selection framework — thesis journal endpoints.

Framework spec: vault research/2026-08-20-confluence-selection-framework.md

The endpoints below let Claude / Brock log a pick when the framework
surfaces one, mark open picks vs SPY, close picks (manual or via cron),
and query the running track record.

**Design invariants:**
  1. Insider cluster is a REQUIRED signal — enforced at POST time.
  2. signals_fired_count must be >= 3.
  3. Once created, signal fields + thesis + target/invalidation/horizon
     are IMMUTABLE. There is no PUT /confluence-pick endpoint by design.
  4. Excess-vs-SPY at close is the KPI. hit_win_criterion locked at
     +3% excess over horizon.
  5. All admin endpoints require auth via existing bmg_admin.sh path.

**Not implemented on purpose:**
  - No "re-open" endpoint. If a close was wrong, log a new pick.
  - No signal editing. Anti-goodhart.
  - No aggregate weight override. Each pick is standalone.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies import get_current_user
from app.db.models.confluence import ConfluencePick
from app.db.models.users import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/confluence", tags=["confluence"])


# ─── Schemas ──────────────────────────────────────────────────────────

class ConfluencePickIn(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=10)
    entry_price_cents: int = Field(..., gt=0)
    spy_price_cents_at_entry: int = Field(..., gt=0)

    # Signals — insider_cluster REQUIRED (framework rule)
    insider_cluster: bool
    short_surprise_dir: Optional[int] = None  # -1, 0, +1
    analyst_revisions_dir: Optional[int] = None  # -1, 0, +1
    fundamental_momentum: Optional[bool] = None
    inst_13f_net_add: Optional[bool] = None

    thesis_text: str = Field(..., min_length=10)
    target_price_cents: Optional[int] = None
    invalidation_price_cents: Optional[int] = None
    horizon_months: int = Field(..., gt=0, le=36)

    notes: Optional[str] = None

    @field_validator("short_surprise_dir", "analyst_revisions_dir")
    @classmethod
    def dir_is_valid(cls, v):
        if v is not None and v not in (-1, 0, 1):
            raise ValueError("direction must be -1, 0, or +1")
        return v

    @field_validator("ticker")
    @classmethod
    def ticker_upper(cls, v):
        return v.upper().strip()


class ConfluencePickClose(BaseModel):
    closed_price_cents: int = Field(..., gt=0)
    spy_price_cents_at_close: int = Field(..., gt=0)
    close_reason: str = Field(..., pattern="^(target|invalidation|horizon_reached|thesis_broken|manual)$")
    notes: Optional[str] = None


def _count_signals(pick_data: ConfluencePickIn) -> int:
    """Count how many Level-1 signals are firing in a nonzero direction."""
    n = 0
    if pick_data.insider_cluster:
        n += 1
    if pick_data.short_surprise_dir is not None and pick_data.short_surprise_dir != 0:
        n += 1
    if pick_data.analyst_revisions_dir is not None and pick_data.analyst_revisions_dir != 0:
        n += 1
    if pick_data.fundamental_momentum:
        n += 1
    if pick_data.inst_13f_net_add:
        n += 1
    return n


# ─── Endpoints ────────────────────────────────────────────────────────

@router.post("/pick")
def create_confluence_pick(
    payload: ConfluencePickIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Log a new confluence pick. Framework rules enforced at write time."""
    # RULE 1: insider cluster is REQUIRED (Cohen/Malloy/Pomorski strongest signal)
    if not payload.insider_cluster:
        raise HTTPException(
            status_code=400,
            detail="insider_cluster is REQUIRED per framework — the strongest single signal. "
                   "Without it, this is not a confluence pick.",
        )

    # RULE 2: minimum 3/5 signals must fire
    n_signals = _count_signals(payload)
    if n_signals < 3:
        raise HTTPException(
            status_code=400,
            detail=f"Framework requires >=3 signals firing. Only {n_signals} fired.",
        )

    entry_date = date.today().isoformat()

    pick = ConfluencePick(
        ticker=payload.ticker,
        entry_date=entry_date,
        entry_price_cents=payload.entry_price_cents,
        spy_price_cents_at_entry=payload.spy_price_cents_at_entry,
        insider_cluster=payload.insider_cluster,
        short_surprise_dir=payload.short_surprise_dir,
        analyst_revisions_dir=payload.analyst_revisions_dir,
        fundamental_momentum=payload.fundamental_momentum,
        inst_13f_net_add=payload.inst_13f_net_add,
        signals_fired_count=n_signals,
        thesis_text=payload.thesis_text,
        target_price_cents=payload.target_price_cents,
        invalidation_price_cents=payload.invalidation_price_cents,
        horizon_months=payload.horizon_months,
        notes=payload.notes,
    )
    db.add(pick)
    db.commit()
    db.refresh(pick)

    logger.info(
        "[confluence] new pick: %s signals=%d target=%s invalidation=%s horizon=%dmo id=%d",
        payload.ticker, n_signals, payload.target_price_cents,
        payload.invalidation_price_cents, payload.horizon_months, pick.id,
    )

    return {
        "id": pick.id,
        "ticker": pick.ticker,
        "entry_date": pick.entry_date,
        "signals_fired_count": pick.signals_fired_count,
        "status": "logged",
    }


@router.post("/close/{pick_id}")
def close_confluence_pick(
    pick_id: int,
    payload: ConfluencePickClose,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Close a pick. Computes excess-vs-SPY + hit criterion."""
    pick = db.query(ConfluencePick).filter(ConfluencePick.id == pick_id).first()
    if not pick:
        raise HTTPException(status_code=404, detail=f"pick {pick_id} not found")
    if pick.closed_date is not None:
        raise HTTPException(status_code=400, detail=f"pick {pick_id} already closed on {pick.closed_date}")

    # Compute returns
    pick.closed_date = date.today().isoformat()
    pick.closed_price_cents = payload.closed_price_cents
    pick.spy_price_cents_at_close = payload.spy_price_cents_at_close
    pick.close_reason = payload.close_reason
    if payload.notes:
        pick.notes = ((pick.notes or "") + f"\n[close] {payload.notes}").strip()

    abs_return = (payload.closed_price_cents / pick.entry_price_cents - 1.0) * 100.0
    spy_return = (payload.spy_price_cents_at_close / pick.spy_price_cents_at_entry - 1.0) * 100.0
    excess = abs_return - spy_return

    pick.absolute_return_pct = round(abs_return, 4)
    pick.excess_vs_spy_pct = round(excess, 4)
    pick.hit_win_criterion = excess >= 3.0

    db.commit()

    logger.info(
        "[confluence] closed %s id=%d reason=%s abs=%.2f%% spy=%.2f%% excess=%.2f%% hit=%s",
        pick.ticker, pick.id, payload.close_reason,
        abs_return, spy_return, excess, pick.hit_win_criterion,
    )

    return {
        "id": pick.id,
        "ticker": pick.ticker,
        "close_reason": payload.close_reason,
        "absolute_return_pct": pick.absolute_return_pct,
        "excess_vs_spy_pct": pick.excess_vs_spy_pct,
        "hit_win_criterion": pick.hit_win_criterion,
    }


@router.get("/journal")
def get_confluence_journal(
    include_closed: bool = Query(True),
    limit: int = Query(200, gt=0, le=1000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the running thesis journal + framework KPIs."""
    q = db.query(ConfluencePick).order_by(ConfluencePick.entry_date.desc(), ConfluencePick.id.desc())

    open_picks = q.filter(ConfluencePick.closed_date.is_(None)).limit(limit).all()
    closed_picks = []
    if include_closed:
        closed_picks = (
            q.filter(ConfluencePick.closed_date.isnot(None)).limit(limit).all()
        )

    # KPIs across closed picks
    n_closed = len(closed_picks)
    n_hits = sum(1 for p in closed_picks if p.hit_win_criterion)
    hit_rate = (n_hits / n_closed) if n_closed > 0 else None
    avg_excess = (
        sum((p.excess_vs_spy_pct or 0.0) for p in closed_picks) / n_closed
    ) if n_closed > 0 else None

    # Framework verdict per note thresholds
    verdict = "insufficient_sample"
    if n_closed >= 10:
        if hit_rate is not None and hit_rate < 0.55:
            verdict = "FAIL_disassemble"
        elif hit_rate is not None and hit_rate < 0.60:
            verdict = "MARGINAL_continue_reduced_size"
        elif hit_rate is not None and hit_rate >= 0.60 and (avg_excess or 0) >= 3.0:
            verdict = "WORKS_scale"
        else:
            verdict = "borderline"

    def _serialize(p: ConfluencePick) -> Dict[str, Any]:
        return {
            "id": p.id,
            "ticker": p.ticker,
            "entry_date": p.entry_date,
            "entry_price": p.entry_price_cents / 100.0,
            "spy_at_entry": p.spy_price_cents_at_entry / 100.0,
            "signals": {
                "insider_cluster": p.insider_cluster,
                "short_surprise_dir": p.short_surprise_dir,
                "analyst_revisions_dir": p.analyst_revisions_dir,
                "fundamental_momentum": p.fundamental_momentum,
                "inst_13f_net_add": p.inst_13f_net_add,
                "count": p.signals_fired_count,
            },
            "thesis": p.thesis_text,
            "target_price": p.target_price_cents / 100.0 if p.target_price_cents else None,
            "invalidation_price": p.invalidation_price_cents / 100.0 if p.invalidation_price_cents else None,
            "horizon_months": p.horizon_months,
            "closed_date": p.closed_date,
            "closed_price": p.closed_price_cents / 100.0 if p.closed_price_cents else None,
            "close_reason": p.close_reason,
            "absolute_return_pct": p.absolute_return_pct,
            "excess_vs_spy_pct": p.excess_vs_spy_pct,
            "hit": p.hit_win_criterion,
            "notes": p.notes,
        }

    return {
        "kpis": {
            "n_open": len(open_picks),
            "n_closed": n_closed,
            "n_hits": n_hits,
            "hit_rate": hit_rate,
            "avg_excess_vs_spy_pct": avg_excess,
            "verdict": verdict,
        },
        "open_picks": [_serialize(p) for p in open_picks],
        "closed_picks": [_serialize(p) for p in closed_picks],
    }


@router.get("/pick/{pick_id}")
def get_confluence_pick(
    pick_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    pick = db.query(ConfluencePick).filter(ConfluencePick.id == pick_id).first()
    if not pick:
        raise HTTPException(status_code=404, detail=f"pick {pick_id} not found")
    return {
        "id": pick.id,
        "ticker": pick.ticker,
        "entry_date": pick.entry_date,
        "entry_price_cents": pick.entry_price_cents,
        "spy_price_cents_at_entry": pick.spy_price_cents_at_entry,
        "signals_fired_count": pick.signals_fired_count,
        "thesis_text": pick.thesis_text,
        "target_price_cents": pick.target_price_cents,
        "invalidation_price_cents": pick.invalidation_price_cents,
        "horizon_months": pick.horizon_months,
        "closed_date": pick.closed_date,
        "closed_price_cents": pick.closed_price_cents,
        "close_reason": pick.close_reason,
        "absolute_return_pct": pick.absolute_return_pct,
        "excess_vs_spy_pct": pick.excess_vs_spy_pct,
        "hit_win_criterion": pick.hit_win_criterion,
    }
