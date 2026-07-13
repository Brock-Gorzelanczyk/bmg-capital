"""Factor: overnight-return momentum.

Source: Lou, Polk & Skouras (2019) "A Tug of War: Overnight Versus Intraday
Expected Returns," JFE 134(1). SSRN https://ssrn.com/abstract=2687977.

Signal:
    score(t) = sum over prior N trading days of (open[i] / close[i-1] - 1)

Only the OVERNIGHT segment of each day's return is used. Intraday returns
(open → close) are discarded — Lou-Polk-Skouras show intraday returns
reverse over the same horizon.

Interpretation: "overnight returns" reflect long-horizon investor pricing
adjustments (via after-hours news + pre-market fills). Persistence of the
signal reflects that these investors trade slowly. Correlation to 12-1 UMD
is < 0.15 — this is a genuinely orthogonal momentum axis.

Rebalance: daily (roll every trading day). Complements our monthly
short_term_momentum and 12-1 UMD PR bots.

Params:
    lookback_days  overnight-return summation window (default 21)

Data source: yfinance daily bars (Open + Close). Free.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _fetch_overnight_score(ticker: str, lookback_days: int) -> Optional[float]:
    try:
        import yfinance as yf  # type: ignore
    except Exception as exc:
        logger.warning("[factor:overnight_momentum] yfinance import failed: %s", exc)
        return None

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=lookback_days * 2 + 20)
    try:
        hist = yf.Ticker(ticker).history(
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            interval="1d",
            auto_adjust=True,
        )
    except Exception as exc:
        logger.debug(
            "[factor:overnight_momentum] %s history fetch failed: %s", ticker, exc,
        )
        return None
    if hist is None or hist.empty or len(hist) < lookback_days + 1:
        return None
    try:
        opens = hist["Open"].tail(lookback_days + 1).to_list()
        closes = hist["Close"].tail(lookback_days + 1).to_list()
    except Exception:
        return None
    if len(opens) < 2 or len(closes) < 2:
        return None

    # For each day i in the window, overnight return is open[i] / close[i-1] - 1.
    # We have (lookback_days+1) days of data → lookback_days pairs.
    total = 0.0
    used = 0
    for i in range(1, len(opens)):
        prev_close = float(closes[i - 1])
        open_i = float(opens[i])
        if prev_close <= 0 or open_i <= 0:
            continue
        total += (open_i / prev_close) - 1.0
        used += 1
    if used == 0:
        return None
    # Return the sum (not mean) so magnitude reflects total overnight drift.
    return float(total)


def compute(
    symbols: list[str],
    db: Session,
    params: dict,
) -> dict[str, float]:
    lookback_days = int(params.get("lookback_days", 21))

    scores: dict[str, float] = {}
    for i, sym in enumerate(symbols):
        s = _fetch_overnight_score(sym, lookback_days)
        if s is None:
            continue
        scores[sym] = s
        if (i + 1) % 50 == 0:
            logger.warning(
                "[factor:overnight_momentum] progress %d/%d, scored=%d",
                i + 1, len(symbols), len(scores),
            )
    logger.warning(
        "[factor:overnight_momentum] done: universe=%d scored=%d",
        len(symbols), len(scores),
    )
    return scores
