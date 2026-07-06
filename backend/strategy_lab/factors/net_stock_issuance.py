"""Factor: Net Stock Issuance (Pontiff-Woodgate 2008, Fama-French 2008).

Score for each ticker: negative log growth in shares outstanding over
the trailing year. Higher score = larger net repurchase = long side.

Reference: BMG-Strategy-Knowledge-Vault-v1.md Section 1.12.
  - PW 1970-2003: hedge return ~11% annual, t-stat ~5-6
  - "Remarkably persistent" per vault decay landscape
  - Long side (net repurchasers) is where recent alpha lives
  - Annual rebalance, low turnover

Data: yfinance ticker.info shares_outstanding (current) vs 1-year prior
via balance_sheet columns. If neither yields two comparable share counts,
skip the ticker.
"""
from __future__ import annotations

import logging
import math
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _fetch_share_growth(ticker: str) -> Optional[float]:
    try:
        import yfinance as yf  # type: ignore
    except Exception as exc:
        logger.warning("[factor:net_stock_issuance] yfinance import failed: %s", exc)
        return None

    t = yf.Ticker(ticker)

    # Try annual balance sheet — has "Ordinary Shares Number" or similar per year.
    try:
        bs = t.balance_sheet
        if bs is not None and not bs.empty:
            for label in (
                "Ordinary Shares Number",
                "Common Stock Shares Outstanding",
                "Share Issued",
                "Common Stock",
            ):
                if label in bs.index:
                    row = bs.loc[label].dropna()
                    if len(row) >= 2:
                        current = float(row.iloc[0])
                        prior = float(row.iloc[1])
                        if current > 0 and prior > 0:
                            return math.log(current / prior)
                        break
    except Exception as exc:
        logger.debug("[factor:net_stock_issuance] %s balance path failed: %s", ticker, exc)

    return None


def compute(
    symbols: list[str],
    db: Session,
    params: dict,
) -> dict[str, float]:
    """Return {ticker: -log(shares_now / shares_1y_ago)}.

    Higher score = more negative share growth = net repurchaser.
    Long the top decile.
    """
    scores: dict[str, float] = {}
    skipped = 0
    for i, sym in enumerate(symbols):
        v = _fetch_share_growth(sym)
        if v is None:
            skipped += 1
            continue
        # Negate so repurchasers rank high.
        scores[sym] = -float(v)
        if (i + 1) % 50 == 0:
            logger.warning(
                "[factor:net_stock_issuance] progress %d/%d, scored=%d skipped=%d",
                i + 1, len(symbols), len(scores), skipped,
            )
    logger.warning(
        "[factor:net_stock_issuance] done: universe=%d scored=%d skipped=%d",
        len(symbols), len(scores), skipped,
    )
    return scores
