from __future__ import annotations

from fastapi import APIRouter, Query

from app.services.earnings import get_earnings_calendar

router = APIRouter(prefix="/api/earnings", tags=["earnings"])


@router.get("")
async def earnings(days_ahead: int = Query(14, le=30)):
    """Return upcoming earnings events for the next ``days_ahead`` days."""
    return {"earnings": await get_earnings_calendar(days_ahead)}
