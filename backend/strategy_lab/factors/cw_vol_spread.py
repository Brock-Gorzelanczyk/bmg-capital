"""Factor: Cremers-Weinbaum implied volatility spread.

Source: Cremers & Weinbaum, "Deviations from Put-Call Parity and Stock
Return Predictability," JFQA 2010. SSRN: https://ssrn.com/abstract=968237

Signal:
    vol_spread(t) = sum over matched (strike, expiry) pairs of
                    OI_pair * (IV_call - IV_put) / sum(OI_pair)

Higher vol_spread => calls relatively more expensive than puts, which
Cremers-Weinbaum interpret as informed buying pressure on calls. Long
top-decile of vol_spread, short bottom.

Rebalance: weekly.

Params:
    dte_min    minimum days-to-expiry for pairs (default 15)
    dte_max    maximum DTE (default 60)
    max_pairs  cap on matched pairs per symbol (default 12) — perf gate

Data source: yfinance option chains (Ticker.option_chain). Uses
impliedVolatility + openInterest columns.
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


def _compute_symbol_vol_spread(
    ticker: str,
    dte_min: int,
    dte_max: int,
    max_pairs: int,
) -> Optional[float]:
    try:
        import yfinance as yf  # type: ignore
    except Exception as exc:
        logger.warning("[factor:cw_vol_spread] yfinance import failed: %s", exc)
        return None

    try:
        yft = yf.Ticker(ticker)
        exps = list(yft.options or [])
    except Exception as exc:
        logger.debug("[factor:cw_vol_spread] %s options list failed: %s", ticker, exc)
        return None
    if not exps:
        return None

    today = date.today()

    numerator = 0.0
    denominator = 0.0
    pairs_used = 0

    for exp_str in exps:
        exp_date = _parse_expiry(exp_str)
        if exp_date is None:
            continue
        dte = (exp_date - today).days
        if dte < dte_min or dte > dte_max:
            continue
        try:
            chain = yft.option_chain(exp_str)
        except Exception as exc:
            logger.debug(
                "[factor:cw_vol_spread] %s option_chain(%s) failed: %s",
                ticker, exp_str, exc,
            )
            continue

        try:
            calls_df = chain.calls[["strike", "impliedVolatility", "openInterest"]].copy()
            puts_df = chain.puts[["strike", "impliedVolatility", "openInterest"]].copy()
        except Exception:
            continue

        merged = calls_df.merge(
            puts_df,
            on="strike",
            suffixes=("_call", "_put"),
            how="inner",
        )
        if merged.empty:
            continue

        for _, row in merged.iterrows():
            iv_c = float(row.get("impliedVolatility_call", 0) or 0)
            iv_p = float(row.get("impliedVolatility_put", 0) or 0)
            oi_c = float(row.get("openInterest_call", 0) or 0)
            oi_p = float(row.get("openInterest_put", 0) or 0)
            if iv_c <= 0 or iv_p <= 0:
                continue
            if math.isnan(iv_c) or math.isnan(iv_p):
                continue
            # OI weight = minimum of the two legs (both must exist to be a "pair")
            oi_weight = min(oi_c, oi_p)
            if oi_weight <= 0:
                continue
            numerator += oi_weight * (iv_c - iv_p)
            denominator += oi_weight
            pairs_used += 1
            if pairs_used >= max_pairs:
                break
        if pairs_used >= max_pairs:
            break

    if denominator <= 0 or pairs_used == 0:
        return None
    return float(numerator / denominator)


def compute(
    symbols: list[str],
    db: Session,
    params: dict,
) -> dict[str, float]:
    dte_min = int(params.get("dte_min", 15))
    dte_max = int(params.get("dte_max", 60))
    max_pairs = int(params.get("max_pairs", 12))

    scores: dict[str, float] = {}
    for i, sym in enumerate(symbols):
        s = _compute_symbol_vol_spread(sym, dte_min, dte_max, max_pairs)
        if s is None:
            continue
        scores[sym] = s
        if (i + 1) % 20 == 0:
            logger.warning(
                "[factor:cw_vol_spread] progress %d/%d, scored=%d",
                i + 1, len(symbols), len(scores),
            )

    logger.warning(
        "[factor:cw_vol_spread] done: universe=%d scored=%d",
        len(symbols), len(scores),
    )
    return scores
