"""Factor: Cross-sectional crypto momentum (Liu-Tsyvinski-Wu 2022 JoF).

Ranks a crypto universe by trailing 1-week return. Long top decile
of winners.

Published result: crypto momentum factor delivers +2-3%/week per leg,
strongest at 1-4 week lookbacks. Documented in Liu, Tsyvinski, Wu
"Common Risk Factors in Cryptocurrency" (SSRN 3379131 / JoF 2022).

Params:
    lookback_days: window for momentum (default 7)

Data: yfinance for BTC-USD, ETH-USD, etc. (crypto pairs).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _weekly_return(ticker: str, lookback_days: int) -> Optional[float]:
    try:
        import yfinance as yf  # type: ignore
    except Exception as exc:
        logger.warning("[factor:crypto_xs_momentum] yfinance import failed: %s", exc)
        return None

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=lookback_days + 3)
    try:
        hist = yf.Ticker(ticker).history(
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            interval="1d",
            auto_adjust=True,
        )
    except Exception as exc:
        logger.debug("[factor:crypto_xs_momentum] %s fetch failed: %s", ticker, exc)
        return None

    if hist is None or hist.empty or len(hist) < 3:
        return None
    try:
        first = float(hist["Close"].iloc[0])
        last = float(hist["Close"].iloc[-1])
        if first <= 0:
            return None
        return (last / first) - 1.0
    except Exception:
        return None


def compute(
    symbols: list[str],
    db: Session,
    params: dict,
) -> dict[str, float]:
    """Return {ticker: weekly_return}. Higher = stronger recent momentum."""
    lookback = int(params.get("lookback_days", 7))
    scores: dict[str, float] = {}
    for i, sym in enumerate(symbols):
        r = _weekly_return(sym, lookback)
        if r is None:
            continue
        scores[sym] = float(r)
    logger.warning(
        "[factor:crypto_xs_momentum] done: universe=%d scored=%d",
        len(symbols), len(scores),
    )
    return scores
