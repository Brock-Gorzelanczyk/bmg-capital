from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

ALPACA_NEWS_URL = "https://data.alpaca.markets/v1beta1/news"


async def get_news(
    symbols: Optional[List[str]] = None, limit: int = 20
) -> List[Dict[str, Any]]:
    """Fetch news articles from the Alpaca News API.

    Parameters
    ----------
    symbols:
        Optional list of ticker symbols to filter articles. If None, returns
        general market news.
    limit:
        Maximum number of articles to return (max 50).
    """
    if not settings.alpaca_api_key:
        return []

    params: Dict[str, Any] = {"limit": limit, "sort": "desc"}
    if symbols:
        params["symbols"] = ",".join(symbols)

    headers = {
        "APCA-API-KEY-ID": settings.alpaca_api_key,
        "APCA-API-SECRET-KEY": settings.alpaca_secret_key,
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(ALPACA_NEWS_URL, params=params, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            articles = data.get("news", [])
            return [
                {
                    "id": a.get("id"),
                    "headline": a.get("headline"),
                    "summary": a.get("summary"),
                    "author": a.get("author"),
                    "source": a.get("source"),
                    "url": a.get("url"),
                    "symbols": a.get("symbols", []),
                    "published_at": a.get("created_at"),
                }
                for a in articles
            ]
    except Exception as e:
        logger.error(f"News fetch error: {e}", exc_info=True)
        return []
