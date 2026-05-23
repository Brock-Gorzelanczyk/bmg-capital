from __future__ import annotations

import logging
from typing import Any, Dict, List

from alpaca.data.enums import DataFeed
from alpaca.data.requests import StockSnapshotRequest
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.alpaca.client import get_historical_client
from app.db.models.users import User
from app.db.models.watchlist import Watchlist, WatchlistItem
from app.dependencies import get_db, get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/watchlists", tags=["watchlists"])


class WatchlistCreate(BaseModel):
    name: str


class SymbolAdd(BaseModel):
    symbol: str


def _watchlist_to_dict(wl: Watchlist, include_items: bool = False) -> Dict[str, Any]:
    d: Dict[str, Any] = {
        "id": wl.id,
        "name": wl.name,
        "created_at": wl.created_at.isoformat() if wl.created_at else None,
    }
    if include_items:
        d["items"] = [
            {
                "id": item.id,
                "symbol": item.symbol,
                "added_at": item.added_at.isoformat() if item.added_at else None,
            }
            for item in wl.items
        ]
    return d


@router.get("")
def list_watchlists(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    watchlists = db.query(Watchlist).filter(Watchlist.user_id == current_user.id).all()
    return {"watchlists": [_watchlist_to_dict(wl, include_items=True) for wl in watchlists]}


@router.post("", status_code=201)
def create_watchlist(
    body: WatchlistCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    wl = Watchlist(name=body.name, user_id=current_user.id)
    db.add(wl)
    db.commit()
    db.refresh(wl)
    return _watchlist_to_dict(wl, include_items=True)


@router.get("/{watchlist_id}")
def get_watchlist(
    watchlist_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    wl = db.query(Watchlist).filter(
        Watchlist.id == watchlist_id, Watchlist.user_id == current_user.id
    ).first()
    if not wl:
        raise HTTPException(status_code=404, detail="Watchlist not found")
    return _watchlist_to_dict(wl, include_items=True)


@router.delete("/{watchlist_id}")
def delete_watchlist(
    watchlist_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    wl = db.query(Watchlist).filter(
        Watchlist.id == watchlist_id, Watchlist.user_id == current_user.id
    ).first()
    if not wl:
        raise HTTPException(status_code=404, detail="Watchlist not found")
    db.delete(wl)
    db.commit()
    return {"ok": True}


@router.post("/{watchlist_id}/symbols", status_code=201)
def add_symbol(
    watchlist_id: int,
    body: SymbolAdd,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    wl = db.query(Watchlist).filter(
        Watchlist.id == watchlist_id, Watchlist.user_id == current_user.id
    ).first()
    if not wl:
        raise HTTPException(status_code=404, detail="Watchlist not found")

    symbol = body.symbol.upper().strip()
    if db.query(WatchlistItem).filter(
        WatchlistItem.watchlist_id == watchlist_id, WatchlistItem.symbol == symbol
    ).first():
        raise HTTPException(status_code=409, detail=f"{symbol} is already in this watchlist")

    item = WatchlistItem(watchlist_id=watchlist_id, symbol=symbol)
    db.add(item)
    db.commit()
    db.refresh(item)
    return {
        "id": item.id,
        "watchlist_id": item.watchlist_id,
        "symbol": item.symbol,
        "added_at": item.added_at.isoformat() if item.added_at else None,
    }


@router.delete("/{watchlist_id}/symbols/{symbol}")
def remove_symbol(
    watchlist_id: int,
    symbol: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    symbol = symbol.upper()
    wl = db.query(Watchlist).filter(
        Watchlist.id == watchlist_id, Watchlist.user_id == current_user.id
    ).first()
    if not wl:
        raise HTTPException(status_code=404, detail="Watchlist not found")
    item = db.query(WatchlistItem).filter(
        WatchlistItem.watchlist_id == watchlist_id, WatchlistItem.symbol == symbol
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail=f"{symbol} not found in watchlist")
    db.delete(item)
    db.commit()
    return {"ok": True}


@router.get("/{watchlist_id}/snapshot")
async def get_watchlist_snapshot(
    watchlist_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    wl = db.query(Watchlist).filter(
        Watchlist.id == watchlist_id, Watchlist.user_id == current_user.id
    ).first()
    if not wl:
        raise HTTPException(status_code=404, detail="Watchlist not found")

    symbols = [item.symbol for item in wl.items]
    if not symbols:
        return {"watchlist_id": watchlist_id, "snapshots": []}

    try:
        client = get_historical_client()
        req = StockSnapshotRequest(symbol_or_symbols=symbols, feed=DataFeed.IEX)
        snapshots_raw = client.get_stock_snapshot(req)
        result: List[Dict[str, Any]] = []
        for symbol in symbols:
            if symbol in snapshots_raw:
                snap = snapshots_raw[symbol]
                daily = snap.daily_bar
                prev = snap.previous_daily_bar
                price = float(daily.close) if daily else 0.0
                prev_close = float(prev.close) if prev else price
                change = price - prev_close
                change_pct = (change / prev_close * 100) if prev_close else 0.0
                result.append({
                    "symbol": symbol, "price": price,
                    "change": change, "change_pct": change_pct,
                    "volume": float(daily.volume) if daily else 0.0,
                    "prev_close": prev_close,
                })
            else:
                result.append({"symbol": symbol, "price": None, "error": "no data"})
        return {"watchlist_id": watchlist_id, "snapshots": result}
    except Exception as e:
        logger.error(f"Snapshot error for watchlist {watchlist_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
