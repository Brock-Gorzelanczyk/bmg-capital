"""Factor: Low Volatility (Blitz-van Vliet 2007, Ang-Hodrick-Xing-Zhang 2006).

Score for each ticker: negative of trailing volatility. Ranking descending
puts the LOWEST-volatility names at the top of the decile → long-only
implementation captures the low-vol anomaly without needing to short the
top decile (per vault: long-only variant has better capacity anyway).

Reference: BMG-Strategy-Knowledge-Vault-v1.md Section 1.6.
  - BvV 1986-2006 global: low-vol Sharpe ~0.72 vs market ~0.40
  - Ang et al. differential ~8% annual (short side driving the split)
  - Turnover 40-60% at monthly rebalance
  - Sector-neutralization improves realized-vs-paper Sharpe materially

Params (with defaults matching Ang et al.):
    window_days:  trailing window for std calculation (default 21)

Data: yfinance daily bars. Fetch trailing 3× window_days worth of bars
so we have a real 21-day sample even with holidays/weekends.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _vol_from_yf(ticker: str, window_days: int) -> Optional[float]:
    try:
        import yfinance as yf  # type: ignore
    except Exception as exc:
        logger.warning("[factor:low_volatility] yfinance import failed: %s", exc)
        return None

    end = datetime.now(timezone.utc)
    # Fetch 3x window so we have plenty of trading days even with holidays.
    start = end - timedelta(days=window_days * 3 + 15)
    try:
        hist = yf.Ticker(ticker).history(
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            interval="1d",
            auto_adjust=True,
        )
    except Exception as exc:
        logger.warning("[factor:low_volatility] %s history fetch failed: %s", ticker, exc)
        return None
    if hist is None or hist.empty or len(hist) < window_days:
        return None
    try:
        closes = hist["Close"].astype(float).tail(window_days + 1).values
        # Daily log returns
        rets = [
            (closes[i] / closes[i - 1] - 1.0)
            for i in range(1, len(closes))
            if closes[i - 1] > 0
        ]
        if len(rets) < window_days - 2:
            return None
        # Sample stdev
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / max(1, len(rets) - 1)
        return var ** 0.5
    except Exception:
        return None


def compute(
    symbols: list[str],
    db: Session,
    params: dict,
) -> dict[str, float]:
    """Return {ticker: -vol}. Higher (less negative) score = lower vol.

    Runtime sorts descending, so top decile of a low-vol scorer means
    the LOWEST-vol names. Long-only portfolio-rank convention: long the
    top decile.
    """
    window_days = int(params.get("window_days", 21))
    scores: dict[str, float] = {}
    for i, sym in enumerate(symbols):
        v = _vol_from_yf(sym, window_days)
        if v is None or v <= 0:
            continue
        # Negate: LOW vol becomes HIGH score.
        scores[sym] = -float(v)
        if (i + 1) % 50 == 0:
            logger.warning(
                "[factor:low_volatility] progress %d/%d, scored=%d",
                i + 1, len(symbols), len(scores),
            )
    logger.warning(
        "[factor:low_volatility] done: universe=%d scored=%d skipped=%d",
        len(symbols), len(scores), len(symbols) - len(scores),
    )
    return scores
