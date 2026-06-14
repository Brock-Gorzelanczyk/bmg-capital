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
def get_congress_trades(
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
def get_summary(
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
):
    """Admin endpoint: trigger a congress data refresh in the background."""
    from app.services.smart_money.congress import fetch_and_upsert_congress
    from app.db.session import SessionLocal

    async def _refresh():
        _db = SessionLocal()
        try:
            result = await fetch_and_upsert_congress(_db, days_back=days_back)
            logger.info("[smart-money] congress refresh done: %s", result)
        except Exception as _e:
            logger.error("[smart-money] congress refresh error: %s", _e, exc_info=True)
        finally:
            _db.close()

    background_tasks.add_task(_refresh)
    return {"status": "refresh queued", "days_back": days_back}


@router.get("/crypto")
async def get_crypto_smart_money(
    _user=Depends(get_current_user),
):
    """Crypto smart money signals: whale accumulation + funding rates."""
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _build_crypto_smart_money)


def _build_crypto_smart_money() -> dict:
    from app.services.whale import get_large_holder_signal
    import os, requests as _req

    assets = []

    # BTC and ETH whale signals from CoinMetrics
    for symbol, display, coin_id in [
        ("BTC/USDT", "Bitcoin", "btc"),
        ("ETH/USDT", "Ethereum", "eth"),
    ]:
        whale = get_large_holder_signal(symbol)
        assets.append({
            "symbol": display,
            "ticker": coin_id.upper(),
            "signal": whale.get("signal", "neutral"),
            "large_holder_count": whale.get("large_holder_count", 0),
            "change_pct": whale.get("change_pct", 0.0),
            "funding_rate": None,
        })

    # Funding rates from Binance (free public API)
    for i, (futures_sym, idx) in enumerate([("BTCUSDT", 0), ("ETHUSDT", 1)]):
        try:
            resp = _req.get(
                "https://fapi.binance.com/fapi/v1/fundingRate",
                params={"symbol": futures_sym, "limit": 1},
                timeout=6,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data:
                    assets[idx]["funding_rate"] = float(data[0].get("fundingRate", 0)) * 100
        except Exception:
            pass

    # Additional coins — just basic CoinMetrics large holder if available
    # (skip for now, only BTC/ETH supported by whale.py)

    return {
        "assets": assets,
        "source": "CoinMetrics Community API + Binance",
        "note": "Addresses with ≥$1M balance (AdrBal1in1MCnt). Funding rate from Binance perps.",
    }
