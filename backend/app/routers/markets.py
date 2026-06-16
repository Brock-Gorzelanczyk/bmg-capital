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
from app.routers.stocks_universe import TOP_STOCKS_UNIVERSE, STOCK_NAMES, STOCK_MCAP

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

# Names and mcap imported from stocks_universe; alias for local use
_STOCK_NAMES = STOCK_NAMES
_STOCK_MCAP  = STOCK_MCAP


def _fetch_stock_data_yfinance(symbols: list[str]) -> list[dict]:
    """
    Fetch stock data via yfinance batch download (~50 symbols, one HTTP call).
    Uses 35-day daily bars: latest close = current price, history for 1D/5D/1M changes.
    """
    try:
        import yfinance as yf
        import pandas as pd
    except ImportError:
        logger.warning("[markets/stocks] yfinance not installed")
        return []

    try:
        raw = yf.download(
            symbols,
            period="35d",
            interval="1d",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception as exc:
        logger.warning("[markets/stocks] yfinance download failed: %s", exc)
        return []

    if raw is None or (hasattr(raw, "empty") and raw.empty):
        logger.warning("[markets/stocks] yfinance returned empty DataFrame for %d symbols", len(symbols))
        return []

    # Multi-ticker download returns MultiIndex columns; single-ticker returns flat
    try:
        closes = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]].rename(columns={"Close": symbols[0]})
        volumes = raw["Volume"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Volume"]].rename(columns={"Volume": symbols[0]})
    except KeyError as exc:
        logger.warning("[markets/stocks] yfinance missing expected columns: %s", exc)
        return []

    rows = []
    for sym in symbols:
        try:
            if sym not in closes.columns:
                continue
            col = closes[sym].dropna()
            if col.empty or len(col) < 2:
                continue

            price     = round(float(col.iloc[-1]), 2)
            change_1d = round((col.iloc[-1] / col.iloc[-2] - 1) * 100, 2) if len(col) >= 2 else None
            change_5d = round((col.iloc[-1] / col.iloc[-5] - 1) * 100, 2) if len(col) >= 5 else None
            change_1m = round((col.iloc[-1] / col.iloc[0]  - 1) * 100, 2) if len(col) >= 20 else None
            sparkline = [round(float(v), 4) for v in col.iloc[-30:].tolist()]

            volume = None
            try:
                vcol = volumes[sym].dropna()
                if not vcol.empty:
                    volume = int(vcol.iloc[-1])
            except Exception:
                pass

            rows.append({
                "symbol":      sym,
                "name":        _STOCK_NAMES.get(sym, sym),
                "price":       price,
                "change_1d":   change_1d,
                "change_5d":   change_5d,
                "change_1m":   change_1m,
                "market_cap":  _STOCK_MCAP.get(sym),
                "volume":      volume,
                "sparkline_1m": sparkline,
            })
        except Exception as exc:
            logger.debug("[markets/stocks] skip %s: %s", sym, exc)

    logger.info("[markets/stocks] yfinance returned %d/%d stocks", len(rows), len(symbols))
    return rows


@router.get("/stocks/validate")
async def validate_stock_universe(_user=Depends(get_current_user)):
    """
    Validate each symbol in TOP_STOCKS_UNIVERSE via yfinance.
    Admin health-check — not cached. Returns per-symbol status.
    """
    try:
        import yfinance as yf
    except ImportError:
        return {"error": "yfinance not installed", "results": {}}

    results: dict[str, str] = {}
    for sym in TOP_STOCKS_UNIVERSE:
        try:
            df = yf.download(sym, period="5d", interval="1d", auto_adjust=True, progress=False, threads=False)
            if df is None or (hasattr(df, "empty") and df.empty):
                logger.warning("[markets/validate] %s returned empty DataFrame", sym)
                results[sym] = "empty"
            else:
                results[sym] = "valid"
        except Exception as exc:
            logger.error("[markets/validate] %s fetch failed: %s", sym, exc)
            results[sym] = f"error: {exc}"

    invalid = [s for s, v in results.items() if v != "valid"]
    if invalid:
        logger.warning("[markets/validate] %d symbols failed: %s", len(invalid), invalid)
    else:
        logger.info("[markets/validate] all %d symbols valid", len(TOP_STOCKS_UNIVERSE))

    return {
        "total": len(TOP_STOCKS_UNIVERSE),
        "valid": len([v for v in results.values() if v == "valid"]),
        "invalid": invalid,
        "results": results,
    }


@router.get("/stocks")
async def get_stock_markets(
    sort: str = Query("market_cap"),
    _user=Depends(get_current_user),
):
    """Top stocks via yfinance batch download. 60s cache."""
    ckey = "stocks:universe"
    cached = _get(ckey, 60)
    if cached is not None:
        return {"stocks": cached}

    # Fetch public stocks; exclude private tickers that yfinance can't resolve
    public_universe = [s for s in TOP_STOCKS_UNIVERSE if s != "SPACEX"]
    loop = asyncio.get_running_loop()
    stocks = await loop.run_in_executor(None, lambda: _fetch_stock_data_yfinance(public_universe))

    # Inject SpaceX as a static private-market row (no public exchange listing)
    stocks.append({
        "symbol":       "SPACEX",
        "name":         "SpaceX",
        "price":        None,
        "change_1d":    None,
        "change_5d":    None,
        "change_1m":    None,
        "market_cap":   350_000_000_000,
        "volume":       None,
        "sparkline_1m": [],
        "private":      True,
    })

    _sort_map = {
        "pct_today": "change_1d",
        "pct_5d":    "change_5d",
        "pct_1m":    "change_1m",
        "volume":    "volume",
        "mcap":      "market_cap",
    }
    sort_field = _sort_map.get(sort, sort)
    if sort_field in ("change_1d", "change_5d", "change_1m", "volume", "market_cap"):
        stocks.sort(key=lambda r: r.get(sort_field) or -999, reverse=True)

    _set(ckey, stocks)
    return {"stocks": stocks}
