"""Factor: Post-Earnings-Announcement Drift (Bernard-Thomas 1989).

Standard PEAD result: stocks that beat earnings estimates continue to
outperform for 60-90 days after the announcement; stocks that miss
continue to underperform. Documented empirical drift ~6-9% per year
in the S&P 500 subset.

Simple retail implementation via yfinance:
  score = (last_close - price_1_day_pre_earnings) / price_1_day_pre_earnings
  filtered by: earnings within last 90 days

Long top decile of positive post-earnings drift.

Reference: Bernard & Thomas 1989 JAR; still robust in smid-caps
per Novy-Marx-Velikov 2023 "Assaying Anomalies" SSRN 4338007.

Params:
    lookback_days: window to detect earnings event (default 90)

Data: yfinance earnings_dates + daily bars.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _pead_score(ticker: str, lookback_days: int) -> Optional[float]:
    try:
        import yfinance as yf  # type: ignore
    except Exception as exc:
        logger.warning("[factor:pead] yfinance import failed: %s", exc)
        return None

    try:
        t = yf.Ticker(ticker)
        edates = t.earnings_dates
        if edates is None or edates.empty:
            return None
        # Most recent earnings date within lookback window
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=lookback_days)
        # earnings_dates index is tz-aware; convert to UTC then compare
        idx = edates.index.tz_convert("UTC") if edates.index.tz is not None else edates.index.tz_localize("UTC")
        eligible = [d for d in idx if cutoff <= d.to_pydatetime() <= now]
        if not eligible:
            return None
        latest_earnings = max(eligible).to_pydatetime()

        end = now
        start = latest_earnings - timedelta(days=5)
        hist = t.history(
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            interval="1d",
            auto_adjust=True,
        )
        if hist is None or hist.empty or len(hist) < 3:
            return None
        # Find close 1 day before earnings, and today's close
        pre_earnings_price = None
        for ts, row in hist.iterrows():
            if ts.to_pydatetime() < latest_earnings:
                pre_earnings_price = float(row["Close"])
        if pre_earnings_price is None or pre_earnings_price <= 0:
            return None
        last_close = float(hist["Close"].iloc[-1])
        return (last_close - pre_earnings_price) / pre_earnings_price
    except Exception as exc:
        logger.debug("[factor:pead] %s failed: %s", ticker, exc)
        return None


def compute(
    symbols: list[str],
    db: Session,
    params: dict,
) -> dict[str, float]:
    """Return {ticker: post_earnings_drift}. Higher = stronger positive drift."""
    lookback = int(params.get("lookback_days", 90))
    scores: dict[str, float] = {}
    for i, sym in enumerate(symbols):
        v = _pead_score(sym, lookback)
        if v is None:
            continue
        scores[sym] = float(v)
        if (i + 1) % 50 == 0:
            logger.warning(
                "[factor:pead] progress %d/%d, scored=%d",
                i + 1, len(symbols), len(scores),
            )
    logger.warning(
        "[factor:pead] done: universe=%d scored=%d",
        len(symbols), len(scores),
    )
    return scores
