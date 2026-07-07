"""Factor: Betting Against Beta (Frazzini-Pedersen 2014, SSRN 2049939).

Standard result: low-beta stocks deliver higher risk-adjusted returns
than high-beta stocks. Frazzini-Pedersen document a leveraged
long-low-beta / short-high-beta portfolio with Sharpe ~0.78 (US 1926-2012).

Long-only retail implementation for BMG: rank universe by
market-model beta over trailing 12 months, long the lowest-beta
decile, equal-weighted. Skip the short leg (retail broker
constraint) — long-only low-beta still captures most of the
BAB premium and works cleanly as a portfolio-rank bot.

Reference: Frazzini, Pedersen "Betting Against Beta" JFE 2014.
  - Long low-β decile alpha: 6-8% ann. unlevered
  - Complements low_volatility factor (uses total vol, not beta)
  - Retail-viable long-only variant

Params:
    lookback_days: rolling window for beta regression (default 252 = 1yr)

Data: yfinance daily bars for ticker + SPY over trailing window.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _fetch_returns(ticker: str, days: int) -> Optional[list[float]]:
    try:
        import yfinance as yf  # type: ignore
    except Exception as exc:
        logger.warning("[factor:bab] yfinance import failed: %s", exc)
        return None

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days + 15)
    try:
        hist = yf.Ticker(ticker).history(
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            interval="1d",
            auto_adjust=True,
        )
    except Exception as exc:
        logger.warning("[factor:bab] %s fetch failed: %s", ticker, exc)
        return None
    if hist is None or hist.empty or len(hist) < days // 2:
        return None
    try:
        closes = hist["Close"].astype(float).values
        rets = [
            (closes[i] / closes[i - 1] - 1.0)
            for i in range(1, len(closes))
            if closes[i - 1] > 0
        ]
        return rets if len(rets) >= 30 else None
    except Exception:
        return None


def _beta(ticker: str, spy_returns: list[float], days: int) -> Optional[float]:
    """OLS slope of ticker returns on SPY returns."""
    r = _fetch_returns(ticker, days)
    if r is None:
        return None
    n = min(len(r), len(spy_returns))
    if n < 30:
        return None
    r = r[-n:]
    x = spy_returns[-n:]

    try:
        mean_x = sum(x) / n
        mean_y = sum(r) / n
        var_x = sum((xi - mean_x) ** 2 for xi in x) / max(1, n - 1)
        cov_xy = sum((x[i] - mean_x) * (r[i] - mean_y) for i in range(n)) / max(1, n - 1)
        if var_x <= 0:
            return None
        return cov_xy / var_x
    except Exception:
        return None


def compute(
    symbols: list[str],
    db: Session,
    params: dict,
) -> dict[str, float]:
    """Return {ticker: -beta}. Higher (less negative) score = lower beta.

    Long top decile = lowest-beta names, per Frazzini-Pedersen
    long-only BAB variant.
    """
    lookback_days = int(params.get("lookback_days", 252))

    spy_returns = _fetch_returns("SPY", lookback_days)
    if spy_returns is None:
        logger.error("[factor:bab] SPY benchmark fetch failed — no scores")
        return {}

    scores: dict[str, float] = {}
    for i, sym in enumerate(symbols):
        b = _beta(sym, spy_returns, lookback_days)
        if b is None:
            continue
        # Negate: low beta becomes high score, so top decile = lowest beta.
        scores[sym] = -float(b)
        if (i + 1) % 50 == 0:
            logger.warning(
                "[factor:bab] progress %d/%d, scored=%d",
                i + 1, len(symbols), len(scores),
            )
    logger.warning(
        "[factor:bab] done: universe=%d scored=%d skipped=%d",
        len(symbols), len(scores), len(symbols) - len(scores),
    )
    return scores
