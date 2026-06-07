"""
Fetches Congressional stock disclosures from:
- Senate Stock Watcher: https://senatestockwatcher.com/api/v1/all_transactions.json
- House Stock Watcher: https://housestockwatcher.com/api/all_transactions

Both are open-source projects scraping official STOCK Act portals.
Rate limiting: be polite — fetch at most once per hour.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from typing import Any

import httpx

logger = logging.getLogger(__name__)

SOURCES = {
    "senate_stock_watcher": "https://senatestockwatcher.com/api/v1/all_transactions.json",
    "house_stock_watcher": "https://housestockwatcher.com/api/all_transactions",
}

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
    # Try exact match first
    for k, v in AMOUNT_MAP.items():
        if k.lower() == amount_str.lower():
            return v
    # Try regex extraction for "Over $X" patterns
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


def _build_source_id(source: str, row: dict) -> str:
    """Build a dedup key from available fields."""
    name = row.get("representative") or row.get("senator") or row.get("name") or ""
    ticker = row.get("ticker") or ""
    tx_date = str(row.get("transaction_date") or row.get("transactionDate") or "")
    tx_type = str(row.get("type") or row.get("transaction_type") or "")
    amount = str(row.get("amount") or "")
    return f"{source}:{name}:{ticker}:{tx_date}:{tx_type}:{amount}"


async def fetch_congress_transactions(source_key: str, url: str, timeout: int = 30) -> list[dict]:
    """Fetch and normalize transactions from one source."""
    headers = {
        "User-Agent": "BMG Capital app/1.0 (admin@bmgcapital.app)",
        "Accept": "application/json",
    }
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    # Both APIs return a list directly or wrapped in a key
    if isinstance(data, dict):
        transactions = data.get("transactions") or data.get("data") or list(data.values())[0]
    else:
        transactions = data

    rows = []
    for row in transactions:
        if not isinstance(row, dict):
            continue
        # Normalize field names (SSW and HSW have slightly different schemas)
        name = (row.get("representative") or row.get("senator") or
                row.get("name") or row.get("member") or "").strip()
        ticker = (row.get("ticker") or "").strip().upper() or None
        tx_type_raw = row.get("type") or row.get("transaction_type") or row.get("transactionType") or ""
        amount_raw = row.get("amount") or row.get("amount_range") or ""
        tx_date = _parse_date(row.get("transaction_date") or row.get("transactionDate") or row.get("tx_date"))
        disc_date = _parse_date(row.get("disclosure_date") or row.get("disclosureDate"))
        party = (row.get("party") or "").strip()[:1].upper() or None
        state = (row.get("state") or "").strip()[:2].upper() or None
        asset_desc = (row.get("asset_description") or row.get("assetDescription") or
                      row.get("description") or row.get("comment") or "")
        chamber = "S" if source_key == "senate_stock_watcher" else "H"
        lower, upper = _parse_amount(amount_raw)
        source_id = _build_source_id(source_key, row)

        if not name or not tx_date:
            continue

        rows.append({
            "member_name": name,
            "party": party,
            "chamber": chamber,
            "state": state,
            "ticker": ticker,
            "asset_description": asset_desc[:500] if asset_desc else None,
            "transaction_type": _normalize_transaction_type(tx_type_raw),
            "amount_range": amount_raw[:50] if amount_raw else None,
            "amount_lower_cents": lower,
            "amount_upper_cents": upper,
            "transaction_date": tx_date,
            "disclosure_date": disc_date,
            "source": source_key,
            "source_id": source_id,
        })
    return rows


async def fetch_and_upsert_congress(db, days_back: int = 365) -> dict:
    """Main entry point: fetch from both sources, upsert into DB, return stats."""
    from app.db.models.smart_money import SmartMoneyCongressTrade  # import here to avoid circular

    cutoff = date.today() - timedelta(days=days_back)
    total_new = 0
    total_skipped = 0
    errors = []

    for source_key, url in SOURCES.items():
        try:
            rows = await fetch_congress_transactions(source_key, url)
            for r in rows:
                if r["transaction_date"] and r["transaction_date"] < cutoff:
                    continue
                # Upsert: skip if source_id already exists
                existing = db.query(SmartMoneyCongressTrade).filter_by(
                    source=r["source"], source_id=r["source_id"]
                ).first()
                if existing:
                    total_skipped += 1
                    continue
                db.add(SmartMoneyCongressTrade(**r))
                total_new += 1
            db.commit()
            logger.info("[congress] %s: %d new, %d skipped", source_key, total_new, total_skipped)
        except Exception as e:
            errors.append(f"{source_key}: {e}")
            logger.error("[congress] fetch failed for %s: %s", source_key, e, exc_info=True)

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
            "source_url": (
                f"https://senatestockwatcher.com/politician/{r.member_name.lower().replace(' ', '-')}"
                if r.chamber == "S"
                else "https://housestockwatcher.com/api/all_transactions"
            ),
        }

    return [_row_to_dict(r) for r in rows], total
