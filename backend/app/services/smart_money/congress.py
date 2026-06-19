"""
Fetches Congressional stock disclosures from Financial Modeling Prep (FMP).
Senate: GET https://financialmodelingprep.com/api/v4/senate-trading?apikey=KEY
House:  GET https://financialmodelingprep.com/api/v4/senate-disclosure?apikey=KEY
Free plan: 250 calls/day. Daily cron uses 2 calls total.
"""
from __future__ import annotations

import logging
import os
import re
import time
from datetime import date, datetime, timedelta
from typing import Any

import httpx

logger = logging.getLogger(__name__)

FMP_BASE = "https://financialmodelingprep.com/api/v4"
FMP_SENATE_URL = f"{FMP_BASE}/senate-trading"
FMP_HOUSE_URL = f"{FMP_BASE}/senate-disclosure"

# 24-hour in-memory cache so manual "Fetch Now" doesn't burn quota
_cache: dict[str, tuple[float, list]] = {}
_CACHE_TTL = 86_400  # 24 hours

AMOUNT_MAP = {
    "$1,001 - $15,000":    (100100, 1500000),
    "$15,001 - $50,000":   (1500100, 5000000),
    "$50,001 - $100,000":  (5000100, 10000000),
    "$100,001 - $250,000": (10000100, 25000000),
    "$250,001 - $500,000": (25000100, 50000000),
    "$500,001 - $1,000,000": (50000100, 100000000),
    "$1,000,001 - $5,000,000": (100000100, 500000000),
    "$5,000,001 - $25,000,000": (500000100, 2500000000),
    "$25,000,001 - $50,000,000": (2500000100, 5000000000),
}


def _parse_amount(amount_str: str | None) -> tuple[int | None, int | None]:
    if not amount_str:
        return None, None
    for k, v in AMOUNT_MAP.items():
        if k.lower() == amount_str.lower():
            return v
    m = re.search(r"[\$]?([\d,]+)", amount_str)
    if m:
        val = int(m.group(1).replace(",", "")) * 100
        return val, None
    return None, None


def _parse_date(val: Any) -> date | None:
    if not val:
        return None
    if isinstance(val, (date, datetime)):
        return val.date() if isinstance(val, datetime) else val
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(str(val).strip()[:19], fmt).date()
        except ValueError:
            continue
    return None


def _normalize_transaction_type(raw: str | None) -> str:
    if not raw:
        return "unknown"
    r = raw.lower().strip()
    if "purchase" in r or "buy" in r:
        return "purchase"
    if "sale" in r or "sell" in r:
        return "sale"
    if "exchange" in r:
        return "exchange"
    return r


def _build_source_id(chamber: str, row: dict) -> str:
    first = (row.get("firstName") or "").strip()
    last = (row.get("lastName") or "").strip()
    name = f"{first} {last}".strip()
    ticker = row.get("symbol") or ""
    tx_date = str(row.get("transactionDate") or "")
    tx_type = str(row.get("type") or "")
    amount = str(row.get("amount") or "")
    return f"fmp:{chamber}:{name}:{ticker}:{tx_date}:{tx_type}:{amount}"


async def _fetch_fmp_feed(url: str, api_key: str, cache_key: str, timeout: int = 30) -> list[dict]:
    """Fetch one FMP feed with 24-hour cache."""
    cached = _cache.get(cache_key)
    if cached and time.time() - cached[0] < _CACHE_TTL:
        logger.debug("[congress-fmp] cache hit for %s (%d rows)", cache_key, len(cached[1]))
        return cached[1]

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        resp = await client.get(url, params={"apikey": api_key}, headers={"Accept": "application/json"})
        resp.raise_for_status()
        data = resp.json()

    if not isinstance(data, list):
        data = data.get("data") or list(data.values())[0] if isinstance(data, dict) else []

    _cache[cache_key] = (time.time(), data)
    logger.info("[congress-fmp] fetched %s: %d rows", cache_key, len(data))
    return data


async def fetch_fmp_congress(timeout: int = 30) -> list[dict]:
    """Fetch and normalize congressional trades from FMP (Senate + House)."""
    api_key = os.environ.get("FMP_API_KEY", "")
    if not api_key:
        raise RuntimeError("FMP_API_KEY environment variable is not set — sign up free at financialmodelingprep.com/register")

    rows: list[dict] = []

    sources = [
        (FMP_SENATE_URL, "S", "fmp_senate"),
        (FMP_HOUSE_URL, "H", "fmp_house"),
    ]

    for url, chamber, cache_key in sources:
        try:
            raw_rows = await _fetch_fmp_feed(url, api_key, cache_key, timeout)
        except Exception as exc:
            logger.warning("[congress-fmp] %s failed: %s", cache_key, exc)
            continue

        for row in raw_rows:
            if not isinstance(row, dict):
                continue

            first = (row.get("firstName") or "").strip()
            last = (row.get("lastName") or "").strip()
            name = f"{first} {last}".strip() or (row.get("office") or "").strip()
            ticker = (row.get("symbol") or "").strip().upper() or None
            tx_type_raw = row.get("type") or ""
            amount_raw = row.get("amount") or ""
            tx_date = _parse_date(row.get("transactionDate"))
            disc_date = _parse_date(row.get("dateReceived") or row.get("dateRecieved"))
            asset_desc = ((row.get("assetDescription") or row.get("comment") or "")[:500]) or None
            lower, upper = _parse_amount(amount_raw)

            if not name or not tx_date:
                continue

            rows.append({
                "member_name": name,
                "party": None,  # FMP does not include party affiliation
                "chamber": chamber,
                "state": None,
                "ticker": ticker,
                "asset_description": asset_desc,
                "transaction_type": _normalize_transaction_type(tx_type_raw),
                "amount_range": amount_raw[:50] if amount_raw else None,
                "amount_lower_cents": lower,
                "amount_upper_cents": upper,
                "transaction_date": tx_date,
                "disclosure_date": disc_date,
                "source": "fmp",
                "source_id": _build_source_id(chamber, row),
            })

    return rows


async def fetch_and_upsert_congress(db, days_back: int = 365) -> dict:
    """Main entry point: fetch from FMP, upsert into DB, return stats."""
    from app.db.models.smart_money import SmartMoneyCongressTrade

    cutoff = date.today() - timedelta(days=days_back)
    total_new = 0
    total_skipped = 0
    errors = []

    try:
        rows = await fetch_fmp_congress()
        for r in rows:
            if r["transaction_date"] and r["transaction_date"] < cutoff:
                continue
            existing = db.query(SmartMoneyCongressTrade).filter_by(
                source=r["source"], source_id=r["source_id"]
            ).first()
            if existing:
                total_skipped += 1
                continue
            db.add(SmartMoneyCongressTrade(**r))
            total_new += 1
        db.commit()
        logger.info("[congress] fmp: %d new, %d skipped", total_new, total_skipped)
    except Exception as e:
        errors.append(f"fmp: {e}")
        db.rollback()
        logger.error("[congress] fmp fetch failed: %s", e, exc_info=True)

    return {"new": total_new, "skipped": total_skipped, "errors": errors}


def get_recent_congress(db, limit: int = 50, offset: int = 0,
                        ticker: str | None = None, party: str | None = None,
                        chamber: str | None = None, days: int = 30,
                        min_amount_cents: int | None = None) -> tuple[list[dict], int]:
    """Query smart_money_congress with optional filters. Returns (rows, total_count)."""
    from app.db.models.smart_money import SmartMoneyCongressTrade

    q = db.query(SmartMoneyCongressTrade)
    if days:
        cutoff = date.today() - timedelta(days=days)
        q = q.filter(SmartMoneyCongressTrade.transaction_date >= cutoff)
    if ticker:
        q = q.filter(SmartMoneyCongressTrade.ticker == ticker.upper())
    if party:
        q = q.filter(SmartMoneyCongressTrade.party == party.upper()[:1])
    if chamber:
        q = q.filter(SmartMoneyCongressTrade.chamber == chamber.upper()[:1])
    if min_amount_cents:
        q = q.filter(SmartMoneyCongressTrade.amount_lower_cents >= min_amount_cents)

    total = q.count()
    rows = q.order_by(SmartMoneyCongressTrade.transaction_date.desc()).offset(offset).limit(limit).all()

    def _row_to_dict(r):
        return {
            "id": r.id,
            "member_name": r.member_name,
            "party": r.party,
            "chamber": r.chamber,
            "state": r.state,
            "ticker": r.ticker,
            "asset_description": r.asset_description,
            "transaction_type": r.transaction_type,
            "amount_range": r.amount_range,
            "amount_lower_cents": r.amount_lower_cents,
            "amount_upper_cents": r.amount_upper_cents,
            "transaction_date": r.transaction_date.isoformat() if r.transaction_date else None,
            "disclosure_date": r.disclosure_date.isoformat() if r.disclosure_date else None,
            "disclosure_delay_days": (
                (r.disclosure_date - r.transaction_date).days
                if r.disclosure_date and r.transaction_date else None
            ),
            "source": r.source,
            "source_url": "https://financialmodelingprep.com/financial-summaries/congress-trading",
        }

    return [_row_to_dict(r) for r in rows], total
