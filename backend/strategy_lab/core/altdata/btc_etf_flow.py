"""
BTC ETF Flow Signal — Farside Investors daily flow scraper.

Scrapes https://farside.co.uk/bitcoin-etf-flow-all-data/ for BTC spot ETF
daily inflow/outflow data. Parses the "Total" column across tickers to compute
a 7-day rolling net flow signal and consecutive streak direction.

Used by crypto_signal_aggregator as a size multiplier on top of cycle phase.
Cache TTL: 4 hours (data updates once per trading day).
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 14400  # 4 hours

_cache: dict = {
    "result": None,
    "fetched_at": 0.0,
}

_NEUTRAL_RESULT: dict = {
    "signal": "neutral",
    "score": 50.0,
    "total_7d_flow_musd": 0.0,
    "streak_days": 0,
    "streak_direction": "inflow",
    "size_multiplier": 1.0,
}

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_FARSIDE_URL = "https://farside.co.uk/bitcoin-etf-flow-all-data/"


def _parse_flow_value(raw: str) -> Optional[float]:
    """
    Parse Farside table cell value into a float (millions USD).
    Handles: "-", "0", "$500.3", "500.3", "(200)" (negative).
    Returns None if unparseable.
    """
    if not isinstance(raw, str):
        return None
    s = raw.strip().replace(",", "")
    if s in ("-", "", "n/a", "N/A"):
        return None
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative = True
        s = s[1:-1]
    s = s.lstrip("$").strip()
    try:
        value = float(s)
        return -value if negative else value
    except ValueError:
        return None


def _scrape_farside() -> list[float]:
    """
    Scrape Farside ETF flow table. Returns list of daily total flows (USD M),
    most recent last. Up to last 10 trading days.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        logger.warning("[btc_etf_flow] beautifulsoup4 not installed; cannot scrape Farside")
        return []

    try:
        headers = {"User-Agent": _USER_AGENT}
        resp = requests.get(_FARSIDE_URL, headers=headers, timeout=15)
        if resp.status_code != 200:
            logger.warning("[btc_etf_flow] Farside returned HTTP %d", resp.status_code)
            return []

        soup = BeautifulSoup(resp.text, "html.parser")

        # Find the main ETF flow table — it's typically the first large table
        tables = soup.find_all("table")
        if not tables:
            logger.warning("[btc_etf_flow] No tables found on Farside page")
            return []

        # Use the largest table (most rows) as the primary data table
        main_table = max(tables, key=lambda t: len(t.find_all("tr")))
        rows = main_table.find_all("tr")

        if len(rows) < 3:
            logger.warning("[btc_etf_flow] Farside table has too few rows: %d", len(rows))
            return []

        # Find "Total" column index from header row
        header_row = rows[0]
        headers_text = [th.get_text(strip=True).lower() for th in header_row.find_all(["th", "td"])]
        total_col_idx = None
        for i, h in enumerate(headers_text):
            if "total" in h:
                total_col_idx = i
                break

        if total_col_idx is None:
            # Try last column as Total
            total_col_idx = len(headers_text) - 1
            logger.debug("[btc_etf_flow] 'Total' column not found in headers; using last column")

        # Extract daily totals from data rows (skip header rows)
        daily_flows: list[float] = []
        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) <= total_col_idx:
                continue
            raw_val = cells[total_col_idx].get_text(strip=True)
            value = _parse_flow_value(raw_val)
            if value is not None:
                daily_flows.append(value)

        # Return last 10 trading days, most recent last
        return daily_flows[-10:] if len(daily_flows) >= 2 else daily_flows

    except Exception as exc:
        logger.warning("[btc_etf_flow] Farside scrape failed: %s", exc)
        return []


def _compute_streak(flows: list[float]) -> tuple[int, str]:
    """Compute consecutive streak length and direction from most recent flows."""
    if not flows:
        return 0, "inflow"
    direction = "inflow" if flows[-1] >= 0 else "outflow"
    streak = 0
    for f in reversed(flows):
        current_dir = "inflow" if f >= 0 else "outflow"
        if current_dir == direction:
            streak += 1
        else:
            break
    return streak, direction


def _classify_signal(total_7d: float, streak: int, direction: str) -> tuple[str, float, float]:
    """Returns (signal_label, score_0_100, size_multiplier)."""
    if streak >= 3 and direction == "inflow" and total_7d > 300:
        return "strong_bullish", 85.0, 1.3
    if total_7d > 100:
        return "bullish", 70.0, 1.1
    if total_7d >= -100:
        return "neutral", 50.0, 1.0
    if streak >= 3 and direction == "outflow" and total_7d < -300:
        return "strong_bearish", 15.0, 0.7
    return "bearish", 30.0, 0.9


def get_btc_etf_flow_signal() -> dict:
    """
    Fetch and classify BTC ETF daily flow data from Farside Investors.

    Returns
    -------
    dict with keys:
        signal           : "strong_bullish"|"bullish"|"neutral"|"bearish"|"strong_bearish"
        score            : float 0-100
        total_7d_flow_musd: float (net $ millions over last 7 trading days)
        streak_days      : int
        streak_direction : "inflow"|"outflow"
        size_multiplier  : float 0.7-1.3
    On failure: neutral defaults + "error" key.
    """
    now_ts = time.monotonic()

    if _cache["result"] is not None and (now_ts - _cache["fetched_at"]) < _CACHE_TTL_SECONDS:
        return _cache["result"]

    try:
        flows = _scrape_farside()

        if not flows:
            logger.warning("[btc_etf_flow] No flow data scraped; returning neutral")
            result = dict(_NEUTRAL_RESULT)
            _cache["result"] = result
            _cache["fetched_at"] = now_ts
            return result

        total_7d = sum(flows[-7:]) if len(flows) >= 7 else sum(flows)
        streak, direction = _compute_streak(flows)
        signal, score, multiplier = _classify_signal(total_7d, streak, direction)

        result = {
            "signal": signal,
            "score": score,
            "total_7d_flow_musd": round(total_7d, 2),
            "streak_days": streak,
            "streak_direction": direction,
            "size_multiplier": multiplier,
        }

        _cache["result"] = result
        _cache["fetched_at"] = now_ts

        logger.info(
            "[btc_etf_flow] signal=%s 7d_flow=$%.0fM streak=%d(%s) mult=%.2f",
            signal, total_7d, streak, direction, multiplier,
        )
        return result

    except Exception as exc:
        logger.warning("[btc_etf_flow] get_btc_etf_flow_signal failed: %s", exc)
        return {**_NEUTRAL_RESULT, "error": str(exc)}
