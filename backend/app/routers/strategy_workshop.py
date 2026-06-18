from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, validator
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.db.models.workshop import WorkshopChart

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/strategy-workshop", tags=["strategy-workshop"])


# ── Pydantic models ────────────────────────────────────────────────────────────

class WorkshopChartCreate(BaseModel):
    ticker: str
    strategy_id: str
    name: str
    notes: Optional[str] = None


class WorkshopChartRating(BaseModel):
    overall: int
    chart_pattern: Optional[int] = None
    indicator_confluence: Optional[int] = None
    volume: Optional[int] = None
    risk_reward: Optional[int] = None
    conviction: Optional[str] = None  # low | medium | high
    notes: Optional[str] = None

    @validator("overall", "chart_pattern", "indicator_confluence", "volume", "risk_reward", pre=True, each_item=False)
    def _check_range(cls, v):
        if v is not None and not (1 <= v <= 5):
            raise ValueError("Rating must be between 1 and 5")
        return v

    @validator("conviction")
    def _check_conviction(cls, v):
        if v is not None and v not in ("low", "medium", "high"):
            raise ValueError("conviction must be low, medium, or high")
        return v


# ── Serializer ─────────────────────────────────────────────────────────────────

def _serialize(r: WorkshopChart) -> dict:
    return {
        "id": r.id,
        "ticker": r.ticker,
        "strategy_id": r.strategy_id,
        "name": r.name,
        "notes": r.notes,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        "rating_overall": r.rating_overall,
        "rating_chart_pattern": r.rating_chart_pattern,
        "rating_indicator_confluence": r.rating_indicator_confluence,
        "rating_volume": r.rating_volume,
        "rating_risk_reward": r.rating_risk_reward,
        "rating_conviction": r.rating_conviction,
        "rating_notes": r.rating_notes,
        "rating_updated_at": r.rating_updated_at.isoformat() if r.rating_updated_at else None,
    }


# ── CRUD endpoints ─────────────────────────────────────────────────────────────

@router.get("/charts")
def list_charts(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    rows = (
        db.query(WorkshopChart)
        .filter_by(user_id=user.id)
        .order_by(WorkshopChart.created_at.desc())
        .all()
    )
    return {"charts": [_serialize(r) for r in rows]}


@router.post("/charts", status_code=201)
def create_chart(
    body: WorkshopChartCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    row = WorkshopChart(
        user_id=user.id,
        ticker=body.ticker.upper(),
        strategy_id=body.strategy_id,
        name=body.name,
        notes=body.notes,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _serialize(row)


@router.get("/charts/{chart_id}")
def get_chart(
    chart_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    row = db.query(WorkshopChart).filter_by(id=chart_id, user_id=user.id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Chart not found")
    return _serialize(row)


@router.put("/charts/{chart_id}/rating")
def save_rating(
    chart_id: int,
    body: WorkshopChartRating,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    row = db.query(WorkshopChart).filter_by(id=chart_id, user_id=user.id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Chart not found")

    row.rating_overall = body.overall
    row.rating_chart_pattern = body.chart_pattern
    row.rating_indicator_confluence = body.indicator_confluence
    row.rating_volume = body.volume
    row.rating_risk_reward = body.risk_reward
    row.rating_conviction = body.conviction
    row.rating_notes = body.notes
    row.rating_updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(row)
    return _serialize(row)


@router.delete("/charts/{chart_id}")
def delete_chart(
    chart_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    row = db.query(WorkshopChart).filter_by(id=chart_id, user_id=user.id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Chart not found")
    db.delete(row)
    db.commit()
    return {"ok": True}


# ── Seed helper ────────────────────────────────────────────────────────────────

_SEED_EXAMPLES = [
    {
        "ticker": "NVDA",
        "strategy_id": "golden_cross",
        "name": "NVDA × Golden Cross — Pre-earnings setup",
        "notes": (
            "Pre-earnings momentum setup. Sharpe 2.63 over 2y. "
            "Wait for confirmed cross before entering. "
            "50dma at $142, 200dma at $138. Active cross."
        ),
    },
    {
        "ticker": "SPY",
        "strategy_id": "options_iron_condor_spy",
        "name": "SPY × Iron Condor 45DTE",
        "notes": (
            "Sell when IVR > 40 and SPY 1m range < 5%. "
            "Short put strike $720, short call strike $760."
        ),
    },
    {
        "ticker": "BTC/USD",
        "strategy_id": "crypto_quant_mean_reversion",
        "name": "BTC × Mean Reversion z-score",
        "notes": (
            "21-day z-score mean reversion. "
            "Enter when z-score < -2.0, exit when reverts to 0."
        ),
    },
]


def startup_seed_workshop_examples(db: Session) -> None:
    """Insert 3 example workshop charts for user_id=1 if they don't already exist."""
    try:
        existing = (
            db.query(WorkshopChart.strategy_id)
            .filter_by(user_id=1)
            .all()
        )
        existing_ids = {row.strategy_id for row in existing}

        seeded = 0
        for example in _SEED_EXAMPLES:
            if example["strategy_id"] not in existing_ids:
                row = WorkshopChart(
                    user_id=1,
                    ticker=example["ticker"],
                    strategy_id=example["strategy_id"],
                    name=example["name"],
                    notes=example["notes"],
                )
                db.add(row)
                seeded += 1

        if seeded:
            db.commit()
            logger.info("[startup] workshop_charts: seeded %d example(s) for user_id=1", seeded)
        else:
            logger.info("[startup] workshop_charts: seed examples already present — skipping")
    except Exception as exc:
        logger.warning("[startup] workshop_charts seed failed (non-fatal): %s", exc)
        db.rollback()
