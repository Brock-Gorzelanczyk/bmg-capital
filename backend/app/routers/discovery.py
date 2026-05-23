from __future__ import annotations

from fastapi import APIRouter, Query

from app.services.discovery import get_themes_with_performance, get_ipo_calendar, get_insider_trades

router = APIRouter(prefix="/api/discovery", tags=["discovery"])


@router.get("/themes")
async def themes():
    return {"themes": await get_themes_with_performance()}


@router.get("/ipos")
async def ipos(days_ahead: int = Query(90, le=180)):
    return {"ipos": await get_ipo_calendar(days_ahead)}


@router.get("/insiders")
async def insiders(limit: int = Query(50, le=100)):
    return {"insiders": await get_insider_trades(limit)}
