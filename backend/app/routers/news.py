from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

from app.services.news import get_news

router = APIRouter(prefix="/api/news", tags=["news"])


@router.get("")
async def news(
    symbols: Optional[str] = Query(None, description="Comma-separated tickers"),
    limit: int = Query(20, le=50),
):
    """Return recent news articles, optionally filtered by symbol(s)."""
    symbol_list = (
        [s.strip().upper() for s in symbols.split(",") if s.strip()] if symbols else None
    )
    return {"articles": await get_news(symbol_list, limit)}
