from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db, require_admin

router = APIRouter(prefix="/api/smart-money", tags=["smart-money"])
logger = logging.getLogger(__name__)

_last_congress_refresh: Optional[datetime] = None


@router.get("/congress")
async def get_congress_trades(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ticker: Optional[str] = Query(None),
    party: Optional[str] = Query(None),
    chamber: Optional[str] = Query(None),
    days: int = Query(30, ge=1, le=365),
    min_amount: Optional[int] = Query(None, description="Minimum amount in dollars"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Congressional stock disclosures from Senate & House Stock Watcher."""
    from app.db.models.smart_money import SmartMoneyCongressTrade
    from app.services.smart_money.congress import get_recent_congress

    min_cents = min_amount * 100 if min_amount else None
    trades, total = get_recent_congress(
        db, limit=limit, offset=offset, ticker=ticker,
        party=party, chamber=chamber, days=days, min_amount_cents=min_cents,
    )

    # Get last fetch time
    latest = db.query(SmartMoneyCongressTrade.fetched_at)\
        .order_by(SmartMoneyCongressTrade.fetched_at.desc()).first()
    last_updated = latest[0].isoformat() if latest else None

    return {
        "trades": trades,
        "total": total,
        "last_updated_at": last_updated,
        "source": "Senate Stock Watcher (senatestockwatcher.com) + House Stock Watcher (housestockwatcher.com)",
        "source_note": "Data sourced from official STOCK Act disclosure portals via open-source aggregators.",
    }


@router.get("/summary")
async def get_summary(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Quick stats for the page header."""
    from app.db.models.smart_money import SmartMoneyCongressTrade

    cutoff = date.today() - timedelta(days=30)
    q = db.query(SmartMoneyCongressTrade).filter(
        SmartMoneyCongressTrade.transaction_date >= cutoff
    )
    buys = q.filter(SmartMoneyCongressTrade.transaction_type == "purchase").count()
    sells = q.filter(SmartMoneyCongressTrade.transaction_type == "sale").count()

    # Most traded ticker
    top_ticker_row = (
        db.query(SmartMoneyCongressTrade.ticker, func.count().label("cnt"))
        .filter(SmartMoneyCongressTrade.transaction_date >= cutoff)
        .filter(SmartMoneyCongressTrade.ticker.isnot(None))
        .group_by(SmartMoneyCongressTrade.ticker)
        .order_by(func.count().desc())
        .first()
    )

    latest_row = db.query(SmartMoneyCongressTrade.fetched_at)\
        .order_by(SmartMoneyCongressTrade.fetched_at.desc()).first()

    return {
        "congress_buys_30d": buys,
        "congress_sells_30d": sells,
        "insider_buys_30d": 0,   # Phase 2
        "insider_sells_30d": 0,  # Phase 2
        "most_traded_ticker_30d": top_ticker_row[0] if top_ticker_row else None,
        "most_traded_ticker_count": top_ticker_row[1] if top_ticker_row else 0,
        "last_updated": {
            "congress": latest_row[0].isoformat() if latest_row else None,
            "insider": None,  # Phase 2
            "hedge_funds": None,  # Phase 3
        },
    }


@router.post("/refresh/congress", dependencies=[Depends(require_admin)])
async def trigger_congress_refresh(
    background_tasks: BackgroundTasks,
    days_back: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    """Admin endpoint: trigger a congress data refresh in the background."""
    from app.services.smart_money.congress import fetch_and_upsert_congress

    async def _refresh():
        result = await fetch_and_upsert_congress(db, days_back=days_back)
        logger.info("[smart-money] congress refresh done: %s", result)

    background_tasks.add_task(_refresh)
    return {"status": "refresh queued", "days_back": days_back}
