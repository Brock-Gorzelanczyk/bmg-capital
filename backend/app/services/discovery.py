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


# ── IPO calendar — Nasdaq public API (no key required) ───────────────────────

_NASDAQ_IPO_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "User-Agent": "Mozilla/5.0 BMGCapital/1.0",
}

async def get_ipo_calendar(days_ahead: int = 90) -> List[Dict[str, Any]]:
    today = datetime.utcnow().date()
    results: List[Dict[str, Any]] = []
    seen: set = set()

    # Fetch current month + next month(s) to cover days_ahead window
    months_needed = max(1, (days_ahead // 30) + 2)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            for month_offset in range(months_needed):
                target = today.replace(day=1)
                # advance by month_offset months
                for _ in range(month_offset):
                    # move to first of next month
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
                    for section, status in [("upcomingTable", "upcoming"), ("recentTable", "priced")]:
                        rows = data.get(section, {}).get("rows") or []
                        for row in rows:
                            sym = (row.get("proposedTickerSymbol") or "").strip()
                            if not sym or sym in seen:
                                continue
                            seen.add(sym)
                            # Parse expected date
                            raw_date = row.get("expectedPriceDate") or row.get("pricedDate") or ""
                            try:
                                dt = datetime.strptime(raw_date, "%m/%d/%Y").date()
                                iso_date = str(dt)
                                if status == "upcoming" and (dt - today).days > days_ahead:
                                    continue
                            except Exception:
                                iso_date = raw_date
                            price_range = row.get("proposedSharePrice") or "TBD"
                            results.append({
                                "company":     row.get("companyName") or sym,
                                "symbol":      sym,
                                "date":        iso_date,
                                "price_range": price_range,
                                "exchange":    row.get("exchange") or "—",
                                "shares":      row.get("sharesOffered") or "",
                                "status":      status,
                            })
                except Exception as me:
                    logger.warning(f"Nasdaq IPO month {date_str} failed: {me}")
    except Exception as e:
        logger.warning(f"IPO calendar fetch failed: {e}", exc_info=True)

    # Sort upcoming first by date, then recent by date desc
    results.sort(key=lambda x: (x["status"] != "upcoming", x.get("date", "")))
    return results


# ── Insider transactions — OpenInsider (aggregates SEC Form 4, no key) ───────

_OPENINSIDER_URL = "https://openinsider.com/screener"
_OPENINSIDER_HEADERS = {
    "User-Agent": "Mozilla/5.0 BMGCapital/1.0",
    "Accept": "text/html,application/xhtml+xml",
}

# Trade type codes → buy/sell
_TX_MAP = {
    "P": "buy",   # Purchase
    "S": "sell",  # Sale
    "S-": "sell", # Sale (planned)
    "S+": "sell", # Sale (auto)
}


def _parse_number(s: str) -> int:
    """'1,234,567' → 1234567"""
    try:
        return int(s.replace(",", "").replace("+", "").strip())
    except Exception:
        return 0


def _parse_value(s: str) -> int:
    """'$1.2M' or '$123,456' → int dollars"""
    try:
        s = s.strip().lstrip("$").replace(",", "")
        if s.endswith("M"):
            return int(float(s[:-1]) * 1_000_000)
        if s.endswith("K"):
            return int(float(s[:-1]) * 1_000)
        if s.endswith("B"):
            return int(float(s[:-1]) * 1_000_000_000)
        return int(float(s))
    except Exception:
        return 0


async def get_insider_trades(limit: int = 50) -> List[Dict[str, Any]]:
    try:
        from bs4 import BeautifulSoup
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(
                _OPENINSIDER_URL,
                params={
                    "form": "4",
                    "cnt": str(min(limit, 100)),
                    "Action": "1",
                    # Filter: purchases + sales, min value $50k
                    "vl": "50",
                    "xp": "1",
                    "xs": "1",
                },
                headers=_OPENINSIDER_HEADERS,
            )
            resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.find("table", {"class": "tinytable"})
        if not table:
            raise ValueError("OpenInsider table not found")

        rows = table.find("tbody").find_all("tr")  # type: ignore[union-attr]
        results: List[Dict[str, Any]] = []
        for row in rows:
            cols = row.find_all("td")
            if len(cols) < 12:
                continue
            # Columns (0-indexed): 0=X, 1=Filing Date, 2=Trade Date, 3=Ticker,
            # 4=Company, 5=Insider Name, 6=Title, 7=Trade Type, 8=Price,
            # 9=Qty, 10=Owned, 11=ΔOwn%, 12=Value
            ticker = cols[3].get_text(strip=True)
            company = cols[4].get_text(strip=True)
            insider = cols[5].get_text(strip=True)
            title = cols[6].get_text(strip=True)
            tx_code = cols[7].get_text(strip=True).split()[0] if cols[7].get_text(strip=True) else ""
            trade_date = cols[2].get_text(strip=True)
            qty = _parse_number(cols[9].get_text(strip=True))
            value = _parse_value(cols[12].get_text(strip=True)) if len(cols) > 12 else 0

            ttype = _TX_MAP.get(tx_code)
            if not ttype or not ticker or qty == 0:
                continue

            # Normalise date YYYY-MM-DD
            try:
                dt = datetime.strptime(trade_date, "%Y-%m-%d").date()
                iso_date = str(dt)
            except Exception:
                iso_date = trade_date

            results.append({
                "symbol":      ticker,
                "company":     company,
                "name":        insider,
                "title":       title,
                "transaction": ttype,
                "shares":      qty,
                "value":       value,
                "date":        iso_date,
            })
            if len(results) >= limit:
                break
        return results
    except Exception as e:
        logger.warning(f"OpenInsider scrape failed: {e}", exc_info=True)
        return []
