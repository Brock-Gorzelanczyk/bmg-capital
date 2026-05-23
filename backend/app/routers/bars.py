from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import yfinance as yf
from fastapi import APIRouter, HTTPException, Query

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
            days_back = 9125   # ~25 years
        elif timeframe == "1Week":
            days_back = 7300   # ~20 years
        elif timeframe == "1Day":
            days_back = 5475   # ~15 years
        elif timeframe in ("4Hour", "1Hour"):
            days_back = 729
        elif timeframe in ("30Min", "15Min", "5Min"):
            days_back = 59
        else:                  # 1Min
            days_back = 7
        max_days = YF_MAX_DAYS.get(timeframe, 3650)
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

    cached = get_cached(symbol, timeframe, start_str, end_str)
    if cached:
        indicator_data = {}
        if indicators:
            try:
                ohlcv = [{"open": b["o"], "high": b["h"], "low": b["l"], "close": b["c"], "volume": b["v"]} for b in cached]
                df_cached = pd.DataFrame(ohlcv)
                requested = [i.strip() for i in indicators.split(",")]
                indicator_data = compute_indicators(df_cached, requested)
            except Exception:
                pass
        return {"symbol": symbol.upper(), "bars": cached, "indicators": indicator_data}

    try:
        ticker = yf.Ticker(symbol.upper())
        # end is exclusive in yfinance, add 1 day to include today
        hist = ticker.history(
            start=start_str,
            end=(end_dt + timedelta(days=1)).date().isoformat(),
            interval=interval,
            auto_adjust=True,
        )

        if hist.empty:
            raise HTTPException(status_code=404, detail=f"No data for {symbol}")

        # Resample 1h bars to 4h for the 4Hour timeframe
        if timeframe == "4Hour":
            hist = hist.resample("4h", closed="left", label="left").agg({
                "Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"
            }).dropna(subset=["Open", "Close"])

        bars_list = []
        ohlcv = []
        for idx, row in hist.iterrows():
            o = float(row["Open"])
            h = float(row["High"])
            l = float(row["Low"])
            c = float(row["Close"])
            v = float(row["Volume"])
            if pd.isna(o) or pd.isna(c):
                continue
            ts = idx.isoformat() if hasattr(idx, "isoformat") else str(idx)
            bars_list.append({"t": ts, "o": o, "h": h, "l": l, "c": c, "v": v})
            ohlcv.append({"open": o, "high": h, "low": l, "close": c, "volume": v})

        if not bars_list:
            raise HTTPException(status_code=404, detail=f"No data for {symbol}")

        df = pd.DataFrame(ohlcv)

        ttl = 3600 if timeframe in ("4Hour", "1Hour") else 300 if timeframe in ("30Min", "15Min", "5Min", "1Min") else 86400
        set_cache(symbol, timeframe, start_str, end_str, bars_list, ttl)

        indicator_data = {}
        if indicators and len(df) > 0:
            requested = [i.strip() for i in indicators.split(",")]
            indicator_data = compute_indicators(df, requested)

        return {"symbol": symbol.upper(), "bars": bars_list, "indicators": indicator_data}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
