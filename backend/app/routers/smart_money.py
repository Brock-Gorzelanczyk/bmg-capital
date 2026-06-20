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
        "source": "Financial Modeling Prep — /stable/ (senate-latest + house-latest)",
        "source_note": "Data sourced from official STOCK Act disclosure portals via FMP stable API.",
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


@router.get("/diagnose/crypto", dependencies=[Depends(require_admin)])
async def diagnose_crypto():
    """Probe CoinMetrics + Bybit connectivity to debug the Crypto tab."""
    import asyncio
    import httpx as _httpx
    from datetime import datetime, timedelta, timezone as _tz

    async def _probe_coinmetrics(asset: str) -> dict:
        url = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
        start = (datetime.now(_tz.utc) - timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            async with _httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                resp = await client.get(url, params={
                    "assets": asset, "metrics": "AdrBal1in1MCnt",
                    "frequency": "1d", "start_time": start,
                    "page_size": 14, "pretty": "false",
                }, headers={"Accept": "application/json", "User-Agent": "BMGCapital/1.0"})
            data_rows, sample, parse_error = 0, {}, None
            try:
                d = resp.json()
                rows = d.get("data", [])
                data_rows = len(rows)
                sample = rows[-1] if rows else {}
            except Exception as pe:
                parse_error = str(pe)
            return {
                "asset": asset, "http_status": resp.status_code,
                "data_rows": data_rows, "sample_row": sample,
                "parse_error": parse_error,
                "error_body": resp.text[:400] if resp.status_code != 200 else None,
            }
        except Exception as exc:
            return {"asset": asset, "error": str(exc)}

    async def _probe_bybit(symbol: str) -> dict:
        url = "https://api.bybit.com/v5/market/funding/history"
        try:
            async with _httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                resp = await client.get(url, params={
                    "category": "linear", "symbol": symbol, "limit": 1
                })
            payload, funding_rate = None, None
            try:
                payload = resp.json()
                items = payload.get("result", {}).get("list", [])
                if items:
                    funding_rate = items[0].get("fundingRate")
            except Exception:
                pass
            return {
                "symbol": symbol, "http_status": resp.status_code,
                "funding_rate_raw": funding_rate,
                "funding_rate_pct": float(funding_rate) * 100 if funding_rate else None,
                "sample_response": payload,
                "error_body": resp.text[:400] if resp.status_code != 200 else None,
            }
        except Exception as exc:
            return {"symbol": symbol, "error": str(exc)}

    results = await asyncio.gather(
        _probe_coinmetrics("btc"),
        _probe_coinmetrics("eth"),
        _probe_bybit("BTCUSDT"),
        _probe_bybit("ETHUSDT"),
        return_exceptions=True,
    )

    return {
        "coinmetrics_community": {"btc": results[0], "eth": results[1]},
        "bybit_funding": {"BTCUSDT": results[2], "ETHUSDT": results[3]},
    }


@router.get("/diagnose/congress", dependencies=[Depends(require_admin)])
async def diagnose_congress():
    """Diagnose FMP congress feed connectivity — key presence, HTTP status, row count, sample fields."""
    import os
    import asyncio
    import httpx
    from app.services.smart_money.congress import FMP_SENATE_URL, FMP_HOUSE_URL

    api_key = os.environ.get("FMP_API_KEY", "")
    api_key_present = bool(api_key)

    if not api_key_present:
        no_key = {"api_key_present": False, "error": "FMP_API_KEY not set — sign up free at financialmodelingprep.com/register"}
        return {"sources": {"fmp_senate": no_key, "fmp_house": no_key}}

    async def _probe(label: str, url: str) -> dict:
        result: dict = {"source": label, "url": url, "api_key_present": True}
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                resp = await client.get(url, params={"apikey": api_key}, headers={"Accept": "application/json"})
            rows = 0
            parse_error = None
            sample_keys: list = []
            sample_row: dict = {}
            try:
                data = resp.json()
                if isinstance(data, list):
                    rows = len(data)
                    if data and isinstance(data[0], dict):
                        sample_keys = list(data[0].keys())
                        sample_row = {k: data[0][k] for k in list(data[0].keys())[:6]}
            except Exception as e:
                parse_error = str(e)
            result.update({
                "http_status": resp.status_code,
                "row_count": rows,
                "sample_keys": sample_keys,
                "sample_row": sample_row,
                "parse_error": parse_error,
                "error_body": resp.text[:300] if resp.status_code != 200 else None,
            })
        except Exception as exc:
            result["error"] = str(exc)
        return result

    senate_result, house_result = await asyncio.gather(
        _probe("fmp_senate", FMP_SENATE_URL),
        _probe("fmp_house", FMP_HOUSE_URL),
    )
    return {"sources": {"fmp_senate": senate_result, "fmp_house": house_result}}


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
        whale_ok = whale.get("ok", False)
        assets.append({
            "symbol": display,
            "ticker": coin_id.upper(),
            "signal": whale.get("signal", "neutral"),
            "whale_ok": whale_ok,
            # null when unavailable so frontend can show "—" instead of falsely-zero "0"
            "large_holder_count": whale.get("large_holder_count") if whale_ok else None,
            "change_pct": whale.get("change_pct") if whale_ok else None,
            "funding_rate": None,
        })

    # Funding rates from Bybit linear perps (Binance is geo-blocked on Railway US IPs)
    # GET /v5/market/funding/history → result.list[0].fundingRate
    for bybit_sym, idx in [("BTCUSDT", 0), ("ETHUSDT", 1)]:
        try:
            resp = _req.get(
                "https://api.bybit.com/v5/market/funding/history",
                params={"category": "linear", "symbol": bybit_sym, "limit": 1},
                timeout=8,
            )
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("result", {}).get("list", [])
                if items:
                    raw = items[0].get("fundingRate")
                    if raw is not None:
                        assets[idx]["funding_rate"] = float(raw) * 100
            else:
                logger.warning("[smart-money/crypto] Bybit %s status %s: %s", bybit_sym, resp.status_code, resp.text[:200])
        except Exception as exc:
            logger.warning("[smart-money/crypto] Bybit %s failed: %s", bybit_sym, exc)

    # Additional coins — just basic CoinMetrics large holder if available
    # (skip for now, only BTC/ETH supported by whale.py)

    return {
        "assets": assets,
        "source": "CoinMetrics Community API + Bybit",
        "note": "Addresses with ≥$1M balance (AdrBal1in1MCnt). Funding rate from Bybit perps.",
    }
