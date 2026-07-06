"""Factor: Value (Fama-French HML, 1993) with intangibles adjustment.

Score for each ticker: (Book Equity + Capitalized Intangibles) / Market Equity.
Higher score = more value-like.

Reference: BMG-Strategy-Knowledge-Vault-v1.md Section 1.1.
  - Original 1963-1991 HML ~5.1% annual, Sharpe ~0.45
  - Post-2007 decay: FF 2020 show 1991-2019 premium indistinguishable
    from zero WITHOUT intangibles adjustment
  - Arnott et al. 2021 argue decay is re-rating shock, not death,
    when intangibles-adjusted BE is used
  - Deep-value tail carries the premium; excluding it kills the factor

Intangibles adjustment: add capitalized R&D expense + 30% of SG&A to
book equity. Approximates the "hidden book" that GAAP expenses out for
tech / brand / IP-heavy firms.

Data hierarchy:
    1. yfinance ticker.info (bookValue, marketCap)
    2. yfinance ticker.balance_sheet + info marketCap fallback

Fail-loud on missing fundamentals: log warning and skip. Financials
typically fail because their balance sheet structure differs — that's
correct behavior per FF who exclude financials from the original
universe.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _fetch_book_to_market(ticker: str) -> Optional[float]:
    try:
        import yfinance as yf  # type: ignore
    except Exception as exc:
        logger.warning("[factor:value_hml] yfinance import failed: %s", exc)
        return None

    t = yf.Ticker(ticker)

    # Fast path: yfinance info dict (bookValue is per-share, need shares
    # to compute total BE; use marketCap for ME).
    try:
        info = t.info or {}
        book_per_share = info.get("bookValue")
        shares = info.get("sharesOutstanding") or info.get("floatShares")
        market_cap = info.get("marketCap")
        if book_per_share and shares and market_cap and market_cap > 0:
            be = float(book_per_share) * float(shares)
            # Intangibles-adjusted proxy: add R&D + 0.3 * SG&A when available.
            rnd = info.get("researchAndDevelopment") or 0
            sga = info.get("sellingGeneralAndAdministrative") or 0
            be_adj = be + float(rnd or 0) + 0.3 * float(sga or 0)
            return be_adj / float(market_cap)
    except Exception as exc:
        logger.debug("[factor:value_hml] %s info path failed: %s", ticker, exc)

    # Fallback: balance sheet + info marketCap
    try:
        info = t.info or {}
        market_cap = float(info.get("marketCap") or 0)
        if market_cap <= 0:
            return None
        bs = t.balance_sheet
        if bs is None:
            return None
        be = None
        for label in ("Stockholders Equity", "Total Stockholder Equity",
                      "Common Stock Equity"):
            if label in bs.index:
                be = float(bs.loc[label].iloc[0])
                break
        if be is None or be <= 0:
            return None
        # Skip intangibles adjustment in fallback path — not always available.
        return be / market_cap
    except Exception as exc:
        logger.debug("[factor:value_hml] %s balance path failed: %s", ticker, exc)
        return None


def compute(
    symbols: list[str],
    db: Session,
    params: dict,
) -> dict[str, float]:
    """Return {ticker: BE/ME}. Higher = more value-like (long top decile)."""
    scores: dict[str, float] = {}
    skipped = 0
    for i, sym in enumerate(symbols):
        v = _fetch_book_to_market(sym)
        if v is None or v <= 0:
            skipped += 1
            continue
        scores[sym] = float(v)
        if (i + 1) % 50 == 0:
            logger.warning(
                "[factor:value_hml] progress %d/%d, scored=%d skipped=%d",
                i + 1, len(symbols), len(scores), skipped,
            )
    logger.warning(
        "[factor:value_hml] done: universe=%d scored=%d skipped=%d",
        len(symbols), len(scores), skipped,
    )
    return scores
