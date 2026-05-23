from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config import settings
from app.dependencies import get_db, get_current_user
from app.db.models.users import User
from app.services.options_chain import get_chain, get_expirations
from app.alpaca.client import get_historical_client

router = APIRouter(prefix="/api/options", tags=["options"])


async def _get_underlying_price(symbol: str) -> float:
    try:
        from alpaca.data.requests import StockLatestQuoteRequest
        data_client = get_historical_client()
        quote = data_client.get_stock_latest_quote(StockLatestQuoteRequest(symbol_or_symbols=symbol))
        q = quote[symbol]
        return float((q.ask_price + q.bid_price) / 2)
    except Exception:
        return 150.0  # sensible fallback for demo


@router.get("/expirations")
async def list_expirations(_: User = Depends(get_current_user)):
    return get_expirations()


@router.get("/chain/{symbol}")
async def option_chain(
    symbol: str,
    expiration: Optional[str] = Query(None, description="YYYY-MM-DD"),
    _: User = Depends(get_current_user),
):
    symbol = symbol.upper()
    exp = date.fromisoformat(expiration) if expiration else None

    underlying_price = await _get_underlying_price(symbol)

    chain = await get_chain(
        symbol=symbol,
        underlying_price=underlying_price,
        expiration=exp,
        api_key=settings.alpaca_api_key,
        secret_key=settings.alpaca_secret_key,
    )
    return chain
