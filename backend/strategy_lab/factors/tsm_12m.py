"""Factor: Time-Series Momentum (Moskowitz-Ooi-Pedersen 2012, SSRN 1657676).

Score for each ticker: cumulative return over the trailing 12 months.
Higher score = stronger uptrend. Long the top decile.

Classic TSM is per-asset (each asset gets long/short based on its own
sign). Adapted to the portfolio-rank cross-sectional framework: rank
ETFs by 12-month return, long the strongest-trending decile.

Reference: BMG-Strategy-Knowledge-Vault-v1.md.
  - MOP 1985-2009 across 58 liquid assets: Sharpe 1.5+ per asset
  - Fills the "no trend-following" gap in the fleet
  - Works across bonds, commodities, equity, FX
  - Turnover moderate at monthly rebalance
  - Long-only ETF-based implementation is Alpaca-compatible

Params:
    lookback_months: window length in months (default 12)

Data: yfinance daily bars, closing prices at t0 and t-lookback.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _fetch_return(ticker: str, months_back: int) -> Optional[float]:
    try:
        import yfinance as yf  # type: ignore
    except Exception as exc:
        logger.warning("[factor:tsm_12m] yfinance import failed: %s", exc)
        return None

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=int(months_back * 32))  # margin for holidays
    try:
        hist = yf.Ticker(ticker).history(
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            interval="1d",
            auto_adjust=True,
        )
    except Exception as exc:
        logger.warning("[factor:tsm_12m] %s history fetch failed: %s", ticker, exc)
        return None
    if hist is None or hist.empty or len(hist) < 10:
        return None
    try:
        first = float(hist["Close"].iloc[0])
        last = float(hist["Close"].iloc[-1])
        if first <= 0:
            return None
        return (last / first) - 1.0
    except (KeyError, IndexError, ValueError):
        return None


def compute(
    symbols: list[str],
    db: Session,
    params: dict,
) -> dict[str, float]:
    """Return {ticker: 12m_return}. Higher = stronger trend, long top decile."""
    months_back = int(params.get("lookback_months", 12))
    scores: dict[str, float] = {}
    for i, sym in enumerate(symbols):
        r = _fetch_return(sym, months_back)
        if r is None:
            continue
        scores[sym] = float(r)
        if (i + 1) % 20 == 0:
            logger.warning(
                "[factor:tsm_12m] progress %d/%d, scored=%d",
                i + 1, len(symbols), len(scores),
            )
    logger.warning(
        "[factor:tsm_12m] done: universe=%d scored=%d skipped=%d",
        len(symbols), len(scores), len(symbols) - len(scores),
    )
    return scores
