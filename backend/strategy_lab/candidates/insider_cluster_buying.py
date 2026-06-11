"""
CANDIDATE — not scheduled. Graduate manually after paper-shadow tracking validates performance.

Strategy: SEC Form 4 Insider Cluster Buying
Academic ref: Lakonishok & Lee (2001), "Are Insider Trades Informative?", Review of Financial Studies
Also: Cohen, Malloy & Pomorski (2012), "Decoding Inside Information", Journal of Finance
Also: Jeng, Metrick & Zeckhauser (2003), "Pure Profits: Where Have All the Gains Gone?", RES

Data source: SEC EDGAR (free, no API key required)
Scan cadence when live: Daily at 8:00 AM ET (add to scheduler manually at graduation)

GRADUATION CHECKLIST:
  - [ ] Paper-shadow for minimum 60 days, 30+ trades
  - [ ] Validate vs. actual EDGAR data (not just smoke-test)
  - [ ] Add proper SEC rate limiting (max 10 req/sec)
  - [ ] Wire real positions table lookup (replace module-level set)
  - [ ] Confirm earnings blackout via real calendar integration
"""
from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import List
from urllib.request import Request, urlopen
from urllib.error import URLError

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "insider_cluster_buying"

CANDIDATE_CONFIG = {
    "name": "insider_cluster_buying",
    "asset_class": "equity",
    "style": "event_driven",
    "data_source": "sec_edgar_form_4",
    "expected_signal_rate": "5-15 per week",
    "expected_sharpe": "0.8-1.3",
    "academic_refs": [
        "Lakonishok & Lee (2001), RFS",
        "Cohen, Malloy & Pomorski (2012), JoF",
        "Jeng, Metrick & Zeckhauser (2003), RES",
    ],
    "promotion_minimum_paper_trades": 30,
    "promotion_minimum_days_observed": 60,
}

# --- Lookback / clustering filters ---
cluster_lookback_days = 30
min_distinct_insiders = 3
min_transaction_usd = 50_000
cluster_total_min_usd = 500_000

# --- Quality / trend filters ---
trend_filter_window = 200
min_price = 5.0
min_adv_usd = 1_000_000
earnings_blackout_days = 7

# --- Sizing ---
base_position_size_pct = 0.005
high_conviction_size_pct = 0.015
max_concurrent_positions = 10

# --- Exit parameters ---
hold_days_max = 60
take_profit_pct = 0.20
hard_stop_pct = 0.10
insider_sale_signal_count = 2
insider_sale_lookback_days = 14

# --- EDGAR constants ---
EDGAR_USER_AGENT = "BMG Capital paper@bmgcapital.com"
EDGAR_RATE_LIMIT_PER_SEC = 10
EDGAR_CACHE_TTL_SECONDS = 86400  # 24h

# --- Module-level state (in-process only; reset on restart) ---
_FORM4_CACHE: dict = {}          # {date_str: (fetched_at, [forms])}
_OPEN_POSITIONS: set = set()     # symbols currently held
_POSITION_ENTRY_DATES: dict = {} # {symbol: datetime}


# ---------------------------------------------------------------------------
# EDGAR helpers
# ---------------------------------------------------------------------------

def _edgar_get(url: str) -> bytes | None:
    """GET a URL from EDGAR with the required User-Agent header."""
    try:
        req = Request(url, headers={"User-Agent": EDGAR_USER_AGENT})
        with urlopen(req, timeout=15) as resp:
            return resp.read()
    except URLError as exc:
        logger.warning("EDGAR fetch failed for %s: %s", url, exc)
        return None


def _get_insider_role(relationship_el: ET.Element | None) -> int:
    """
    Return a role priority integer from a <reportingOwnerRelationship> element.
      1 = C-suite (CEO / CFO / President / etc.)
      2 = Board director
      3 = Officer (other named officer)
      4 = 10%+ holder
      5 = Other / unknown
    """
    if relationship_el is None:
        return 5

    def _flag(tag: str) -> bool:
        el = relationship_el.find(tag)
        return el is not None and (el.text or "").strip() == "1"

    if _flag("isCEO") or _flag("isCFO") or _flag("isPresident"):
        return 1
    if _flag("isDirector"):
        return 2
    if _flag("isOfficer"):
        return 3
    if _flag("isTenPercentOwner"):
        return 4
    return 5


def _parse_form4_xml(xml_bytes: bytes, filing_date: str) -> list[dict]:
    """Parse a Form 4 XML document and return a list of transaction records."""
    records: list[dict] = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        logger.warning("Form 4 XML parse error: %s", exc)
        return records

    symbol_el = root.find(".//issuerTradingSymbol")
    symbol = (symbol_el.text or "").strip().upper() if symbol_el is not None else ""
    if not symbol:
        return records

    owner_name_el = root.find(".//reportingOwnerName")
    insider_name = (owner_name_el.text or "").strip() if owner_name_el is not None else "Unknown"

    relationship_el = root.find(".//reportingOwnerRelationship")
    role = _get_insider_role(relationship_el)

    for txn in root.findall(".//nonDerivativeTransaction"):
        code_el = txn.find("transactionCoding/transactionCode")
        shares_el = txn.find("transactionAmounts/transactionShares/value")
        price_el = txn.find("transactionAmounts/transactionPricePerShare/value")
        if code_el is None or shares_el is None or price_el is None:
            continue
        try:
            shares = float(shares_el.text or 0)
            price = float(price_el.text or 0)
        except ValueError:
            continue
        records.append({
            "symbol": symbol,
            "insider_name": insider_name,
            "role": role,
            "transaction_code": (code_el.text or "").strip(),
            "shares": shares,
            "price_per_share": price,
            "transaction_value": shares * price,
            "filing_date": filing_date,
        })
    return records


def _fetch_recent_form4s(days: int = 30) -> list[dict]:
    """
    Pull Form 4 filings from SEC EDGAR atom feed and parse each filing's XML.
    Results are cached for EDGAR_CACHE_TTL_SECONDS.
    Returns a flat list of transaction dicts on success, [] on any failure.
    """
    cache_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if cache_key in _FORM4_CACHE:
        fetched_at, cached = _FORM4_CACHE[cache_key]
        age = (datetime.now(timezone.utc) - fetched_at).total_seconds()
        if age < EDGAR_CACHE_TTL_SECONDS:
            return cached

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    atom_url = (
        "https://www.sec.gov/cgi-bin/browse-edgar"
        "?action=getcurrent&type=4&output=atom&start=0&count=40"
    )
    atom_bytes = _edgar_get(atom_url)
    if not atom_bytes:
        return []

    try:
        feed = ET.fromstring(atom_bytes)
    except ET.ParseError as exc:
        logger.warning("EDGAR atom feed parse error: %s", exc)
        return []

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entries = feed.findall("atom:entry", ns)

    all_transactions: list[dict] = []
    for entry in entries:
        updated_el = entry.find("atom:updated", ns)
        if updated_el is not None:
            try:
                filing_dt = datetime.fromisoformat(
                    (updated_el.text or "").replace("Z", "+00:00")
                )
                if filing_dt < cutoff:
                    continue
                filing_date = filing_dt.strftime("%Y-%m-%d")
            except ValueError:
                filing_date = "unknown"
        else:
            filing_date = "unknown"

        link_el = entry.find("atom:link", ns)
        if link_el is None:
            continue
        index_url = link_el.get("href", "")
        if not index_url:
            continue

        time.sleep(0.1)  # stay well under 10 req/sec per EDGAR ToS
        index_bytes = _edgar_get(index_url)
        if not index_bytes:
            continue

        # Find the Form 4 XML link in the filing index (plain HTML/text)
        # EDGAR index pages list files; look for the .xml that starts with form4 / 0000
        index_text = index_bytes.decode("utf-8", errors="replace")
        form4_xml_url: str | None = None
        for line in index_text.splitlines():
            if ".xml" in line.lower() and "form4" not in line.lower():
                # Typical pattern: <a href="/Archives/edgar/data/.../0000....xml">
                import re
                match = re.search(r'href="(/Archives/edgar/data/[^"]+\.xml)"', line, re.IGNORECASE)
                if match:
                    form4_xml_url = "https://www.sec.gov" + match.group(1)
                    break
        if not form4_xml_url:
            # Fallback: look for any xml href in the index
            import re
            match = re.search(
                r'href="(/Archives/edgar/data/[^"]+\.xml)"', index_text, re.IGNORECASE
            )
            if match:
                form4_xml_url = "https://www.sec.gov" + match.group(1)

        if not form4_xml_url:
            continue

        time.sleep(0.1)
        xml_bytes = _edgar_get(form4_xml_url)
        if not xml_bytes:
            continue

        records = _parse_form4_xml(xml_bytes, filing_date)
        all_transactions.extend(records)

    _FORM4_CACHE[cache_key] = (datetime.now(timezone.utc), all_transactions)
    return all_transactions


# ---------------------------------------------------------------------------
# Conviction scoring
# ---------------------------------------------------------------------------

def _compute_cluster_conviction(transactions: list[dict]) -> int:
    """
    Score a cluster of buy transactions for a single symbol.
    Returns -1 if the cluster doesn't meet minimum thresholds (no signal).
    """
    total_usd = sum(t["transaction_value"] for t in transactions)
    distinct_insiders = len({t["insider_name"] for t in transactions})

    if distinct_insiders < min_distinct_insiders:
        return -1

    score = 0
    if total_usd > 500_000:
        score += 1
    if total_usd > 1_000_000:
        score += 2  # additional (cumulative with above)
    if any(t["role"] == 1 for t in transactions):
        score += 1
    if any(t["role"] == 2 for t in transactions):
        score += 1
    return score


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def generate_signals(
    bars: dict,
    profile_config: dict,
    regime: dict,
) -> List[Signal]:
    """
    Generate buy signals for stocks showing insider cluster buying activity,
    and exit signals for time-stopped or insider-reversed positions.
    """
    # Step 1: fetch Form 4 filings
    all_forms = _fetch_recent_form4s(days=cluster_lookback_days)

    # Step 2: filter to open-market purchases above the minimum size
    buys = [
        t for t in all_forms
        if t["transaction_code"] == "P" and t["transaction_value"] >= min_transaction_usd
    ]

    # Step 3: group by symbol → compute conviction
    by_symbol: dict[str, list[dict]] = {}
    for txn in buys:
        by_symbol.setdefault(txn["symbol"], []).append(txn)

    out: List[Signal] = []

    # Step 4: entry signals
    for symbol, cluster in by_symbol.items():
        conviction = _compute_cluster_conviction(cluster)
        if conviction < 0:
            continue

        # Trend filter
        if symbol in bars:
            bar_list = bars[symbol]
            closes = [float(b.get("c", 0)) for b in bar_list]
            if len(closes) >= trend_filter_window:
                sma200 = sum(closes[-trend_filter_window:]) / trend_filter_window
                last_close = closes[-1]
                if last_close <= sma200:
                    continue
                if last_close < min_price:
                    continue

        # Earnings blackout (optional safety layer)
        try:
            from app.services.blackout_check import BlackoutCheck
            if BlackoutCheck.is_blacked_out(symbol):
                continue
        except ImportError:
            pass  # if safety layer not available, skip this check

        # Capacity check
        if len(_OPEN_POSITIONS) >= max_concurrent_positions:
            break

        # Size hint by conviction tier
        if conviction >= 3:
            size_hint = high_conviction_size_pct
        elif conviction >= 2:
            size_hint = base_position_size_pct * 2
        else:
            size_hint = base_position_size_pct

        confidence = min(0.95, 0.60 + conviction * 0.05)
        reason = (
            f"insider_cluster_{symbol}_{conviction}c_{len(cluster)}insiders"
        )

        out.append(Signal(
            symbol=symbol,
            side="buy",
            confidence=confidence,
            size_hint=size_hint,
            reason=reason,
            strategy=STRATEGY_NAME,
        ))
        _OPEN_POSITIONS.add(symbol)
        if symbol not in _POSITION_ENTRY_DATES:
            _POSITION_ENTRY_DATES[symbol] = datetime.now(timezone.utc)

    # Step 5: exit signals
    now = datetime.now(timezone.utc)

    # Time stop
    for symbol in list(_OPEN_POSITIONS):
        entry_dt = _POSITION_ENTRY_DATES.get(symbol)
        if entry_dt is not None:
            held_days = (now - entry_dt).days
            if held_days >= hold_days_max:
                out.append(Signal(
                    symbol=symbol,
                    side="sell",
                    confidence=0.90,
                    size_hint=1.0,
                    reason="insider_cluster_exit_time_stop",
                    strategy=STRATEGY_NAME,
                ))
                _OPEN_POSITIONS.discard(symbol)
                _POSITION_ENTRY_DATES.pop(symbol, None)

    # Insider reversal: 2+ insiders sold the same symbol in last N days
    sale_cutoff = now - timedelta(days=insider_sale_lookback_days)
    sales = [
        t for t in all_forms
        if t["transaction_code"] == "S"
        and t["symbol"] in _OPEN_POSITIONS
    ]
    sale_insiders_by_symbol: dict[str, set] = {}
    for txn in sales:
        try:
            filing_dt = datetime.strptime(txn["filing_date"], "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            continue
        if filing_dt >= sale_cutoff:
            sale_insiders_by_symbol.setdefault(txn["symbol"], set()).add(
                txn["insider_name"]
            )

    for symbol, sellers in sale_insiders_by_symbol.items():
        if len(sellers) >= insider_sale_signal_count:
            out.append(Signal(
                symbol=symbol,
                side="sell",
                confidence=0.85,
                size_hint=1.0,
                reason="insider_cluster_exit_insider_sell",
                strategy=STRATEGY_NAME,
            ))
            _OPEN_POSITIONS.discard(symbol)
            _POSITION_ENTRY_DATES.pop(symbol, None)

    return out
