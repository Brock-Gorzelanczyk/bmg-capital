from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

FMP_URL = "https://financialmodelingprep.com/api/v3/earning_calendar"


async def get_earnings_calendar(days_ahead: int = 14) -> List[Dict[str, Any]]:
    """Fetch upcoming earnings events from Financial Modeling Prep.

    Requires ``settings.fmp_api_key`` to be set; returns an empty list otherwise.
    """
    if not settings.fmp_api_key:
        return []

    today = datetime.utcnow().date()
    end = today + timedelta(days=days_ahead)
    params = {
        "from": str(today),
        "to": str(end),
        "apikey": settings.fmp_api_key,
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(FMP_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
            return [
                {
                    "symbol": e.get("symbol"),
                    "date": e.get("date"),
                    "eps_estimate": e.get("epsEstimated"),
                    "eps_actual": e.get("eps"),
                    "revenue_estimate": e.get("revenueEstimated"),
                    "revenue_actual": e.get("revenue"),
                    "time": e.get("time"),
                }
                for e in (data if isinstance(data, list) else [])
                if e.get("symbol")
            ]
    except Exception as e:
        logger.error(f"Earnings fetch error: {e}", exc_info=True)
        return []
