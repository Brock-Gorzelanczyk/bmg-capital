from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Query

from app.services.earnings import get_earnings_calendar

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/earnings", tags=["earnings"])


@router.get("")
async def earnings(days_ahead: int = Query(14, le=30), background_tasks: BackgroundTasks = None):
    """Return upcoming earnings events for the next ``days_ahead`` days."""
    data = await get_earnings_calendar(days_ahead)
    return {"earnings": data}


@router.get("/implied-move/{symbol}")
async def implied_move(symbol: str):
    """Return the implied move percentage for a symbol using ATM straddle approximation."""
    try:
        import yfinance as yf

        ticker = yf.Ticker(symbol)
        expirations = ticker.options
        if not expirations:
            return {"symbol": symbol, "implied_move_pct": None}

        opt = ticker.option_chain(expirations[0])
        calls = opt.calls
        puts = opt.puts
        current_price = ticker.fast_info.last_price

        if not current_price or current_price <= 0:
            return {"symbol": symbol, "implied_move_pct": None}

        atm_calls = calls.iloc[(calls["strike"] - current_price).abs().argsort()[:1]]
        atm_puts = puts.iloc[(puts["strike"] - current_price).abs().argsort()[:1]]
        straddle_cost = atm_calls["lastPrice"].iloc[0] + atm_puts["lastPrice"].iloc[0]
        implied_move_pct = (straddle_cost / current_price) * 100
        return {"symbol": symbol, "implied_move_pct": round(implied_move_pct, 1)}
    except Exception:
        return {"symbol": symbol, "implied_move_pct": None}


@router.get("/history/{symbol}")
async def earnings_history(symbol: str):
    """Return last 4 quarters of EPS surprise history for a symbol."""
    try:
        import yfinance as yf
        import pandas as pd

        ticker = yf.Ticker(symbol)

        # Try earnings_history first, fall back to quarterly_earnings
        history = None
        try:
            history = ticker.earnings_history
        except Exception:
            pass

        if history is None or (hasattr(history, "empty") and history.empty):
            try:
                history = ticker.quarterly_earnings
            except Exception:
                pass

        if history is None or (hasattr(history, "empty") and history.empty):
            return {"symbol": symbol, "history": []}

        results = []

        # earnings_history has columns: epsEstimate, epsActual, epsDifference, surprisePercent
        if "epsActual" in history.columns and "epsEstimate" in history.columns:
            # Take the last 4 rows
            subset = history.tail(4)
            for idx, row in subset.iterrows():
                period = str(idx)
                eps_actual = float(row["epsActual"]) if pd.notna(row.get("epsActual")) else None
                eps_estimate = float(row["epsEstimate"]) if pd.notna(row.get("epsEstimate")) else None
                surprise_pct: Optional[float] = None
                if eps_actual is not None and eps_estimate is not None and eps_estimate != 0:
                    surprise_pct = round(((eps_actual - eps_estimate) / abs(eps_estimate)) * 100, 1)
                results.append({
                    "period": period,
                    "eps_actual": eps_actual,
                    "eps_estimate": eps_estimate,
                    "surprise_pct": surprise_pct,
                })
        # quarterly_earnings has columns: Revenue, Earnings (no estimate)
        elif "Earnings" in history.columns:
            subset = history.tail(4)
            for idx, row in subset.iterrows():
                period = str(idx)
                eps_actual = float(row["Earnings"]) if pd.notna(row.get("Earnings")) else None
                results.append({
                    "period": period,
                    "eps_actual": eps_actual,
                    "eps_estimate": None,
                    "surprise_pct": None,
                })

        return {"symbol": symbol, "history": results}
    except Exception as exc:
        logger.warning("earnings_history failed for %s: %s", symbol, exc)
        return {"symbol": symbol, "history": []}
