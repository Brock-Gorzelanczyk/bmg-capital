"""
Congress STOCK Act Signal — Weekend 8, Module 21.

Tracks congressional stock disclosures (required under the STOCK Act).
45-day filing lag is the entire tradeable window.

Filter logic:
  - Committee assignment: Intel / Financial Services > rank-and-file
  - Trade size: >$50K (ignore <$1K token trades)
  - Transaction type: purchase only (ignore sales for long signals)

Data: Quiver Quantitative API ($10/mo) or free House/Senate scrape from
      https://disclosures.house.gov and https://efts.senate.gov

Nancy Pelosi strategy: +744% since 2014 vs +242% SPY (Unusual Whales data).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# High-value committee assignments (informationally advantaged)
HIGH_VALUE_COMMITTEES = {
    "House Intelligence Committee",
    "Senate Intelligence Committee",
    "House Financial Services Committee",
    "Senate Banking Committee",
    "House Energy and Commerce Committee",
    "Senate Commerce Committee",
    "House Armed Services Committee",
    "Senate Armed Services Committee",
}

MIN_TRADE_VALUE_USD = 50_000
FILING_LAG_DAYS = 45  # maximum filing deadline


@dataclass
class CongressTrade:
    member_name: str
    party: str              # "D" | "R" | "I"
    chamber: str            # "House" | "Senate"
    committees: list[str]
    symbol: str
    transaction_type: str   # "Purchase" | "Sale"
    transaction_date: datetime
    disclosure_date: datetime
    amount_range: str       # "$50,001 - $100,000" etc.
    amount_min_usd: float
    amount_max_usd: float
    high_value_committee: bool


@dataclass
class CongressSignal:
    symbol: str
    member_name: str
    committee: Optional[str]
    transaction_date: datetime
    disclosure_date: datetime
    amount_range: str
    signal_strength: str    # "high" | "medium" | "low"
    days_since_transaction: int


def _parse_amount_range(range_str: str) -> tuple[float, float]:
    """Parse '$50,001 - $100,000' into (min, max) floats."""
    if not range_str:
        return 0.0, 0.0
    try:
        parts = range_str.replace("$", "").replace(",", "").split("-")
        lo = float(parts[0].strip())
        hi = float(parts[1].strip()) if len(parts) > 1 else lo
        return lo, hi
    except (ValueError, IndexError):
        return 0.0, 0.0


def _fetch_quiver_quant(symbol: str) -> list[CongressTrade]:
    """Fetch congress trades from Quiver Quantitative API."""
    try:
        import requests
        api_key = os.getenv("QUIVER_QUANT_API_KEY", "")
        if not api_key:
            return []

        url = f"https://api.quiverquant.com/beta/live/congresstrading/{symbol}"
        headers = {"Authorization": f"Token {api_key}"}
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code != 200:
            logger.debug("[congress] Quiver error %d for %s", resp.status_code, symbol)
            return []

        trades = []
        for r in resp.json():
            tx_type = r.get("Transaction", "")
            if "Purchase" not in tx_type:
                continue

            amount_range = r.get("Range", "")
            lo, hi = _parse_amount_range(amount_range)
            if hi < MIN_TRADE_VALUE_USD:
                continue

            try:
                tx_date = datetime.strptime(r["TransactionDate"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                disc_date = datetime.strptime(r["ReportDate"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except (KeyError, ValueError):
                continue

            committees = r.get("Committees", []) or []
            if isinstance(committees, str):
                committees = [committees]

            trades.append(CongressTrade(
                member_name=r.get("Representative", "Unknown"),
                party=r.get("Party", ""),
                chamber=r.get("Chamber", "House"),
                committees=committees,
                symbol=symbol,
                transaction_type="Purchase",
                transaction_date=tx_date,
                disclosure_date=disc_date,
                amount_range=amount_range,
                amount_min_usd=lo,
                amount_max_usd=hi,
                high_value_committee=any(c in HIGH_VALUE_COMMITTEES for c in committees),
            ))
        return trades
    except Exception as exc:
        logger.debug("[congress] Quiver error for %s: %s", symbol, exc)
        return []


def score_trade(trade: CongressTrade) -> str:
    """Score a single congress trade signal strength."""
    score = 0
    if trade.high_value_committee:
        score += 2
    if trade.amount_max_usd >= 500_000:
        score += 2
    elif trade.amount_max_usd >= 100_000:
        score += 1
    if trade.chamber == "Senate":
        score += 1  # Senators typically have longer terms + more visibility

    if score >= 4:
        return "high"
    if score >= 2:
        return "medium"
    return "low"


def get_signals(symbol: str) -> list[CongressSignal]:
    """
    Get active congress trade signals for a symbol.
    Only returns trades within the 45-day filing window (still actionable).
    """
    trades = _fetch_quiver_quant(symbol)
    if not trades:
        return []

    now = datetime.now(timezone.utc)
    signals = []

    for trade in trades:
        days_since = (now - trade.transaction_date).days
        # Only surface if within 45-day window
        if days_since > FILING_LAG_DAYS:
            continue

        strength = score_trade(trade)
        top_committee = next(
            (c for c in trade.committees if c in HIGH_VALUE_COMMITTEES),
            trade.committees[0] if trade.committees else None,
        )

        signals.append(CongressSignal(
            symbol=symbol,
            member_name=trade.member_name,
            committee=top_committee,
            transaction_date=trade.transaction_date,
            disclosure_date=trade.disclosure_date,
            amount_range=trade.amount_range,
            signal_strength=strength,
            days_since_transaction=days_since,
        ))
        logger.info(
            "[congress] signal: %s | %s | %s | strength=%s | %dd ago",
            symbol, trade.member_name, top_committee, strength, days_since,
        )

    return signals
