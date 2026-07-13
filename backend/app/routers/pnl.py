"""P&L endpoints — thin alias layer over dashboard's canonical rollups.

MIROFISH dashboard spec (2026-07-13) asks for /api/pnl/daily-distribution
so the ridgeline panel can be a single batch call. It's the same data as
/api/dashboard/sleeve-distributions — this alias exists so the spec URLs
map without the frontend having to know about the older prefix.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
from app.db.models.users import User

router = APIRouter(prefix="/api/pnl", tags=["pnl"])


@router.get("/daily-distribution")
def daily_distribution(
    sessions: int = Query(30, ge=1, le=365, description="Number of trading days"),
    group: str = Query("sleeve", pattern="^(sleeve)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Per-sleeve daily P&L series for ridgeline rendering."""
    from app.routers.dashboard import get_sleeve_distributions
    return get_sleeve_distributions(days=sessions, db=db, current_user=current_user)
