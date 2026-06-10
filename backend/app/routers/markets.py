"""
Markets endpoints — crypto top list (CoinGecko) + stocks screener (yfinance).
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

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

# Top 200 S&P 500 + Nasdaq-100 symbols by market cap (static seed list)
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


def _fetch_stock_data(symbols: list[str]) -> list[dict]:
    """Batch fetch stock data using yfinance. Returns list of dicts."""
    import yfinance as yf
    import pandas as pd

    try:
        # Download 1M of daily data (for sparkline + pct calcs)
        raw = yf.download(
            tickers=symbols,
            period="1mo",
            interval="1d",
            group_by="ticker",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception as exc:
        logger.warning("yfinance download failed: %s", exc)
        return []

    rows = []
    for sym in symbols:
        try:
            if len(symbols) == 1:
                closes = raw["Close"]
            else:
                closes = raw["Close"][sym] if sym in raw["Close"].columns else None

            if closes is None or len(closes) == 0:
                continue

            closes = closes.dropna()
            if len(closes) < 2:
                continue

            sparkline = [round(float(v), 4) for v in closes.tolist()[-30:]]
            price = sparkline[-1] if sparkline else None
            if price is None:
                continue

            change_1d = round((sparkline[-1] / sparkline[-2] - 1) * 100, 2) if len(sparkline) >= 2 else None
            change_5d = round((sparkline[-1] / sparkline[-6] - 1) * 100, 2) if len(sparkline) >= 6 else None
            change_1m = round((sparkline[-1] / sparkline[0] - 1) * 100, 2) if len(sparkline) >= 20 else None

            rows.append({
                "symbol": sym,
                "price": price,
                "change_1d": change_1d,
                "change_5d": change_5d,
                "change_1m": change_1m,
                "sparkline_1m": sparkline,
                "market_cap": None,
                "volume": None,
                "name": sym,
            })
        except Exception:
            continue

    # Enrich with market cap + name via Tickers (batch info — best-effort)
    try:
        # Fetch fast_info for top 50 (rate-limit friendly)
        top_syms = [r["symbol"] for r in rows[:50]]
        tickers = yf.Tickers(" ".join(top_syms))
        for row in rows[:50]:
            try:
                info = tickers.tickers[row["symbol"]].fast_info
                row["market_cap"] = int(info.market_cap) if info.market_cap else None
                row["volume"] = int(info.three_month_average_volume or 0) or None
            except Exception:
                pass
    except Exception:
        pass

    rows.sort(key=lambda r: (r["market_cap"] or 0), reverse=True)
    return rows


@router.get("/stocks")
async def get_stock_markets(
    limit: int = Query(100, ge=10, le=200),
    sort: str = Query("market_cap"),
    _user=Depends(get_current_user),
):
    """Top stocks screener via yfinance. 5-min cache."""
    ckey = f"stocks:{limit}"
    cached = _get(ckey, 300)
    if cached is not None:
        return {"stocks": cached}

    symbols = _SP500_SEED[:limit]
    loop = asyncio.get_running_loop()
    stocks = await loop.run_in_executor(None, lambda: _fetch_stock_data(symbols))

    if sort == "change_1d":
        stocks.sort(key=lambda r: r.get("change_1d") or 0, reverse=True)
    elif sort == "change_1m":
        stocks.sort(key=lambda r: r.get("change_1m") or 0, reverse=True)

    _set(ckey, stocks)
    return {"stocks": stocks}
