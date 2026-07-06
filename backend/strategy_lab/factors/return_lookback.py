"""Factor: 12-1 momentum (Jegadeesh-Titman 1993, SSRN 227615).

Score for each ticker:
    return over the 11-month window ending 1 month ago
    = price at (t - 1 month) / price at (t - 13 months) - 1

The 1-month skip filters short-term reversal noise that inverts UMD in
the very short window.

Params:
    months_back:  window length (default 12)
    skip_months:  months to skip at the end (default 1)

Data source: yfinance daily bars. We fetch 400 trading days per ticker,
take the close price at the appropriate offsets.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _fetch_close_at_offset(ticker: str, days_back: int) -> Optional[float]:
    """Return the close price approximately `days_back` trading days ago.

    Uses yfinance history over a window sized to cover days_back + margin,
    then takes the closest-to-target row.
    """
    try:
        import yfinance as yf  # type: ignore
    except Exception as exc:
        logger.warning("[factor:return_lookback] yfinance import failed: %s", exc)
        return None

    end = datetime.now(timezone.utc)
    # Fetch a window 30 calendar days wider than the target so we have data
    # even if the offset day lands on a holiday.
    start = end - timedelta(days=int(days_back * 1.5) + 30)
    try:
        hist = yf.Ticker(ticker).history(
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            interval="1d",
            auto_adjust=True,
        )
    except Exception as exc:
        logger.warning("[factor:return_lookback] %s history fetch failed: %s", ticker, exc)
        return None
    if hist is None or hist.empty:
        return None
    # target index = len(hist) - days_back, clamped
    n = len(hist)
    idx = max(0, n - int(days_back))
    try:
        close = float(hist["Close"].iloc[idx])
    except (KeyError, IndexError, ValueError):
        return None
    return close if close > 0 else None


def compute(
    symbols: list[str],
    db: Session,
    params: dict,
) -> dict[str, float]:
    """Return {ticker: score} where score = price[skip] / price[skip + months_back] - 1.

    Missing data → ticker is skipped (not scored). The runner then treats
    missing scores as "not in universe" so it can't accidentally rank
    tickers whose data feed was down.
    """
    months_back = int(params.get("months_back", 12))
    skip_months = int(params.get("skip_months", 1))
    days_recent = int(skip_months * 21)                  # 1 month ≈ 21 trading days
    days_back = int((months_back + skip_months) * 21)    # end of the 12-month window

    scores: dict[str, float] = {}
    for i, sym in enumerate(symbols):
        # Recent price (t - skip_months)
        recent = _fetch_close_at_offset(sym, days_recent)
        if recent is None:
            continue
        back = _fetch_close_at_offset(sym, days_back)
        if back is None or back <= 0:
            continue
        try:
            r = recent / back - 1.0
            scores[sym] = float(r)
        except (ZeroDivisionError, ValueError):
            continue
        # Coarse progress log every 50 tickers so a slow yfinance fetch is visible.
        if (i + 1) % 50 == 0:
            logger.warning(
                "[factor:return_lookback] progress %d/%d, scored=%d",
                i + 1, len(symbols), len(scores),
            )
    logger.warning(
        "[factor:return_lookback] done: universe=%d scored=%d skipped=%d",
        len(symbols), len(scores), len(symbols) - len(scores),
    )
    return scores
