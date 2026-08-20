"""Factor: VIX-Regime-Dependent Momentum (Alpha Architect / Mesicek 2026).

Reference: "VIX and Trend Following Revisited" — 9-yr OOS evidence from
Aug 2017 to Jun 2026. VIX-Top-1 delivered 14.09% net CAGR vs 9.87% for
fixed 10-month momentum; Sharpe 1.03 vs 0.81; max DD −11.02% vs −12.99%.

Mechanic: momentum lookback length is a function of current VIX regime.
    Green regime (VIX low)   → 12-month lookback  (slow, filters noise)
    Yellow regime (VIX med)  → 6-month lookback   (mid-speed)
    Red regime (VIX high)    → 3-month lookback   (fast, adapts to shocks)

Ranks a small ETF universe (SPY, VXF, EFA, AGG, BIL) by the regime-
appropriate lookback and returns scores. Runtime should use long_decile=10
with position_sizing=equal_weight and long_only=True, top-1 selection —
paper found Top-1 works, Top-2 dilutes to fixed-lookback performance.

Regime bands (from paper — VIX close on signal day):
    Green:  VIX <= 20
    Yellow: 20 < VIX <= 30
    Red:    VIX > 30

Params:
    green_months: default 12
    yellow_months: default 6
    red_months: default 3

Data: yfinance daily close for each ETF + ^VIX index.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _current_vix() -> Optional[float]:
    """Latest ^VIX close from yfinance."""
    try:
        import yfinance as yf  # type: ignore
    except Exception as exc:
        logger.warning("[factor:vix_regime_rotation] yfinance import failed: %s", exc)
        return None
    try:
        hist = yf.Ticker("^VIX").history(period="5d", interval="1d")
    except Exception as exc:
        logger.warning("[factor:vix_regime_rotation] ^VIX fetch failed: %s", exc)
        return None
    if hist is None or hist.empty:
        return None
    try:
        return float(hist["Close"].iloc[-1])
    except (KeyError, IndexError, ValueError):
        return None


def _regime_lookback_months(vix: float, params: dict) -> int:
    green = int(params.get("green_months", 12))
    yellow = int(params.get("yellow_months", 6))
    red = int(params.get("red_months", 3))
    if vix > 30:
        return red
    if vix > 20:
        return yellow
    return green


def _return_over_lookback(ticker: str, months_back: int) -> Optional[float]:
    try:
        import yfinance as yf  # type: ignore
    except Exception as exc:
        logger.warning("[factor:vix_regime_rotation] yfinance import failed: %s", exc)
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
        logger.warning("[factor:vix_regime_rotation] %s fetch failed: %s", ticker, exc)
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
    """Return {ticker: return_over_regime_lookback}. Higher = better.

    Universe should be the 5-ETF set: SPY, VXF, EFA, AGG, BIL.
    Runtime should use long_decile=10 (top-1 with 5 assets), long-only.
    """
    vix = _current_vix()
    if vix is None:
        logger.warning("[factor:vix_regime_rotation] no VIX — cannot select regime")
        return {}
    lookback = _regime_lookback_months(vix, params)
    regime = "green" if lookback == int(params.get("green_months", 12)) else \
             ("yellow" if lookback == int(params.get("yellow_months", 6)) else "red")
    logger.warning(
        "[factor:vix_regime_rotation] VIX=%.2f regime=%s lookback=%dmo universe=%d",
        vix, regime, lookback, len(symbols),
    )
    scores: dict[str, float] = {}
    for sym in symbols:
        r = _return_over_lookback(sym, lookback)
        if r is None:
            continue
        scores[sym] = float(r)
    logger.warning(
        "[factor:vix_regime_rotation] done: scored=%d skipped=%d",
        len(scores), len(symbols) - len(scores),
    )
    return scores
