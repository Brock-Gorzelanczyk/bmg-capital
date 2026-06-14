"""
Markets endpoints — crypto top list (CoinGecko) + stocks screener (Alpaca).
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests as _requests

from fastapi import APIRouter, Depends, Query

from app.dependencies import get_current_user
from app.services import coingecko as cg

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/markets", tags=["markets"])

# ── Simple in-memory cache ────────────────────────────────────────────────────

_cache: dict[str, tuple[float, object]] = {}

def _get(key: str, ttl: float) -> object | None:
    entry = _cache.get(key)
    if entry and time.time() - entry[0] < ttl:
        return entry[1]
    return None

def _set(key: str, val: object) -> object:
    _cache[key] = (time.time(), val)
    return val

# ── Crypto ────────────────────────────────────────────────────────────────────

@router.get("/crypto")
async def get_crypto_markets(
    limit: int = Query(100, ge=1, le=250),
    sort: str = Query("market_cap"),
    _user=Depends(get_current_user),
):
    """Top crypto by market cap from CoinGecko. 60s cache."""
    ckey = f"crypto:{limit}"
    cached = _get(ckey, 60)
    if cached is not None:
        return {"coins": cached}

    loop = asyncio.get_running_loop()
    coins = await loop.run_in_executor(None, lambda: cg.get_top_coins(limit))

    if sort == "volume":
        coins.sort(key=lambda c: c.get("total_volume") or 0, reverse=True)
    elif sort == "change_24h":
        coins.sort(key=lambda c: c.get("pct_24h") or 0, reverse=True)

    _set(ckey, coins)
    return {"coins": coins}


# ── Stocks ────────────────────────────────────────────────────────────────────

# S&P 500 + Nasdaq-100 leaders by market cap order
_SP500_SEED = [
    "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","BRK-B","AVGO","JPM",
    "LLY","V","UNH","XOM","MA","COST","HD","NFLX","PG","JNJ","ABBV","WMT",
    "BAC","CRM","KO","CVX","MRK","AMD","ORCL","PEP","ADBE","TMO","CSCO","ACN",
    "LIN","WFC","MCD","TXN","ABT","PM","DIS","INTU","DHR","NEE","CMCSA","GE",
    "VZ","IBM","AMGN","CAT","NOW","RTX","SPGI","QCOM","AXP","T","GS","HON",
    "ISRG","PFE","BKNG","GILD","BLK","AMAT","MU","SYK","MDT","ELV","ADI","DE",
    "PANW","C","BSX","VRTX","SBUX","PLD","REGN","CB","CI","SCHW","SO","MMC",
    "TJX","CME","LRCX","ETN","ITW","ZTS","ADP","HCA","CVS","WM","MO","EMR",
    "EOG","MCO","USB","CTAS","NOC","PGR","AON","ICE","NSC","MPC","FCX","SLB",
    "FDX","GM","F","UBER","DUK","APD","TGT","COF","BDX","ECL","AIG","HLT",
    "ABNB","CARR","PCAR","KHC","BK","MRNA","DXCM","GD","KMB","JCI","HPQ",
    "NXPI","PSA","PRU","MNST","STZ","FTNT","A","MAR","MCHP","ODFL","FAST",
    "ALL","ROST","FANG","NUE","CSGP","OTIS","NEM","TEL","HIG","WBA","AEP",
    "EW","MSCI","MET","VLO","XYL","RSG","AMP","CTVA","IDXX","CDNS","GWW",
    "WELL","IQV","PCG","AWK","KEYS","TROW","CDW","VRSK","WAT","WSM","TDG",
    "ROP","CL","SHW","FIS","PAYX","CPRT","ACGL","MPWR","KLAC","NDAQ","EXC",
    "CINF","KDP","MTD","ZBH","BALL","HUM","WEC","BAX","EBAY","FSLR","DDOG",
    "CRWD","SNOW","TTD","HUBS","HOOD","SHOP","SQ","PYPL","SOFI","PLTR",
]

# Partial name map for top symbols
_STOCK_NAMES: dict[str, str] = {
    "AAPL":"Apple","MSFT":"Microsoft","NVDA":"NVIDIA","AMZN":"Amazon",
    "GOOGL":"Alphabet","META":"Meta","TSLA":"Tesla","BRK-B":"Berkshire","AVGO":"Broadcom",
    "JPM":"JPMorgan","LLY":"Eli Lilly","V":"Visa","UNH":"UnitedHealth","XOM":"ExxonMobil",
    "MA":"Mastercard","COST":"Costco","HD":"Home Depot","NFLX":"Netflix","PG":"P&G",
    "JNJ":"J&J","ABBV":"AbbVie","WMT":"Walmart","BAC":"BofA","CRM":"Salesforce",
    "KO":"Coca-Cola","CVX":"Chevron","MRK":"Merck","AMD":"AMD","ORCL":"Oracle",
    "PEP":"PepsiCo","ADBE":"Adobe","TMO":"Thermo Fisher","CSCO":"Cisco","ACN":"Accenture",
    "LIN":"Linde","WFC":"Wells Fargo","MCD":"McDonald's","TXN":"Texas Instruments",
    "ABT":"Abbott","PM":"Philip Morris","DIS":"Disney","INTU":"Intuit","DHR":"Danaher",
    "NEE":"NextEra","CMCSA":"Comcast","GE":"GE Aerospace","VZ":"Verizon","IBM":"IBM",
    "AMGN":"Amgen","CAT":"Caterpillar","NOW":"ServiceNow","RTX":"RTX Corp","SPGI":"S&P Global",
    "QCOM":"Qualcomm","AXP":"Amex","T":"AT&T","GS":"Goldman Sachs","HON":"Honeywell",
    "ISRG":"Intuitive Surgical","PFE":"Pfizer","BKNG":"Booking","GILD":"Gilead",
    "BLK":"BlackRock","AMAT":"Applied Materials","MU":"Micron","SYK":"Stryker",
    "PANW":"Palo Alto","C":"Citigroup","VRTX":"Vertex","SBUX":"Starbucks","REGN":"Regeneron",
    "SCHW":"Schwab","GS":"Goldman","UBER":"Uber","TGT":"Target","COF":"Capital One",
    "ABNB":"Airbnb","MRNA":"Moderna","CRWD":"CrowdStrike","SNOW":"Snowflake",
    "PLTR":"Palantir","SQ":"Block","PYPL":"PayPal","SHOP":"Shopify","HOOD":"Robinhood",
    "SOFI":"SoFi","DDOG":"Datadog","TTD":"Trade Desk","HUBS":"HubSpot","FSLR":"First Solar",
}


def _fetch_stock_data_alpaca(symbols: list[str]) -> list[dict]:
    """Fetch stock data via Alpaca Data API (IEX feed). Replaces broken yfinance."""
    api_key = os.getenv("ALPACA_API_KEY", "") or os.getenv("ALPACA_PAPER_KEY", "")
    api_secret = os.getenv("ALPACA_SECRET_KEY", "") or os.getenv("ALPACA_PAPER_SECRET", "")
    base = "https://data.alpaca.markets"

    if not api_key:
        logger.warning("[markets/stocks] ALPACA_API_KEY not set — stocks unavailable")
        return []

    headers = {"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": api_secret}
    result_map: dict[str, dict] = {}

    # ── Step 1: Snapshots (latest price, daily bar, prev close) ──────────────
    for i in range(0, len(symbols), 100):
        chunk = [s for s in symbols[i:i+100] if s != "BRK-B"]  # IEX uses BRK/B
        chunk_fixed = [s.replace("BRK-B", "BRK/B") for s in symbols[i:i+100]]
        try:
            resp = _requests.get(
                f"{base}/v2/stocks/snapshots",
                params={"symbols": ",".join(chunk_fixed), "feed": "iex"},
                headers=headers,
                timeout=20,
            )
            if resp.status_code == 200:
                snaps = resp.json()
                if "snapshots" in snaps:
                    snaps = snaps["snapshots"]
                for raw_sym, snap in snaps.items():
                    sym = raw_sym.replace("/", "-")
                    daily = snap.get("dailyBar") or {}
                    prev  = snap.get("prevDailyBar") or {}
                    trade = snap.get("latestTrade") or {}

                    price     = trade.get("p") or daily.get("c")
                    prev_close = prev.get("c")
                    change_1d = (
                        round((price / prev_close - 1) * 100, 2)
                        if price and prev_close and prev_close > 0 else None
                    )
                    result_map[sym] = {
                        "symbol": sym,
                        "name": _STOCK_NAMES.get(sym, sym),
                        "price": round(float(price), 2) if price else None,
                        "change_1d": change_1d,
                        "change_5d": None,
                        "change_1m": None,
                        "market_cap": None,
                        "volume": int(daily.get("v") or 0) or None,
                        "sparkline_1m": [],
                    }
            else:
                logger.warning("[markets/stocks] snapshots returned %d", resp.status_code)
        except Exception as exc:
            logger.warning("[markets/stocks] snapshot error: %s", exc)

    # ── Step 2: 1-month bars for sparklines + 5D / 1M returns ────────────────
    end   = datetime.now(timezone.utc)
    start = end - timedelta(days=37)
    # Process in chunks of 100 (API max per request)
    for i in range(0, len(symbols), 100):
        chunk_fixed = [s.replace("BRK-B", "BRK/B") for s in symbols[i:i+100]]
        try:
            resp = _requests.get(
                f"{base}/v2/stocks/bars",
                params={
                    "symbols": ",".join(chunk_fixed),
                    "timeframe": "1Day",
                    "start": start.strftime("%Y-%m-%dT00:00:00Z"),
                    "end": end.strftime("%Y-%m-%dT00:00:00Z"),
                    "feed": "iex",
                    "limit": 10000,
                },
                headers=headers,
                timeout=25,
            )
            if resp.status_code == 200:
                bars_by_sym = resp.json().get("bars", {})
                for raw_sym, bars in bars_by_sym.items():
                    sym = raw_sym.replace("/", "-")
                    closes = [b["c"] for b in bars if "c" in b]
                    if not closes or sym not in result_map:
                        continue
                    result_map[sym]["sparkline_1m"] = [round(c, 4) for c in closes[-30:]]
                    if len(closes) >= 5:
                        result_map[sym]["change_5d"] = round(
                            (closes[-1] / closes[-5] - 1) * 100, 2)
                    if len(closes) >= 20:
                        result_map[sym]["change_1m"] = round(
                            (closes[-1] / closes[0] - 1) * 100, 2)
        except Exception as exc:
            logger.warning("[markets/stocks] bars error: %s", exc)

    # Return in seed order (pre-sorted by approx market cap)
    rows = [result_map[s] for s in symbols if s in result_map and result_map[s]["price"]]
    logger.info("[markets/stocks] returning %d stocks", len(rows))
    return rows


@router.get("/stocks")
async def get_stock_markets(
    limit: int = Query(100, ge=10, le=200),
    sort: str = Query("market_cap"),
    _user=Depends(get_current_user),
):
    """Top stocks via Alpaca Data API (IEX feed). 5-min cache."""
    ckey = f"stocks:{limit}"
    cached = _get(ckey, 300)
    if cached is not None:
        return {"stocks": cached}

    symbols = _SP500_SEED[:limit]
    loop = asyncio.get_running_loop()
    stocks = await loop.run_in_executor(None, lambda: _fetch_stock_data_alpaca(symbols))

    if sort == "change_1d":
        stocks.sort(key=lambda r: r.get("change_1d") or -999, reverse=True)
    elif sort == "change_1m":
        stocks.sort(key=lambda r: r.get("change_1m") or -999, reverse=True)

    _set(ckey, stocks)
    return {"stocks": stocks}
