"""Factor: Novy-Marx Gross Profitability (2013, SSRN 2049783).

Score for each ticker:
    (Revenue_ttm - COGS_ttm) / Total_Assets_latest
    = Gross Profit / Total Assets

Higher score means more gross profit generated per dollar of assets — the
classic quality signal that survived the McLean-Pontiff 32% decay average
because it captures a real operating characteristic, not a mispricing.

Data source hierarchy:
    1. yfinance ticker.info (grossProfits, totalAssets) - fastest
    2. yfinance ticker.income_stmt + balance_sheet - more reliable but slower

Fail-loud on missing fundamentals: log to warning and skip. The runner
counts skips so we can see if the data feed is degrading.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _fetch_gp_over_assets(ticker: str) -> Optional[float]:
    try:
        import yfinance as yf  # type: ignore
    except Exception as exc:
        logger.warning("[factor:novy_marx_gp_a] yfinance import failed: %s", exc)
        return None

    t = yf.Ticker(ticker)

    # Try the fast path first: yfinance's cached info dict.
    try:
        info = t.info or {}
        gp = info.get("grossProfits")
        ta = info.get("totalAssets")
        if gp is not None and ta is not None:
            gp_f = float(gp)
            ta_f = float(ta)
            if ta_f > 0:
                return gp_f / ta_f
    except Exception as exc:
        logger.debug("[factor:novy_marx_gp_a] %s info path failed: %s", ticker, exc)

    # Fallback: pull income and balance sheet statements.
    try:
        income = t.income_stmt
        bs = t.balance_sheet
        if income is None or bs is None:
            return None
        # Take most recent column (latest fiscal period).
        rev = None
        cogs = None
        for label in ("Total Revenue", "Revenue"):
            if label in income.index:
                rev = float(income.loc[label].iloc[0])
                break
        for label in ("Cost Of Revenue", "Cost of Revenue"):
            if label in income.index:
                cogs = float(income.loc[label].iloc[0])
                break
        ta_val = None
        for label in ("Total Assets",):
            if label in bs.index:
                ta_val = float(bs.loc[label].iloc[0])
                break
        if rev is None or cogs is None or ta_val is None or ta_val <= 0:
            return None
        return (rev - cogs) / ta_val
    except Exception as exc:
        logger.debug("[factor:novy_marx_gp_a] %s statements path failed: %s", ticker, exc)
        return None


def compute(
    symbols: list[str],
    db: Session,
    params: dict,
) -> dict[str, float]:
    """Return {ticker: score} where score = (revenue_ttm - cogs_ttm) / total_assets.

    Missing fundamentals → ticker skipped and logged. Bank names typically
    return None here because they lack a meaningful COGS line; that is
    correct behavior per Novy-Marx (financials excluded from the original
    universe).
    """
    scores: dict[str, float] = {}
    skipped = 0
    for i, sym in enumerate(symbols):
        val = _fetch_gp_over_assets(sym)
        if val is None:
            skipped += 1
            continue
        scores[sym] = float(val)
        if (i + 1) % 50 == 0:
            logger.warning(
                "[factor:novy_marx_gp_a] progress %d/%d, scored=%d skipped=%d",
                i + 1, len(symbols), len(scores), skipped,
            )
    logger.warning(
        "[factor:novy_marx_gp_a] done: universe=%d scored=%d skipped=%d",
        len(symbols), len(scores), skipped,
    )
    return scores
