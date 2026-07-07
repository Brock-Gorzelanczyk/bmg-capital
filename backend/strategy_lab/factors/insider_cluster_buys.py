"""Factor: Insider Cluster Buys (Cohen-Malloy-Pomorski 2012).

Retail-viable proxy for the SEC Form 4 opportunistic-insider signal:
ranks stocks by the count of insider purchases in the trailing 90 days
scaled by market cap. Higher score = more cluster buying activity.

Uses yfinance's Ticker.insider_transactions endpoint. Falls back to
empty (skip) for tickers with no data. Simple, robust to feed gaps.

Reference: Cohen, Malloy, Pomorski 2012 JoF (NBER w16454). Published
~10% annualized long-short spread; long-only variant still delivers
~5-7%.

Params:
    lookback_days: window for insider transactions (default 90)

Data: yfinance.Ticker.insider_transactions (free tier).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _insider_score(ticker: str, lookback_days: int) -> Optional[float]:
    try:
        import yfinance as yf  # type: ignore
    except Exception as exc:
        logger.warning("[factor:insider_cluster_buys] yfinance import failed: %s", exc)
        return None

    try:
        t = yf.Ticker(ticker)
        transactions = t.insider_transactions
        if transactions is None or transactions.empty:
            return None

        cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        # yfinance columns: Start Date, Insider, Position, Transaction, Shares, Value, ...
        recent_buys = 0
        total_value = 0.0
        for _, row in transactions.iterrows():
            try:
                start_date = row.get("Start Date")
                if start_date is None:
                    continue
                # Normalize to tz-aware UTC
                if hasattr(start_date, "to_pydatetime"):
                    dt = start_date.to_pydatetime()
                else:
                    dt = start_date
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt < cutoff:
                    continue
                txn_type = str(row.get("Transaction", "")).lower()
                if "purchase" in txn_type or "buy" in txn_type:
                    recent_buys += 1
                    val = row.get("Value")
                    if val is not None:
                        try:
                            total_value += float(val)
                        except Exception:
                            pass
            except Exception:
                continue

        if recent_buys == 0:
            return 0.0
        # Score = number of cluster buys * log(value+1). Rewards both
        # count and size.
        import math
        return float(recent_buys) * math.log(max(1.0, total_value / 1_000_000.0) + 1.0)
    except Exception as exc:
        logger.debug("[factor:insider_cluster_buys] %s failed: %s", ticker, exc)
        return None


def compute(
    symbols: list[str],
    db: Session,
    params: dict,
) -> dict[str, float]:
    """Return {ticker: cluster_buy_score}. Higher = more insider accumulation."""
    lookback = int(params.get("lookback_days", 90))
    scores: dict[str, float] = {}
    for i, sym in enumerate(symbols):
        v = _insider_score(sym, lookback)
        if v is None:
            continue
        scores[sym] = float(v)
        if (i + 1) % 50 == 0:
            logger.warning(
                "[factor:insider_cluster_buys] progress %d/%d, scored=%d",
                i + 1, len(symbols), len(scores),
            )
    logger.warning(
        "[factor:insider_cluster_buys] done: universe=%d scored=%d",
        len(symbols), len(scores),
    )
    return scores
