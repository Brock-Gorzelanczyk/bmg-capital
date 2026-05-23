from __future__ import annotations

from fastapi import APIRouter

from app.services.market_overview import get_market_overview
from app.services.sector import get_sector_performance

router = APIRouter(prefix="/api/market", tags=["market"])


@router.get("/overview")
async def market_overview():
    """Return price and daily change for the major index ETFs."""
    return {"indices": await get_market_overview()}


@router.get("/sectors")
async def sector_performance():
    """Return daily performance for each SPDR sector ETF."""
    return {"sectors": await get_sector_performance()}
