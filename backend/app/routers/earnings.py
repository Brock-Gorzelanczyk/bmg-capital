from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks, Query

from app.services.earnings import get_earnings_calendar

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/earnings", tags=["earnings"])


@router.get("")
async def earnings(days_ahead: int = Query(14, le=30), background_tasks: BackgroundTasks = None):
    """Return upcoming earnings events for the next ``days_ahead`` days."""
    data = await get_earnings_calendar(days_ahead)
    return {"earnings": data}
