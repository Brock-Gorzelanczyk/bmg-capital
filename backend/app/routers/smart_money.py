from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
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
        "source": "Quiver Quantitative (quiverquant.com)",
        "source_note": "Data sourced from official STOCK Act disclosure portals via Quiver Quantitative API.",
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
    days_back: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    """Admin endpoint: run congress data refresh synchronously, return result."""
    import asyncio
    from app.services.smart_money.congress import fetch_and_upsert_congress

    try:
        result = await asyncio.wait_for(
            fetch_and_upsert_congress(db, days_back=days_back),
            timeout=120,
        )
        logger.info("[smart-money] congress refresh done: %s", result)
        ok = len(result.get("errors", [])) == 0
        return {
            "status": "ok" if ok else "partial",
            "days_back": days_back,
            "new": result.get("new", 0),
            "skipped": result.get("skipped", 0),
            "errors": result.get("errors", []),
        }
    except asyncio.TimeoutError:
        logger.error("[smart-money] congress refresh timed out after 120s")
        return {"status": "error", "days_back": days_back, "error": "Timed out after 120s — congress sources may be slow. Try again later."}
    except Exception as exc:
        logger.error("[smart-money] congress refresh failed: %s", exc, exc_info=True)
        return {"status": "error", "days_back": days_back, "error": str(exc)}


@router.get("/diagnose/congress", dependencies=[Depends(require_admin)])
async def diagnose_congress():
    """Diagnose Quiver Quantitative connectivity. Shows API key presence + HTTP status + row count."""
    import os
    import httpx
    from app.services.smart_money.congress import QUIVER_CONGRESS_URL

    api_key = os.environ.get("QUIVER_API_KEY", "")
    api_key_present = bool(api_key)

    result: dict = {
        "source": "quiver_quantitative",
        "url": QUIVER_CONGRESS_URL,
        "api_key_present": api_key_present,
    }

    if not api_key_present:
        result["error"] = "QUIVER_API_KEY env var is not set — add it to Railway and redeploy"
        return {"sources": {"quiver_quantitative": result}}

    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": "BMG Capital app/1.0 (admin@bmgcapital.app)",
        }
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            resp = await client.get(QUIVER_CONGRESS_URL, headers=headers)
        rows = 0
        parse_error = None
        try:
            data = resp.json()
            if isinstance(data, list):
                rows = len(data)
            elif isinstance(data, dict):
                for v in data.values():
                    if isinstance(v, list):
                        rows = len(v)
                        break
        except Exception as e:
            parse_error = str(e)
        result.update({
            "http_status": resp.status_code,
            "content_type": resp.headers.get("content-type", ""),
            "body_bytes": len(resp.content),
            "row_count": rows,
            "parse_error": parse_error,
            "sample": str(resp.text[:300]) if resp.status_code != 200 else None,
        })
    except Exception as exc:
        result["error"] = str(exc)

    return {"sources": {"quiver_quantitative": result}}


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
