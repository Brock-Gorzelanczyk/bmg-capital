from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.services.research import get_fundamentals

router = APIRouter(prefix="/api/research", tags=["research"])


@router.get("/{symbol}")
async def company_research(symbol: str):
    """Return company fundamentals for a given ticker symbol."""
    symbol = symbol.upper().strip().lstrip("$")
    if not symbol or len(symbol) > 10:
        raise HTTPException(status_code=400, detail="Invalid symbol")
    data = await get_fundamentals(symbol)
    if "error" in data and len(data) == 2:
        raise HTTPException(status_code=404, detail=f"Could not fetch data for {symbol}")
    return data
