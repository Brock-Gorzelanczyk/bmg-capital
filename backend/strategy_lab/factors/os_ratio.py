"""Factor: options/stock volume ratio (O/S).

Source: Roll, Schwartz & Subrahmanyam (2010) "O/S: The Relative Trading
Activity in Options and Stock." SSRN https://ssrn.com/abstract=1410091.
Follow-up: Johnson & So (2012) "The Option to Stock Volume Ratio and Future
Returns," JFE 106(2). Also Ge-Lin-Pearson (2016).

Signal:
    os = sum_option_volume_all_strikes(0-45 DTE) / avg_daily_stock_volume(5d)

Cross-sectional interpretation (Johnson-So 2012): low O/S predicts positive
returns (calm informed positioning), high O/S predicts negative returns
(bearish informed positioning taking advantage of short-sale frictions).

Score returned is NEGATIVE O/S so the portfolio-rank runner's descending
sort puts low-O/S names in the LONG bucket (top decile).

Rebalance: weekly.

Params:
    dte_max        include options with DTE <= this (default 45)
    stock_vol_days rolling window for stock volume average (default 5)
    min_option_vol per-name filter — skip if total option volume < this
                   (default 100 contracts) to reject illiquid noise

Data source: yfinance Ticker.option_chain per expiry (volume + openInterest
per row) + Ticker.history for stock volume. No paid feeds.
"""
from __future__ import annotations

import logging
import math
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _parse_expiry(exp_str: str) -> Optional[date]:
    try:
        return datetime.strptime(exp_str, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _compute_symbol_os(
    ticker: str,
    dte_max: int,
    stock_vol_days: int,
    min_option_vol: int,
) -> Optional[float]:
    try:
        import yfinance as yf  # type: ignore
    except Exception as exc:
        logger.warning("[factor:os_ratio] yfinance import failed: %s", exc)
        return None

    try:
        yft = yf.Ticker(ticker)
        exps = list(yft.options or [])
    except Exception as exc:
        logger.debug("[factor:os_ratio] %s options list failed: %s", ticker, exc)
        return None
    if not exps:
        return None

    today = date.today()
    option_volume = 0
    for exp_str in exps:
        exp_date = _parse_expiry(exp_str)
        if exp_date is None:
            continue
        dte = (exp_date - today).days
        if dte < 0 or dte > dte_max:
            continue
        try:
            chain = yft.option_chain(exp_str)
        except Exception:
            continue
        try:
            option_volume += int(chain.calls["volume"].fillna(0).sum())
            option_volume += int(chain.puts["volume"].fillna(0).sum())
        except Exception:
            continue

    if option_volume < min_option_vol:
        return None

    # Stock volume: 5-day rolling mean
    try:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=stock_vol_days * 3 + 10)
        hist = yft.history(
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            interval="1d",
            auto_adjust=True,
        )
    except Exception:
        return None
    if hist is None or hist.empty or "Volume" not in hist.columns:
        return None
    try:
        stock_vol = float(hist["Volume"].tail(stock_vol_days).mean())
    except Exception:
        return None
    if stock_vol <= 0 or math.isnan(stock_vol):
        return None

    os_ratio = option_volume / stock_vol
    # NEGATIVE so the descending-sort runner puts LOW O/S first (long-decile)
    return -float(os_ratio)


def compute(
    symbols: list[str],
    db: Session,
    params: dict,
) -> dict[str, float]:
    dte_max = int(params.get("dte_max", 45))
    stock_vol_days = int(params.get("stock_vol_days", 5))
    min_option_vol = int(params.get("min_option_vol", 100))

    scores: dict[str, float] = {}
    for i, sym in enumerate(symbols):
        s = _compute_symbol_os(sym, dte_max, stock_vol_days, min_option_vol)
        if s is None:
            continue
        scores[sym] = s
        if (i + 1) % 20 == 0:
            logger.warning(
                "[factor:os_ratio] progress %d/%d, scored=%d",
                i + 1, len(symbols), len(scores),
            )
    logger.warning(
        "[factor:os_ratio] done: universe=%d scored=%d",
        len(symbols), len(scores),
    )
    return scores
