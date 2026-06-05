"""
Discovery service: curated themes (with live performance), IPO calendar, insider trades.
All endpoints degrade gracefully when API keys are absent.
"""
from __future__ import annotations

import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from datetime import timezone, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

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


# ── IPO calendar — Nasdaq public API (no key required) ───────────────────────

_NASDAQ_IPO_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "User-Agent": "Mozilla/5.0 BMGCapital/1.0",
}

async def get_ipo_calendar(days_ahead: int = 90) -> List[Dict[str, Any]]:
    today = datetime.now(timezone.utc).date()
    results: List[Dict[str, Any]] = []
    seen: set = set()

    months_needed = max(1, (days_ahead // 30) + 2)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            for month_offset in range(months_needed):
                target = today.replace(day=1)
                for _ in range(month_offset):
                    if target.month == 12:
                        target = target.replace(year=target.year + 1, month=1)
                    else:
                        target = target.replace(month=target.month + 1)
                date_str = target.strftime("%Y-%m")
                try:
                    resp = await client.get(
                        "https://api.nasdaq.com/api/ipo/calendar",
                        params={"date": date_str},
                        headers=_NASDAQ_IPO_HEADERS,
                    )
                    if resp.status_code != 200:
                        continue
                    data = resp.json().get("data", {})

                    # Upcoming IPOs — data["upcoming"]["upcomingTable"]["rows"]
                    upcoming_rows = (
                        data.get("upcoming", {})
                            .get("upcomingTable", {})
                            .get("rows") or []
                    )
                    for row in upcoming_rows:
                        sym = (row.get("proposedTickerSymbol") or "").strip()
                        if not sym or sym in seen:
                            continue
                        seen.add(sym)
                        raw_date = row.get("expectedPriceDate") or ""
                        try:
                            dt = datetime.strptime(raw_date, "%m/%d/%Y").date()
                            iso_date = str(dt)
                            if (dt - today).days > days_ahead:
                                continue
                        except Exception:
                            iso_date = raw_date
                        results.append({
                            "company":     row.get("companyName") or sym,
                            "symbol":      sym,
                            "date":        iso_date,
                            "price_range": row.get("proposedSharePrice") or "TBD",
                            "exchange":    row.get("proposedExchange") or "—",
                            "shares":      row.get("sharesOffered") or "",
                            "status":      "upcoming",
                        })

                    # Priced IPOs — data["priced"]["rows"]
                    priced_rows = data.get("priced", {}).get("rows") or []
                    for row in priced_rows:
                        sym = (row.get("proposedTickerSymbol") or "").strip()
                        if not sym or sym in seen:
                            continue
                        seen.add(sym)
                        raw_date = row.get("pricedDate") or ""
                        try:
                            dt = datetime.strptime(raw_date, "%m/%d/%Y").date()
                            iso_date = str(dt)
                        except Exception:
                            iso_date = raw_date
                        results.append({
                            "company":     row.get("companyName") or sym,
                            "symbol":      sym,
                            "date":        iso_date,
                            "price_range": row.get("proposedSharePrice") or "TBD",
                            "exchange":    row.get("proposedExchange") or "—",
                            "shares":      row.get("sharesOffered") or "",
                            "status":      "priced",
                        })

                except Exception as me:
                    logger.warning(f"Nasdaq IPO month {date_str} failed: {me}")
    except Exception as e:
        logger.warning(f"IPO calendar fetch failed: {e}", exc_info=True)

    results.sort(key=lambda x: (x["status"] != "upcoming", x.get("date", "")))
    return results


# ── Insider transactions — SEC EDGAR Form 4 (official SEC data, no key) ──────

_EDGAR_HEADERS = {
    "User-Agent": "BMGCapital research@bmgcapital.com",
    "Accept-Encoding": "gzip, deflate",
    "Accept": "text/html,application/xml,application/json",
}

# 5-minute in-memory cache
_insider_cache: Tuple[Optional[datetime], List[Dict[str, Any]]] = (None, [])


async def get_insider_trades(limit: int = 50) -> List[Dict[str, Any]]:
    """
    Fetch recent insider P (purchase) and S (sale) transactions from SEC EDGAR
    Form 4 filings via the EDGAR EFTS search API + direct XML parsing.
    Cache: 5 minutes.
    """
    global _insider_cache
    cached_at, cached_data = _insider_cache
    if cached_at and (datetime.now(timezone.utc) - cached_at).total_seconds() < 300:
        return cached_data

    today = datetime.now(timezone.utc).date()
    start_date = (today - timedelta(days=30)).isoformat()
    results: List[Dict[str, Any]] = []
    sem = asyncio.Semaphore(10)

    try:
        async with httpx.AsyncClient(timeout=8.0, headers=_EDGAR_HEADERS) as client:
            # Step 1: Fetch recent Form 4 filings from EDGAR EFTS search
            resp = await client.get(
                "https://efts.sec.gov/LATEST/search-index",
                params={
                    "forms": "4",
                    "dateRange": "custom",
                    "startdt": start_date,
                    "enddt": today.isoformat(),
                },
            )
            resp.raise_for_status()
            hits = resp.json().get("hits", {}).get("hits", [])[:100]

            async def process_filing(hit: Dict[str, Any]) -> List[Dict[str, Any]]:
                src = hit.get("_source", {})
                adsh = src.get("adsh", "")
                ciks = src.get("ciks", [])
                if not adsh or not ciks:
                    return []

                # First CIK is the reporting person (filer); use without leading zeros
                filer_cik = ciks[0].lstrip("0") or ciks[0]
                adsh_no_dash = adsh.replace("-", "")

                async with sem:
                    try:
                        # Fetch the filing index page (listed under filer's CIK)
                        idx_url = (
                            f"https://www.sec.gov/Archives/edgar/data"
                            f"/{filer_cik}/{adsh_no_dash}/{adsh}-index.htm"
                        )
                        idx_resp = await client.get(idx_url, timeout=5.0)
                        if idx_resp.status_code != 200:
                            return []

                        # Extract the raw XML link (skip xslF345X06 styled version)
                        xml_links = re.findall(
                            r'href="(/Archives/edgar/data/[^"]+\.xml)"',
                            idx_resp.text,
                        )
                        raw_links = [l for l in xml_links if "xslF345X06" not in l]
                        if not raw_links:
                            return []

                        # Fetch the Form 4 XML
                        xml_resp = await client.get(
                            f"https://www.sec.gov{raw_links[0]}", timeout=5.0
                        )
                        if xml_resp.status_code != 200:
                            return []

                        root = ET.fromstring(xml_resp.text)

                        # Issuer info
                        ticker_el  = root.find("issuer/issuerTradingSymbol")
                        company_el = root.find("issuer/issuerName")
                        ticker  = (ticker_el.text  or "").strip() if ticker_el  is not None else ""
                        company = (company_el.text or "").strip() if company_el is not None else ""
                        if not ticker:
                            return []

                        # Reporting owner info
                        owner_el = root.find("reportingOwner")
                        insider, title = "", ""
                        if owner_el is not None:
                            n = owner_el.find("reportingOwnerId/rptOwnerName")
                            t = owner_el.find("reportingOwnerRelationship/officerTitle")
                            insider = (n.text or "").strip() if n is not None else ""
                            title   = (t.text or "").strip() if t is not None else ""

                        # Non-derivative transactions: P = purchase, S = sale only
                        txs: List[Dict[str, Any]] = []
                        table = root.find("nonDerivativeTable")
                        if table:
                            for tx in table.findall("nonDerivativeTransaction"):
                                code_el   = tx.find("transactionCoding/transactionCode")
                                shares_el = tx.find("transactionAmounts/transactionShares/value")
                                price_el  = tx.find("transactionAmounts/transactionPricePerShare/value")
                                date_el   = tx.find("transactionDate/value")

                                code = (code_el.text or "").strip() if code_el is not None else ""
                                if code not in ("P", "S"):
                                    continue
                                try:
                                    shares    = abs(float((shares_el.text or "0").replace(",", ""))) if shares_el is not None else 0.0
                                    price_per = float((price_el.text or "0").replace(",", ""))       if price_el  is not None else 0.0
                                except Exception:
                                    continue
                                if shares < 1:
                                    continue
                                value = round(shares * price_per)
                                if value < 5_000:
                                    continue
                                tx_date = (date_el.text or "").strip() if date_el is not None else src.get("file_date", "")
                                txs.append({
                                    "symbol":      ticker,
                                    "company":     company,
                                    "name":        insider,
                                    "title":       title,
                                    "transaction": "buy" if code == "P" else "sell",
                                    "shares":      int(shares),
                                    "value":       value,
                                    "date":        tx_date,
                                })
                        return txs

                    except Exception as e:
                        logger.debug(f"Filing {adsh}: {e}")
                        return []

            # Process all filings concurrently (semaphore limits to 10 at a time)
            tasks = [process_filing(h) for h in hits]
            gathered = await asyncio.gather(*tasks, return_exceptions=True)
            for item in gathered:
                if isinstance(item, list):
                    results.extend(item)

    except Exception as e:
        logger.warning(f"SEC EDGAR insider trades failed: {e}", exc_info=True)

    # Buys first, then by value descending
    results.sort(key=lambda x: (x["transaction"] != "buy", -x["value"]))
    results = results[:limit]

    _insider_cache = (datetime.now(timezone.utc), results)
    return results
