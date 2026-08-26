"""Insider enrichment — per-ticker insider detail from openinsider.com.

MVP foundation for the Ali/Hirshleifer (2017) opportunistic-insider signal.
The full paper requires:
  1. Per-insider CIK persistence across years
  2. Pre-QEA trade profitability computation (5-day CAR around next earnings date)
  3. Annual quintile re-ranking of insiders by average pre-QEA profit
  4. Live classification of new trades by top-quintile insiders

This MVP-lite ships steps 1 and — via LLM reasoning at hunt time — a proxy
for step 4 without steps 2-3. It:
  - Scrapes the openinsider per-ticker detail page (public HTML)
  - Extracts each recent insider trade with name + role
  - Returns structured JSON: [{name, role, transaction_date, shares, price, value_usd}]
  - Claude Sonnet uses this in the hunter prompt to reason about "3 CEOs buying"
    vs "5 random 10% owners buying" — a soft proxy for the opportunistic-insider
    quality distinction

Follow-up (documented for later): compute the full pre-QEA-profitability metric
per Ali/Hirshleifer §3.1. Needs Robinhood earnings-date history + Alpaca prices
+ per-insider CIK tracking across time.
"""
from __future__ import annotations

import logging
import re
import time
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_OI_BASE = "http://openinsider.com"
_CACHE: Dict[str, tuple] = {}  # symbol -> (rows, ts)
_CACHE_TTL_SEC = 6 * 3600  # 6 hours


def _fetch(url: str, timeout: int = 20) -> Optional[str]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (BMG Confluence Hunter)"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        logger.warning("[insider_enrichment] fetch failed %s: %s", url, e)
        return None


def _parse_insider_trades(html: str, max_rows: int = 20) -> List[Dict[str, Any]]:
    """Parse the per-ticker openinsider page (e.g., openinsider.com/HOG).
    Returns most-recent-first list of insider trades with name + role.

    Layout (verified 2026-08-26): rows in <table class="tinytable">, columns:
    0=X flag, 1=filing_date, 2=trade_date, 3=ticker, 4=insider_name, 5=role,
    6=transaction_type, 7=price, 8=qty, 9=owned, 10=dOwn, 11=value.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        logger.warning("[insider_enrichment] BeautifulSoup not available")
        return []

    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="tinytable")
    if table is None:
        return []
    out: List[Dict[str, Any]] = []
    tbody = table.find("tbody") or table
    for tr in tbody.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 12:
            continue
        try:
            trade_date = tds[2].get_text(strip=True)
            insider_name = tds[4].get_text(strip=True)
            role = tds[5].get_text(strip=True)
            ttype = tds[6].get_text(strip=True)
            price = float(tds[7].get_text(strip=True).replace("$", "").replace(",", ""))
            qty_str = tds[8].get_text(strip=True).replace("+", "").replace(",", "")
            qty = int(qty_str) if qty_str.lstrip("-").isdigit() else 0
            value_str = tds[11].get_text(strip=True).replace("+", "").replace("$", "").replace(",", "")
            value = int(value_str) if value_str.lstrip("-").isdigit() else 0
        except (ValueError, IndexError):
            continue
        # Only P-Purchase and S-Sale entries
        if "Purchase" not in ttype and "Sale" not in ttype:
            continue
        out.append({
            "trade_date": trade_date,
            "insider_name": insider_name,
            "role": role,
            "transaction_type": "P" if "Purchase" in ttype else "S",
            "price": price,
            "qty": qty,
            "value_usd": value,
        })
        if len(out) >= max_rows:
            break
    return out


def get_insider_detail(symbol: str, use_cache: bool = True, max_rows: int = 20) -> List[Dict[str, Any]]:
    """Get recent insider trades for one ticker with name + role.
    Returns list ordered most-recent-first."""
    symbol = symbol.upper().strip()
    now = time.time()
    if use_cache and symbol in _CACHE:
        val, ts = _CACHE[symbol]
        if now - ts < _CACHE_TTL_SEC:
            return val

    html = _fetch(f"{_OI_BASE}/{symbol}")
    if not html:
        return []
    rows = _parse_insider_trades(html, max_rows=max_rows)
    _CACHE[symbol] = (rows, now)
    return rows


def summarize_for_prompt(rows: List[Dict[str, Any]], max_show: int = 10) -> str:
    """Format insider trade rows for LLM prompt injection.
    Emphasizes senior-role trades (CEO/CFO/Chairman) since Ali/Hirshleifer's
    opportunistic-insider concept overweights operating-executive trades."""
    if not rows:
        return "no recent insider detail available"

    senior_keywords = ["ceo", "cfo", "chairman", "president", "coo", "founder"]

    def is_senior(role: str) -> bool:
        r = role.lower()
        return any(k in r for k in senior_keywords)

    lines: List[str] = []
    for r in rows[:max_show]:
        side = "BUY" if r["transaction_type"] == "P" else "SELL"
        tag = "★" if is_senior(r["role"]) else " "
        lines.append(
            f"{tag} {r['trade_date']} {side} {r['insider_name'][:28]:28s} ({r['role'][:22]:22s}) "
            f"{r['qty']:>7,} @ ${r['price']:>7.2f} = ${r['value_usd']:>10,}"
        )
    return "\n".join(lines)
