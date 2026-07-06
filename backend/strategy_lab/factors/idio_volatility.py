"""Factor: Idiosyncratic Volatility (Ang-Hodrick-Xing-Zhang 2006, SSRN 647981).

Score for each ticker: negative of the standard deviation of daily
residuals from a simple market model (regress ticker returns on SPY
returns over trailing 21 days). Lower residual vol = higher score.
Long the top decile.

Distinct from `low_volatility` factor which uses total volatility.
IVOL isolates the idiosyncratic component after removing market beta.
Ang et al. showed low-IVOL names outperform high-IVOL by 8-12%
annually — a robust cross-section return spread that explains dozens
of other anomalies.

Reference: BMG-Strategy-Knowledge-Vault-v1.md Section 1.10.
  - Ang et al. 1963-2000: differential ~12% annual
  - Explains lottery-stock underperformance
  - Long-only bottom-quintile is retail-viable
  - Turnover moderate at monthly rebalance

Params:
    window_days: rolling window for regression (default 21)

Data: yfinance daily bars for ticker + SPY over trailing window.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _fetch_returns(ticker: str, window_days: int) -> Optional[list[float]]:
    """Return daily log-return series over trailing window."""
    try:
        import yfinance as yf  # type: ignore
    except Exception as exc:
        logger.warning("[factor:idio_volatility] yfinance import failed: %s", exc)
        return None

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=window_days * 2 + 15)
    try:
        hist = yf.Ticker(ticker).history(
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            interval="1d",
            auto_adjust=True,
        )
    except Exception as exc:
        logger.warning("[factor:idio_volatility] %s fetch failed: %s", ticker, exc)
        return None
    if hist is None or hist.empty or len(hist) < window_days:
        return None
    try:
        closes = hist["Close"].astype(float).tail(window_days + 1).values
        rets = [
            (closes[i] / closes[i - 1] - 1.0)
            for i in range(1, len(closes))
            if closes[i - 1] > 0
        ]
        return rets if len(rets) >= window_days - 2 else None
    except Exception:
        return None


def _idio_vol(ticker: str, spy_returns: list[float], window_days: int) -> Optional[float]:
    """Regress ticker returns on SPY returns; return residual std."""
    r = _fetch_returns(ticker, window_days)
    if r is None or len(r) != len(spy_returns):
        return None
    if len(r) < 5:
        return None
    try:
        n = len(r)
        mean_x = sum(spy_returns) / n
        mean_y = sum(r) / n
        # OLS slope + intercept for y = alpha + beta * x
        var_x = sum((x - mean_x) ** 2 for x in spy_returns) / max(1, n - 1)
        cov_xy = sum((spy_returns[i] - mean_x) * (r[i] - mean_y) for i in range(n)) / max(1, n - 1)
        if var_x <= 0:
            return None
        beta = cov_xy / var_x
        alpha = mean_y - beta * mean_x
        residuals = [r[i] - alpha - beta * spy_returns[i] for i in range(n)]
        mean_res = sum(residuals) / n
        var_res = sum((res - mean_res) ** 2 for res in residuals) / max(1, n - 1)
        return var_res ** 0.5
    except Exception:
        return None


def compute(
    symbols: list[str],
    db: Session,
    params: dict,
) -> dict[str, float]:
    """Return {ticker: -idio_vol}. Higher (less negative) = lower idio vol.

    Long the top decile = the lowest-IVOL names, per Ang et al.'s
    long-only implementation.
    """
    window_days = int(params.get("window_days", 21))

    # SPY benchmark series — fetched once, reused for every regression.
    spy_returns = _fetch_returns("SPY", window_days)
    if spy_returns is None:
        logger.error("[factor:idio_volatility] SPY benchmark fetch failed — no scores")
        return {}

    scores: dict[str, float] = {}
    for i, sym in enumerate(symbols):
        v = _idio_vol(sym, spy_returns, window_days)
        if v is None or v <= 0:
            continue
        scores[sym] = -float(v)  # Negate: low IVOL becomes high score
        if (i + 1) % 50 == 0:
            logger.warning(
                "[factor:idio_volatility] progress %d/%d, scored=%d",
                i + 1, len(symbols), len(scores),
            )
    logger.warning(
        "[factor:idio_volatility] done: universe=%d scored=%d skipped=%d",
        len(symbols), len(scores), len(symbols) - len(scores),
    )
    return scores
