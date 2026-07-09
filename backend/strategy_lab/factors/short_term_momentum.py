"""Factor: Short-term momentum conditioned on turnover.

Source: Medhat & Schmeling, "Short-term Momentum," Review of Financial
Studies 2022. SSRN: https://ssrn.com/abstract=3150525

The classic 12-1 UMD momentum explicitly SKIPS month t-1 to avoid the
1-month reversal. Medhat-Schmeling show the skipped month is not a
reversal at all when conditioned on turnover: high-turnover winners
in month t-1 continue to win in month t, at a rate comparable to
conventional 12-1 momentum.

Signal construction:
    score = ret_1m if turnover_1m is in top half of universe, else None

Rebalance: monthly. Long the top decile of scored names.

Params:
    lookback_days   trading days for return + turnover window (default 21)
    turnover_cutoff percentile threshold for turnover filter (default 0.5)

Data source: yfinance daily bars (close + volume). Turnover proxy uses
average daily $ volume over the window since yfinance shares-outstanding
lookups are unreliable per-symbol; the cross-sectional ranking is invariant
to whether we use raw dollar volume vs turnover-normalized dollar volume.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _fetch_window(ticker: str, days: int) -> Optional[tuple[float, float, float]]:
    """Return (ret_1m, avg_dollar_volume, sample_days) for the last `days`.

    ret_1m = close[-1] / close[-days] - 1
    avg_dollar_volume = mean(close * volume) over the window
    """
    try:
        import yfinance as yf  # type: ignore
    except Exception as exc:
        logger.warning("[factor:short_term_momentum] yfinance import failed: %s", exc)
        return None

    end = datetime.now(timezone.utc)
    # 60 calendar days buys us ~40 trading days; enough for a 21-day window
    # even with holidays / spotty data.
    start = end - timedelta(days=max(60, int(days * 2) + 20))
    try:
        hist = yf.Ticker(ticker).history(
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            interval="1d",
            auto_adjust=True,
        )
    except Exception as exc:
        logger.debug("[factor:short_term_momentum] %s history fetch failed: %s", ticker, exc)
        return None
    if hist is None or hist.empty:
        return None
    if len(hist) < days + 1:
        return None
    try:
        close_last = float(hist["Close"].iloc[-1])
        close_first = float(hist["Close"].iloc[-days])
        vol_window = hist.iloc[-days:]
        avg_dollar_vol = float((vol_window["Close"] * vol_window["Volume"]).mean())
    except (KeyError, IndexError, ValueError):
        return None
    if close_first <= 0 or close_last <= 0 or avg_dollar_vol <= 0:
        return None
    ret_1m = close_last / close_first - 1.0
    return (ret_1m, avg_dollar_vol, float(days))


def compute(
    symbols: list[str],
    db: Session,
    params: dict,
) -> dict[str, float]:
    """Return {ticker: ret_1m} for the top-turnover half of scored symbols."""
    lookback_days = int(params.get("lookback_days", 21))
    turnover_cutoff = float(params.get("turnover_cutoff", 0.5))

    raw: dict[str, tuple[float, float]] = {}
    for i, sym in enumerate(symbols):
        w = _fetch_window(sym, lookback_days)
        if w is None:
            continue
        ret_1m, avg_dv, _ = w
        raw[sym] = (ret_1m, avg_dv)
        if (i + 1) % 50 == 0:
            logger.warning(
                "[factor:short_term_momentum] progress %d/%d, scored=%d",
                i + 1, len(symbols), len(raw),
            )

    if not raw:
        logger.warning("[factor:short_term_momentum] no data — returning empty scores")
        return {}

    # Turnover filter: keep top half by avg dollar volume
    sorted_by_dv = sorted(raw.items(), key=lambda kv: -kv[1][1])
    keep_n = max(1, int(len(sorted_by_dv) * (1.0 - turnover_cutoff)))
    kept_syms = {s for s, _ in sorted_by_dv[:keep_n]}

    scores = {s: raw[s][0] for s in kept_syms}
    logger.warning(
        "[factor:short_term_momentum] done: universe=%d fetched=%d kept_top_turnover=%d",
        len(symbols), len(raw), len(scores),
    )
    return scores
