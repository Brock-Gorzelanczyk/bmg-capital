"""Factor: Intramonth Momentum (Nathan-Suominen-Tasa 2026, SSRN 6426026).

Momentum profits concentrate in a 6-trading-day window before month-end
("PreTOM"). Mechanism: institutional dash-for-cash — investors sell losers
to fund month-end payment obligations, creating predictable selling
pressure in bottom-decile stocks.

Empirical result (1980-2025): value-weighted WML during PreTOM turns
$1 into $18.78, vs $2.37 during rest-of-month. Losers drive the effect
(bottom-decile stocks underperform by an extra 7.2 bps/day in the
window); winners show little pattern. Replicates across 19 developed
markets. Causal ID via SEC's May 2024 T+2→T+1 transition (window
shifted by exactly one day).

Implementation: this factor SCORES the same 12-1 momentum universe.
The scheduling constraint (only trade during PreTOM window) belongs
in the runner / rebalance_schedule, not here. Ship with schedule
that fires monthly on business day -8 approx (portfolio_rank runner
default). Follow-up: add PreTOM-aware schedule kind to runner.

Scoring: raw 12-1 return (t-12mo to t-1mo, skipping most recent month
to avoid short-term reversal). Runtime uses short_decile=0 semantic —
we want to SHORT the losers, not long the winners.

Reference: BMG SSRN batch 7 (this file), ledger of alpha ideas
2026-08-20.

Params:
    lookback_months: total window (default 12)
    skip_months: recent months to skip (default 1)

Data: yfinance daily bars.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _fetch_12_1_return(ticker: str, lookback_months: int, skip_months: int) -> Optional[float]:
    """Return simple return from t-lookback to t-skip (i.e., 12-1 momentum)."""
    try:
        import yfinance as yf  # type: ignore
    except Exception as exc:
        logger.warning("[factor:intramonth_dashforcash] yfinance import failed: %s", exc)
        return None

    end = datetime.now(timezone.utc) - timedelta(days=int(skip_months * 21))
    start = end - timedelta(days=int((lookback_months - skip_months) * 32))
    try:
        hist = yf.Ticker(ticker).history(
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            interval="1d",
            auto_adjust=True,
        )
    except Exception as exc:
        logger.warning("[factor:intramonth_dashforcash] %s fetch failed: %s", ticker, exc)
        return None
    if hist is None or hist.empty or len(hist) < 30:
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
    """Return {ticker: 12-1 momentum score}. Higher = better past performer.

    Runtime should use long_decile=0, short_decile=10 to isolate the
    loser-driven alpha per the paper's asymmetric finding.
    """
    lookback = int(params.get("lookback_months", 12))
    skip = int(params.get("skip_months", 1))
    scores: dict[str, float] = {}
    for i, sym in enumerate(symbols):
        r = _fetch_12_1_return(sym, lookback, skip)
        if r is None:
            continue
        scores[sym] = float(r)
        if (i + 1) % 25 == 0:
            logger.warning(
                "[factor:intramonth_dashforcash] progress %d/%d scored=%d",
                i + 1, len(symbols), len(scores),
            )
    logger.warning(
        "[factor:intramonth_dashforcash] done: universe=%d scored=%d skipped=%d",
        len(symbols), len(scores), len(symbols) - len(scores),
    )
    return scores
