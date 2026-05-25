"""
Discovery service: curated themes (with live performance), IPO calendar, insider trades.
All endpoints degrade gracefully when API keys are absent.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# ── Curated themes ──────────────────────────────────────────────────────────

THEMES: List[Dict[str, Any]] = [
    {
        "id": "ai-ml",
        "name": "AI & Machine Learning",
        "description": "Companies at the forefront of artificial intelligence and large-scale compute.",
        "emoji": "🤖",
        "color": "violet",
        "tickers": ["NVDA", "MSFT", "GOOGL", "META", "AMD", "PLTR", "AI", "AMZN"],
    },
    {
        "id": "cybersecurity",
        "name": "Cybersecurity",
        "description": "Protecting enterprise infrastructure from evolving digital threats.",
        "emoji": "🛡️",
        "color": "blue",
        "tickers": ["CRWD", "PANW", "ZS", "OKTA", "FTNT", "S", "CYBR"],
    },
    {
        "id": "cloud",
        "name": "Cloud & SaaS",
        "description": "Software-as-a-service and cloud infrastructure leaders.",
        "emoji": "☁️",
        "color": "sky",
        "tickers": ["CRM", "NOW", "SNOW", "DDOG", "MDB", "NET", "TEAM", "HUBS"],
    },
    {
        "id": "clean-energy",
        "name": "Clean Energy",
        "description": "Renewable energy producers, grid tech, and storage innovators.",
        "emoji": "🌱",
        "color": "emerald",
        "tickers": ["NEE", "ENPH", "FSLR", "PLUG", "BE", "RUN", "SEDG", "ICLN"],
    },
    {
        "id": "ev-autonomous",
        "name": "EV & Autonomous",
        "description": "Electric vehicles and self-driving technology disruptors.",
        "emoji": "⚡",
        "color": "amber",
        "tickers": ["TSLA", "RIVN", "NIO", "XPEV", "LCID", "APTV", "ON"],
    },
    {
        "id": "semiconductors",
        "name": "Semiconductors",
        "description": "Chip designers and fab equipment makers powering every device.",
        "emoji": "💾",
        "color": "orange",
        "tickers": ["NVDA", "AMD", "INTC", "QCOM", "AVGO", "AMAT", "LRCX", "MU"],
    },
    {
        "id": "fintech",
        "name": "FinTech",
        "description": "Payments, lending, and financial infrastructure reinvented.",
        "emoji": "💳",
        "color": "green",
        "tickers": ["SQ", "PYPL", "V", "MA", "AFRM", "UPST", "HOOD", "NU"],
    },
    {
        "id": "biotech",
        "name": "Biotech & Genomics",
        "description": "Next-generation therapeutics, CRISPR, and precision medicine.",
        "emoji": "🧬",
        "color": "rose",
        "tickers": ["MRNA", "BNTX", "REGN", "VRTX", "EDIT", "BEAM", "PACB", "ILMN"],
    },
    {
        "id": "defense",
        "name": "Defense & Aerospace",
        "description": "Defense contractors and space technology companies.",
        "emoji": "🚀",
        "color": "slate",
        "tickers": ["LMT", "RTX", "NOC", "GD", "BA", "LHX", "SPCE"],
    },
    {
        "id": "consumer",
        "name": "Consumer Brands",
        "description": "Iconic consumer brands with enduring pricing power.",
        "emoji": "🛍️",
        "color": "pink",
        "tickers": ["AAPL", "NKE", "SBUX", "MCD", "LULU", "TGT", "COST", "AMZN"],
    },
]

# ── Theme performance (live Alpaca data) ────────────────────────────────────

async def get_themes_with_performance() -> List[Dict[str, Any]]:
    """Return themes augmented with average constituent 1-day performance."""
    try:
        from alpaca.data.requests import StockSnapshotRequest
        from alpaca.data.enums import DataFeed
        from app.alpaca.client import get_historical_client

        all_tickers = list({t for theme in THEMES for t in theme["tickers"]})
        client = get_historical_client()
        req = StockSnapshotRequest(symbol_or_symbols=all_tickers, feed=DataFeed.IEX)
        snapshots = client.get_stock_snapshot(req)

        perf: Dict[str, float] = {}
        prices: Dict[str, float] = {}
        for sym, snap in snapshots.items():
            daily = snap.daily_bar
            prev = snap.previous_daily_bar
            if daily and prev and float(prev.close) > 0:
                change = (float(daily.close) - float(prev.close)) / float(prev.close) * 100
                perf[sym] = round(change, 2)
                prices[sym] = round(float(daily.close), 2)

        result = []
        for theme in THEMES:
            tickers = theme["tickers"]
            changes = [perf[t] for t in tickers if t in perf]
            avg_change = round(sum(changes) / len(changes), 2) if changes else 0.0
            constituents = [
                {"symbol": t, "change_pct": perf.get(t, 0.0), "price": prices.get(t, 0.0)}
                for t in tickers
            ]
            result.append({**theme, "avg_change_pct": avg_change, "constituents": constituents})
        return result
    except Exception as e:
        logger.warning(f"Theme performance fetch failed: {e} — returning static", exc_info=True)
        return [{**t, "avg_change_pct": 0.0, "constituents": [{"symbol": s, "change_pct": 0.0, "price": 0.0} for s in t["tickers"]]} for t in THEMES]


# ── IPO calendar ────────────────────────────────────────────────────────────

FMP_IPO_URL = "https://financialmodelingprep.com/api/v3/ipo_calendar"

_DEMO_IPOS = [
    {"company": "Databricks", "symbol": "DBX", "date": "2025-07-10", "price_range": "$38–$42", "exchange": "NASDAQ", "status": "upcoming"},
    {"company": "Shein", "symbol": "SHEIN", "date": "2025-07-18", "price_range": "$20–$24", "exchange": "NYSE", "status": "upcoming"},
    {"company": "Klarna", "symbol": "KLAR", "date": "2025-08-05", "price_range": "$60–$68", "exchange": "NYSE", "status": "upcoming"},
    {"company": "Discord", "symbol": "DISC", "date": "2025-08-14", "price_range": "$28–$32", "exchange": "NASDAQ", "status": "upcoming"},
    {"company": "Stripe", "symbol": "STRP", "date": "2025-09-02", "price_range": "$45–$52", "exchange": "NYSE", "status": "rumored"},
]


async def get_ipo_calendar(days_ahead: int = 90) -> List[Dict[str, Any]]:
    if not settings.fmp_api_key:
        return _DEMO_IPOS

    today = datetime.utcnow().date()
    end = today + timedelta(days=days_ahead)
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                FMP_IPO_URL,
                params={"from": str(today), "to": str(end), "apikey": settings.fmp_api_key},
            )
            resp.raise_for_status()
            data = resp.json()
            return [
                {
                    "company": e.get("company", ""),
                    "symbol": e.get("symbol", ""),
                    "date": e.get("date", ""),
                    "price_range": f"${e.get('priceRange', 'TBD')}",
                    "exchange": e.get("exchange", ""),
                    "status": "upcoming",
                }
                for e in (data if isinstance(data, list) else [])
                if e.get("symbol")
            ]
    except Exception as e:
        logger.warning(f"IPO calendar fetch failed: {e}", exc_info=True)
        return _DEMO_IPOS


# ── Insider transactions ────────────────────────────────────────────────────

FMP_INSIDER_URL = "https://financialmodelingprep.com/api/v4/insider-trading"

_DEMO_INSIDERS = [
    {"symbol": "NVDA", "name": "Jensen Huang", "title": "CEO", "transaction": "sell", "shares": 120_000, "value": 14_400_000, "date": "2025-05-20"},
    {"symbol": "META", "name": "Mark Zuckerberg", "title": "CEO", "transaction": "sell", "shares": 40_000, "value": 22_000_000, "date": "2025-05-19"},
    {"symbol": "TSLA", "name": "Elon Musk", "title": "CEO", "transaction": "buy", "shares": 500_000, "value": 87_500_000, "date": "2025-05-18"},
    {"symbol": "AMZN", "name": "Andy Jassy", "title": "CEO", "transaction": "sell", "shares": 15_000, "value": 2_850_000, "date": "2025-05-17"},
    {"symbol": "GOOGL", "name": "Sundar Pichai", "title": "CEO", "transaction": "sell", "shares": 18_000, "value": 3_060_000, "date": "2025-05-16"},
    {"symbol": "MSFT", "name": "Satya Nadella", "title": "CEO", "transaction": "sell", "shares": 10_000, "value": 4_300_000, "date": "2025-05-15"},
    {"symbol": "CRWD", "name": "George Kurtz", "title": "CEO", "transaction": "buy", "shares": 5_000, "value": 1_750_000, "date": "2025-05-14"},
    {"symbol": "AAPL", "name": "Tim Cook", "title": "CEO", "transaction": "sell", "shares": 100_000, "value": 18_900_000, "date": "2025-05-13"},
    {"symbol": "PLTR", "name": "Alexander Karp", "title": "CEO", "transaction": "sell", "shares": 200_000, "value": 3_800_000, "date": "2025-05-12"},
    {"symbol": "AMD", "name": "Lisa Su", "title": "CEO", "transaction": "buy", "shares": 20_000, "value": 3_000_000, "date": "2025-05-11"},
]


async def get_insider_trades(limit: int = 50) -> List[Dict[str, Any]]:
    if not settings.fmp_api_key:
        return _DEMO_INSIDERS

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                FMP_INSIDER_URL,
                params={"limit": limit, "apikey": settings.fmp_api_key},
            )
            resp.raise_for_status()
            data = resp.json()
            results = []
            for e in (data if isinstance(data, list) else []):
                tx = e.get("transactionType", "").lower()
                if "purchase" in tx or "buy" in tx:
                    ttype = "buy"
                elif "sale" in tx or "sell" in tx:
                    ttype = "sell"
                else:
                    continue
                shares = e.get("securitiesTransacted") or 0
                price = e.get("price") or 0
                results.append({
                    "symbol": e.get("symbol", ""),
                    "name": e.get("reportingName", ""),
                    "title": e.get("typeOfOwner", ""),
                    "transaction": ttype,
                    "shares": int(shares),
                    "value": round(float(shares) * float(price)),
                    "date": e.get("transactionDate", ""),
                })
            return results[:limit]
    except Exception as e:
        logger.warning(f"Insider trades fetch failed: {e}", exc_info=True)
        return _DEMO_INSIDERS
