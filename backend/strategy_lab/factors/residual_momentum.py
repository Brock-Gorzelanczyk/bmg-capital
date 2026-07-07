"""Factor: Residual Momentum (Blitz-Huij-Martens 2011, SSRN 2319861).

Standard 12-1 momentum uses raw returns. Residual momentum ranks
stocks by their FF3-residual 12-1 returns — meaning momentum
AFTER stripping out market, size, and value factor exposures.

Empirical result: residual momentum has ~2x the Sharpe of raw
momentum and avoids the sharp reversals that make raw momentum
crash (Aug 2007, Q1 2009). Same universe, same rebalance, same
holding period — just cleaner signal.

Simplified implementation for BMG (retail-viable):
Instead of the full FF3 factor model, compute market-model
residuals (regress ticker returns on SPY returns over trailing
12 months), take the alpha + residual return over the last 11
months (skip most recent to avoid short-term reversal, per
standard 12-1 momentum convention).

Reference: BMG-Strategy-Knowledge-Vault-v1.md.

Params:
    lookback_months: total window (default 12)
    skip_months: recent months to skip (default 1)

Data: yfinance daily bars for ticker + SPY over trailing window.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _fetch_returns(ticker: str, days: int) -> Optional[list[float]]:
    """Return daily simple-return series over trailing window."""
    try:
        import yfinance as yf  # type: ignore
    except Exception as exc:
        logger.warning("[factor:residual_momentum] yfinance import failed: %s", exc)
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
        logger.warning("[factor:residual_momentum] %s fetch failed: %s", ticker, exc)
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


def _residual_momentum(
    ticker: str, spy_returns: list[float], lookback: int, skip: int,
) -> Optional[float]:
    """Regress ticker returns on SPY. Return alpha + residual cum return over
    lookback minus skip window.
    """
    r = _fetch_returns(ticker, lookback)
    if r is None or len(r) < 30:
        return None
    # Align series lengths from the tail
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
        beta = cov_xy / var_x
        alpha = mean_y - beta * mean_x
        residuals = [r[i] - alpha - beta * x[i] for i in range(n)]

        # Cumulative residual return over the 12-1 window (skip last `skip`
        # months = last skip*21 trading days).
        skip_days = skip * 21
        eligible = residuals[: n - skip_days] if skip_days < n else residuals
        if len(eligible) < 30:
            return None
        # Compound the residual returns
        cum = 1.0
        for res in eligible:
            cum *= 1.0 + res
        return cum - 1.0
    except Exception:
        return None


def compute(
    symbols: list[str],
    db: Session,
    params: dict,
) -> dict[str, float]:
    """Return {ticker: residual_12m_return}. Higher = stronger residual mom.

    Long top decile = the strongest-residual-momentum names, per
    Blitz-Huij-Martens.
    """
    lookback_months = int(params.get("lookback_months", 12))
    skip_months = int(params.get("skip_months", 1))
    total_days = lookback_months * 21

    # SPY benchmark series — fetched once, reused for every regression.
    spy_returns = _fetch_returns("SPY", total_days)
    if spy_returns is None:
        logger.error(
            "[factor:residual_momentum] SPY benchmark fetch failed — no scores"
        )
        return {}

    scores: dict[str, float] = {}
    for i, sym in enumerate(symbols):
        v = _residual_momentum(sym, spy_returns, total_days, skip_months)
        if v is None:
            continue
        scores[sym] = float(v)
        if (i + 1) % 50 == 0:
            logger.warning(
                "[factor:residual_momentum] progress %d/%d, scored=%d",
                i + 1, len(symbols), len(scores),
            )
    logger.warning(
        "[factor:residual_momentum] done: universe=%d scored=%d skipped=%d",
        len(symbols), len(scores), len(symbols) - len(scores),
    )
    return scores
