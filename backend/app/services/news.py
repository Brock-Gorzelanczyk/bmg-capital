from __future__ import annotations

import asyncio
import hashlib
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

ALPACA_NEWS_URL = "https://data.alpaca.markets/v1beta1/news"

# Free public RSS feeds — no API key required
RSS_SOURCES = [
    {
        "url": "https://feeds.reuters.com/reuters/businessNews",
        "source": "Reuters",
    },
    {
        "url": "https://search.cnbc.com/rs/search/combinedcms/view.aspx?partnerId=wrss01&id=100003114",
        "source": "CNBC",
    },
    {
        "url": "https://feeds.marketwatch.com/marketwatch/topstories/",
        "source": "MarketWatch",
    },
    {
        "url": "https://finance.yahoo.com/news/rssindex",
        "source": "Yahoo Finance",
    },
    {
        "url": "https://www.investing.com/rss/news.rss",
        "source": "Investing.com",
    },
    {
        "url": "https://www.fool.com/feeds/index.aspx",
        "source": "Motley Fool",
    },
    {
        "url": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
        "source": "WSJ",
    },
    {
        "url": "https://www.forbes.com/investing/feed2/",
        "source": "Forbes",
    },
]

# XML namespaces used by various RSS feeds
_NS = {
    "dc": "http://purl.org/dc/elements/1.1/",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "media": "http://search.yahoo.com/mrss/",
}


def _parse_date(date_str: str | None) -> str:
    """Parse RFC 2822 or ISO date strings into ISO 8601 UTC."""
    if not date_str:
        return datetime.now(timezone.utc).isoformat()
    try:
        return parsedate_to_datetime(date_str).isoformat()
    except Exception:
        try:
            return datetime.fromisoformat(date_str).isoformat()
        except Exception:
            return datetime.now(timezone.utc).isoformat()


def _article_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:16]


def _text(el: ET.Element | None) -> str:
    return (el.text or "").strip() if el is not None else ""


async def _fetch_rss(
    client: httpx.AsyncClient, source_cfg: Dict[str, str], symbols: Optional[List[str]]
) -> List[Dict[str, Any]]:
    """Fetch and parse a single RSS feed."""
    try:
        resp = await client.get(source_cfg["url"], timeout=8.0, follow_redirects=True)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
    except Exception as e:
        logger.debug(f"RSS {source_cfg['source']} failed: {e}")
        return []

    # Handle both RSS 2.0 (<channel><item>) and Atom (<entry>)
    items = root.findall(".//item") or root.findall(
        ".//{http://www.w3.org/2005/Atom}entry"
    )

    articles = []
    for item in items[:30]:
        # Headline
        headline = (
            _text(item.find("title"))
            or _text(item.find("{http://www.w3.org/2005/Atom}title"))
        )
        if not headline:
            continue

        # URL
        url = (
            _text(item.find("link"))
            or _text(item.find("{http://www.w3.org/2005/Atom}link"))
        )
        link_el = item.find("{http://www.w3.org/2005/Atom}link")
        if not url and link_el is not None:
            url = link_el.get("href", "")

        # Summary
        summary = (
            _text(item.find("description"))
            or _text(item.find("{http://www.w3.org/2005/Atom}summary"))
            or _text(item.find("{http://www.w3.org/2005/Atom}content"))
        )
        # Strip HTML tags from summary
        import re
        summary = re.sub(r"<[^>]+>", "", summary).strip()[:500]

        # Date
        pub_date = _parse_date(
            _text(item.find("pubDate"))
            or _text(item.find("{http://purl.org/dc/elements/1.1/}date"))
            or _text(item.find("{http://www.w3.org/2005/Atom}published"))
            or _text(item.find("{http://www.w3.org/2005/Atom}updated"))
        )

        # Author
        author = (
            _text(item.find("{http://purl.org/dc/elements/1.1/}creator"))
            or _text(item.find("author"))
            or source_cfg["source"]
        )

        article = {
            "id": _article_id(url or headline),
            "headline": headline,
            "summary": summary,
            "author": author,
            "source": source_cfg["source"],
            "url": url,
            "symbols": [],
            "published_at": pub_date,
        }

        # Symbol filter: keep article if headline/summary mentions any requested symbol
        if symbols:
            text_lower = (headline + " " + summary).lower()
            matched = [s for s in symbols if s.lower() in text_lower]
            if not matched:
                continue
            article["symbols"] = matched

        articles.append(article)

    return articles


async def _fetch_alpaca(
    symbols: Optional[List[str]], limit: int
) -> List[Dict[str, Any]]:
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
            resp = await client.get(ALPACA_NEWS_URL, params=params, headers=headers, timeout=10.0)
            resp.raise_for_status()
            data = resp.json()
            return [
                {
                    "id": str(a.get("id", _article_id(a.get("url", "")))),
                    "headline": a.get("headline", ""),
                    "summary": a.get("summary", ""),
                    "author": a.get("author", ""),
                    "source": a.get("source", "Alpaca"),
                    "url": a.get("url", ""),
                    "symbols": a.get("symbols", []),
                    "published_at": a.get("created_at", ""),
                }
                for a in data.get("news", [])
            ]
    except Exception as e:
        logger.error(f"Alpaca news fetch error: {e}")
        return []


async def get_news(
    symbols: Optional[List[str]] = None, limit: int = 20
) -> List[Dict[str, Any]]:
    """Fetch news from Alpaca + multiple RSS sources in parallel, merged and deduplicated."""

    # Run all fetches concurrently
    async with httpx.AsyncClient(
        headers={"User-Agent": "BMGCapital/1.0 (financial news aggregator)"},
        timeout=8.0,
    ) as client:
        tasks = [_fetch_alpaca(symbols, limit)] + [
            _fetch_rss(client, src, symbols) for src in RSS_SOURCES
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    # Flatten + filter exceptions
    all_articles: List[Dict[str, Any]] = []
    for result in results:
        if isinstance(result, list):
            all_articles.extend(result)

    # Deduplicate by headline similarity (first 60 chars)
    seen: set[str] = set()
    unique: List[Dict[str, Any]] = []
    for article in all_articles:
        key = article.get("headline", "")[:60].lower().strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(article)

    # Sort by date descending
    def _sort_key(a: Dict[str, Any]) -> str:
        return a.get("published_at") or ""

    unique.sort(key=_sort_key, reverse=True)

    return unique[: max(limit, 50)]
