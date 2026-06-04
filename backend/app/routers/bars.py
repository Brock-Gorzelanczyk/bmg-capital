from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import yfinance as yf
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.indicators.engine import compute_indicators
from app.services.bar_cache import get_cached, set_cache

router = APIRouter(prefix="/api/bars", tags=["bars"])

YF_INTERVAL_MAP = {
    "1Min": "1m",
    "5Min": "5m",
    "15Min": "15m",
    "30Min": "30m",
    "1Hour": "1h",
    "4Hour": "1h",   # download 1h, resample to 4h
    "1Day": "1d",
    "1Week": "1wk",
    "1Month": "1mo",
}

# yfinance enforces max lookback per interval
YF_MAX_DAYS: dict[str, int] = {
    "1Min": 7,
    "5Min": 59,
    "15Min": 59,
    "30Min": 59,
    "1Hour": 729,
    "4Hour": 729,
}

# Timeframes that support indicator warm-up (daily and coarser only)
DAILY_TIMEFRAMES = {"1Day", "1Week", "1Month"}

# Calendar days per bar for each timeframe (with a ~10% buffer baked in)
_DAYS_PER_BAR: dict[str, float] = {
    "1Day":   1.5,   # ~1 trading day = 1.4 calendar days; +buffer
    "1Week":  7.5,   # 1 week = 7 calendar days; +buffer
    "1Month": 33.0,  # ~1 month = 30-31 calendar days; +buffer
}


def _max_indicator_lookback(indicators_str: Optional[str]) -> int:
    """Return the largest period in indicator keys (e.g. SMA_200 → 200, ICHIMOKU → 52)."""
    if not indicators_str:
        return 0
    max_p = 0
    for key in indicators_str.split(","):
        key = key.strip()
        parts = key.split("_")
        if len(parts) >= 2:
            try:
                max_p = max(max_p, int(parts[-1]))
            except ValueError:
                pass
        if key == "MACD":
            max_p = max(max_p, 26)
        if key == "ICHIMOKU":
            max_p = max(max_p, 52)
        if key in ("DONCHIAN", "KELTNER"):
            max_p = max(max_p, 20)
    return max_p


_CCXT_TF_MAP = {
    "1Min": "1m", "5Min": "5m", "15Min": "15m", "30Min": "30m",
    "1Hour": "1h", "4Hour": "4h", "1Day": "1d", "1Week": "1w", "1Month": "1M",
}


def _fetch_ccxt_ohlcv(symbol: str, timeframe: str, start_str: str) -> list[dict]:
    """CCXT/Binance fallback for crypto symbols like FET-USD → FET/USDT."""
    try:
        import ccxt
        base = symbol.upper().replace("-USD", "").replace("-USDT", "")
        ccxt_sym = f"{base}/USDT"
        ccxt_tf = _CCXT_TF_MAP.get(timeframe, "1d")
        since = int(datetime.fromisoformat(start_str).timestamp() * 1000)
        exchange = ccxt.binance({"enableRateLimit": True})
        ohlcv = exchange.fetch_ohlcv(ccxt_sym, timeframe=ccxt_tf, since=since, limit=1000)
        return [
            {
                "_t": datetime.utcfromtimestamp(r[0] / 1000).isoformat(),
                "open": r[1], "high": r[2], "low": r[3], "close": r[4], "volume": r[5],
            }
            for r in ohlcv if r[4] is not None
        ]
    except Exception:
        return []


def _fetch_yf_ohlcv(ticker: yf.Ticker, start_str: str, end_str: str, interval: str, timeframe: str) -> list[dict]:
    """Fetch OHLCV from yfinance and return as a list of dicts with open/high/low/close/volume."""
    hist = ticker.history(
        start=start_str,
        end=end_str,
        interval=interval,
        auto_adjust=True,
    )
    if hist.empty:
        return []

    if timeframe == "4Hour":
        hist = hist.resample("4h", closed="left", label="left").agg({
            "Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"
        }).dropna(subset=["Open", "Close"])

    rows = []
    for idx, row in hist.iterrows():
        o, h, l, c, v = float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"]), float(row["Volume"])
        if pd.isna(o) or pd.isna(c):
            continue
        rows.append({"open": o, "high": h, "low": l, "close": c, "volume": v,
                     "_t": idx.isoformat() if hasattr(idx, "isoformat") else str(idx)})
    return rows


class BatchBarsRequest(BaseModel):
    symbols: list[str]
    start: str | None = None
    end: str | None = None
    timeframe: str = "1Day"


async def _fetch_bars_for_symbol(
    symbol: str,
    start: Optional[str],
    end: Optional[str],
    timeframe: str,
) -> dict:
    """Fetch OHLCV bars for a single symbol. Returns same shape as GET /{symbol} (without indicators)."""
    interval = YF_INTERVAL_MAP.get(timeframe, "1d")
    end_dt = datetime.utcnow() if not end else datetime.fromisoformat(end)

    if not start:
        if timeframe == "1Month":
            days_back = 9125
        elif timeframe == "1Week":
            days_back = 7300
        elif timeframe == "1Day":
            days_back = 5475
        elif timeframe in ("4Hour", "1Hour"):
            days_back = 729
        elif timeframe in ("30Min", "15Min", "5Min"):
            days_back = 59
        else:
            days_back = 7
        max_days = YF_MAX_DAYS.get(timeframe, 20000)
        days_back = min(days_back, max_days)
        start_dt = end_dt - timedelta(days=days_back)
    else:
        start_dt = datetime.fromisoformat(start)
        max_days = YF_MAX_DAYS.get(timeframe)
        if max_days:
            earliest = end_dt - timedelta(days=max_days)
            if start_dt < earliest:
                start_dt = earliest

    start_str = start_dt.date().isoformat()
    end_str = end_dt.date().isoformat()
    end_exclusive = (end_dt + timedelta(days=1)).date().isoformat()

    cached = get_cached(symbol, timeframe, start_str, end_str)
    if cached:
        bars_list = cached
    else:
        ticker = yf.Ticker(symbol.upper())
        rows = _fetch_yf_ohlcv(ticker, start_str, end_exclusive, interval, timeframe)
        if not rows:
            rows = _fetch_ccxt_ohlcv(symbol, timeframe, start_str)
        if not rows:
            raise HTTPException(status_code=404, detail=f"No data for {symbol}")

        bars_list = [
            {"t": r["_t"], "o": r["open"], "h": r["high"], "l": r["low"], "c": r["close"], "v": r["volume"]}
            for r in rows
        ]
        ttl = 3600 if timeframe in ("4Hour", "1Hour") else 300 if timeframe in ("30Min", "15Min", "5Min", "1Min") else 86400
        set_cache(symbol, timeframe, start_str, end_str, bars_list, ttl)

    return {"bars": bars_list}


@router.get("/latest")
async def get_latest_prices(
    symbols: str = Query(..., description="Comma-separated symbols e.g. NVDA,AAPL,BTC-USD"),
):
    """Return the latest close price for up to 30 symbols. Used for live P&L in position tables."""
    sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()][:30]
    prices: dict[str, float | None] = {}
    for sym in sym_list:
        try:
            ticker = yf.Ticker(sym)
            hist = ticker.history(period="2d")
            if not hist.empty:
                prices[sym] = round(float(hist["Close"].iloc[-1]), 4)
            else:
                prices[sym] = None
        except Exception:
            prices[sym] = None
    return {"prices": prices}


@router.post("/batch")
async def get_bars_batch(body: BatchBarsRequest):
    """Fetch OHLCV bars for multiple symbols in a single request (capped at 20 symbols)."""
    results = {}
    for symbol in body.symbols[:20]:
        try:
            bars_data = await _fetch_bars_for_symbol(symbol, body.start, body.end, body.timeframe)
            results[symbol] = bars_data
        except Exception as e:
            results[symbol] = {"bars": [], "error": str(e)}
    return {"results": results}


@router.get("/{symbol}")
async def get_bars(
    symbol: str,
    timeframe: str = Query("1Day"),
    start: Optional[str] = None,
    end: Optional[str] = None,
    indicators: Optional[str] = Query(
        None, description="Comma-separated indicator keys, e.g. SMA_20,RSI_14,MACD"
    ),
):
    """Fetch OHLCV bars for a symbol with optional technical indicators."""
    interval = YF_INTERVAL_MAP.get(timeframe, "1d")
    end_dt = datetime.utcnow() if not end else datetime.fromisoformat(end)

    if not start:
        if timeframe == "1Month":
            days_back = 9125
        elif timeframe == "1Week":
            days_back = 7300
        elif timeframe == "1Day":
            days_back = 5475
        elif timeframe in ("4Hour", "1Hour"):
            days_back = 729
        elif timeframe in ("30Min", "15Min", "5Min"):
            days_back = 59
        else:
            days_back = 7
        max_days = YF_MAX_DAYS.get(timeframe, 20000)
        days_back = min(days_back, max_days)
        start_dt = end_dt - timedelta(days=days_back)
    else:
        start_dt = datetime.fromisoformat(start)
        max_days = YF_MAX_DAYS.get(timeframe)
        if max_days:
            earliest = end_dt - timedelta(days=max_days)
            if start_dt < earliest:
                start_dt = earliest

    start_str = start_dt.date().isoformat()
    end_str = end_dt.date().isoformat()
    end_exclusive = (end_dt + timedelta(days=1)).date().isoformat()

    # ── Main bars ──────────────────────────────────────────────────────────────
    cached = get_cached(symbol, timeframe, start_str, end_str)
    if cached:
        bars_list = cached
        main_ohlcv = [{"open": b["o"], "high": b["h"], "low": b["l"], "close": b["c"], "volume": b["v"]} for b in bars_list]
    else:
        try:
            ticker = yf.Ticker(symbol.upper())
            rows = _fetch_yf_ohlcv(ticker, start_str, end_exclusive, interval, timeframe)
            if not rows:
                # CCXT fallback for crypto symbols (e.g. FET-USD → FET/USDT on Binance)
                rows = _fetch_ccxt_ohlcv(symbol, timeframe, start_str)
            if not rows:
                raise HTTPException(status_code=404, detail=f"No data for {symbol}")

            bars_list = [{"t": r["_t"], "o": r["open"], "h": r["high"], "l": r["low"], "c": r["close"], "v": r["volume"]} for r in rows]
            main_ohlcv = [{"open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"], "volume": r["volume"]} for r in rows]

            ttl = 3600 if timeframe in ("4Hour", "1Hour") else 300 if timeframe in ("30Min", "15Min", "5Min", "1Min") else 86400
            set_cache(symbol, timeframe, start_str, end_str, bars_list, ttl)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    if not bars_list:
        raise HTTPException(status_code=404, detail=f"No data for {symbol}")

    # ── Indicator computation with warm-up ─────────────────────────────────────
    indicator_data: dict = {}
    if indicators and main_ohlcv:
        requested = [i.strip() for i in indicators.split(",")]

        # For daily+ timeframes with long-period indicators, prepend warm-up bars
        # so the full indicator series is valid for every visible bar.
        warmup_ohlcv: list[dict] = []
        if start and timeframe in DAILY_TIMEFRAMES:
            lookback = _max_indicator_lookback(indicators)
            if lookback > 0:
                days_per_bar = _DAYS_PER_BAR.get(timeframe, 1.5)
                extra_days = math.ceil(lookback * days_per_bar)
                warmup_start = start_dt - timedelta(days=extra_days)
                warmup_key = f"__warmup_{symbol}_{timeframe}_{warmup_start.date().isoformat()}_{start_str}"
                warmup_cached = get_cached(symbol, f"{timeframe}_warmup", warmup_start.date().isoformat(), start_str)
                if warmup_cached:
                    warmup_ohlcv = warmup_cached
                else:
                    try:
                        wt = yf.Ticker(symbol.upper())
                        wrows = _fetch_yf_ohlcv(wt, warmup_start.date().isoformat(), start_str, interval, timeframe)
                        warmup_ohlcv = [{"open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"], "volume": r["volume"]} for r in wrows]
                        set_cache(symbol, f"{timeframe}_warmup", warmup_start.date().isoformat(), start_str, warmup_ohlcv, 86400)
                    except Exception:
                        warmup_ohlcv = []  # fall back to no warm-up — indicators may start late

        full_ohlcv = warmup_ohlcv + main_ohlcv
        full_df = pd.DataFrame(full_ohlcv)
        n_warmup = len(warmup_ohlcv)

        try:
            all_indicators = compute_indicators(full_df, requested)
            # Strip the warm-up prefix so indicator arrays align 1:1 with returned bars
            indicator_data = {k: v[n_warmup:] for k, v in all_indicators.items()}
        except Exception:
            indicator_data = {}

    return {"symbol": symbol.upper(), "bars": bars_list, "indicators": indicator_data}
